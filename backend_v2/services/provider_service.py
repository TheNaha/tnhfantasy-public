# Provider Service - Business logic for provider management
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Dict, Any, List, Optional

from sqlmodel import Session

from core.entities import Provider, LoadBalancingConfig
from core.events import event_bus, Event, EventType, emit_provider_event
from core.exceptions import NotFoundError, ProviderError, ValidationError
from infrastructure.repositories import ProviderRepository, LoadBalancingRepository
from infrastructure.request_dedup import deduplicated, is_in_flight
from infrastructure.logging import provider_logger
from infrastructure.providers.provider_registry import ProviderRegistry
from api.provider_runtime import resolve_provider_runtime
from services.provider_deploy_orchestrator import (
    ProviderDeployOrchestrator,
    ProviderDeployStepExecutionError,
    ProviderDeployStepTimeoutError,
)

logger = provider_logger()


DEPLOY_STATE_KEY = "deploy_state"
DEPLOY_IN_PROGRESS_TTL = timedelta(minutes=30)
RECONCILIATION_STATE_KEY = "reconciliation_state"
RECONCILIATION_IN_PROGRESS_TTL = timedelta(minutes=180)
RECONCILIATION_IN_PROGRESS_STATUSES = {"queued", "reconciling"}
RECONCILIATION_TERMINAL_STATUSES = {"completed", "failed", "idle"}
RUNTIME_CONFIG_KEY = "runtime_config"
DEPLOY_CONFIG_KEY = "deploy_config"
SUPPORTED_MANAGED_DEPLOY_TYPES = {"modal", "beam"}
LEGACY_DEPLOY_CONFIG_FIELDS = {
    "app_name",
    "enable_memory_snapshot",
    "gpu_url",
    "storage_url",
    "download_url",
    "gpu_type",
}


class ProviderService:
    """
    Handles provider lifecycle and configuration.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.repo = ProviderRepository(session)
        self.lb_repo = LoadBalancingRepository(session)

    @staticmethod
    def _utcnow_iso() -> str:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

    @staticmethod
    def _parse_utc_timestamp(raw_value: Optional[str]) -> Optional[datetime]:
        if not raw_value:
            return None
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _clean_dict(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return deepcopy(value) if isinstance(value, dict) else {}

    @staticmethod
    def _mask_secret(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        if len(value) <= 6:
            return "*" * len(value)
        return f"{value[:3]}***{value[-3:]}"

    def _default_deploy_mode(self, provider_type: str) -> str:
        return "managed" if provider_type in SUPPORTED_MANAGED_DEPLOY_TYPES else "manual"

    def _default_deploy_targets(self, provider_type: str) -> List[Dict[str, Any]]:
        if provider_type == "modal":
            return [
                {
                    "name": "modal_app",
                    "entrypoint": "/app/modal_app.py",
                    "command": ["modal", "deploy", "/app/modal_app.py"],
                }
            ]
        if provider_type == "beam":
            return [
                {
                    "name": "comfy_gpu",
                    "entrypoint": "/app/beam_app.py:comfy_gpu",
                    "command": ["beta9", "deploy", "/app/beam_app.py:comfy_gpu"],
                },
                {
                    "name": "comfy_storage",
                    "entrypoint": "/app/beam_app.py:comfy_storage",
                    "command": ["beta9", "deploy", "/app/beam_app.py:comfy_storage"],
                },
                {
                    "name": "comfy_download",
                    "entrypoint": "/app/beam_app.py:comfy_download",
                    "command": ["beta9", "deploy", "/app/beam_app.py:comfy_download"],
                },
            ]
        return []

    @staticmethod
    def _normalize_deploy_step_command(provider_type: str, command: List[str]) -> List[str]:
        """Keep compatibility with older Beam configs that still reference `beam` CLI."""
        if provider_type == "beam" and command and command[0] == "beam":
            return ["beta9", *command[1:]]
        return command

    def _extract_runtime_config(self, provider_type: str, container_config: Any, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        runtime_config = self._clean_dict(config.get(RUNTIME_CONFIG_KEY))
        if not runtime_config:
            runtime_config = self._clean_dict(container_config)
        if not runtime_config:
            return None

        worker_config = self._clean_dict(config.get("worker"))
        if worker_config and "worker" not in runtime_config:
            runtime_config["worker"] = worker_config

        runtime_config.setdefault("mode", "container")
        if provider_type in SUPPORTED_MANAGED_DEPLOY_TYPES:
            runtime_config.setdefault("port", runtime_config.get("port", 8000))
        return runtime_config

    def _extract_deploy_config(self, provider_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        deploy_config = self._clean_dict(config.get(DEPLOY_CONFIG_KEY))

        for key in LEGACY_DEPLOY_CONFIG_FIELDS:
            if key in config and deploy_config.get(key) in (None, ""):
                deploy_config[key] = config[key]

        functions_config = self._clean_dict(config.get("functions"))
        if functions_config and "functions" not in deploy_config:
            deploy_config["functions"] = functions_config

        deploy_config.setdefault("deploy_mode", self._default_deploy_mode(provider_type))
        deploy_config.setdefault("targets", self._default_deploy_targets(provider_type))
        return deploy_config

    def _compose_config(
        self,
        *,
        base_config: Optional[Dict[str, Any]],
        runtime_config: Optional[Dict[str, Any]],
        deploy_config: Dict[str, Any],
        deploy_state: Optional[Dict[str, Any]] = None,
        reconciliation_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        config = self._clean_dict(base_config)
        config[RUNTIME_CONFIG_KEY] = runtime_config or None
        config[DEPLOY_CONFIG_KEY] = deploy_config

        if runtime_config is not None and runtime_config.get("worker") is not None:
            config["worker"] = runtime_config.get("worker")

        functions_config = self._clean_dict(deploy_config.get("functions"))
        if functions_config:
            config["functions"] = functions_config

        for key in LEGACY_DEPLOY_CONFIG_FIELDS:
            if key in deploy_config:
                config[key] = deploy_config[key]

        if deploy_state is not None:
            config[DEPLOY_STATE_KEY] = deploy_state
        elif DEPLOY_STATE_KEY not in config:
            config[DEPLOY_STATE_KEY] = {"status": "idle"}

        if reconciliation_state is not None:
            config[RECONCILIATION_STATE_KEY] = reconciliation_state
        elif RECONCILIATION_STATE_KEY not in config:
            config[RECONCILIATION_STATE_KEY] = {"status": "idle"}

        return config

    def _normalize_provider_for_storage(self, provider_data: Dict[str, Any], existing: Optional[Provider] = None) -> Dict[str, Any]:
        payload = deepcopy(provider_data)
        provider_type = payload.get("type") or getattr(existing, "type", "modal")
        existing_config = self._clean_dict(getattr(existing, "config", None))
        merged_config = self._clean_dict(existing_config)
        merged_config.update(self._clean_dict(payload.get("config")))

        raw_runtime_config = payload.get("runtime_config")
        if raw_runtime_config is None and "container_config" in payload:
            raw_runtime_config = payload.get("container_config")
        if raw_runtime_config is None:
            raw_runtime_config = self._extract_runtime_config(
                provider_type,
                getattr(existing, "container_config", None),
                merged_config,
            )
        else:
            raw_runtime_config = self._clean_dict(raw_runtime_config)

        raw_deploy_config = payload.get("deploy_config")
        if raw_deploy_config is None:
            raw_deploy_config = self._extract_deploy_config(provider_type, merged_config)
        else:
            raw_deploy_config = self._clean_dict(raw_deploy_config)

        deploy_config = self._extract_deploy_config(
            provider_type,
            {
                **merged_config,
                DEPLOY_CONFIG_KEY: raw_deploy_config,
            },
        )

        runtime_config = raw_runtime_config or None
        config = self._compose_config(
            base_config=merged_config,
            runtime_config=runtime_config,
            deploy_config=deploy_config,
            deploy_state=self._read_deploy_state(existing) if existing else None,
            reconciliation_state=self._read_reconciliation_state(existing) if existing else None,
        )

        return {
            "id": payload.get("id") or getattr(existing, "id", None),
            "type": provider_type,
            "enabled": payload.get("enabled", getattr(existing, "enabled", True)),
            "priority": payload.get("priority", getattr(existing, "priority", 1)),
            "credentials": self._clean_dict(payload.get("credentials", getattr(existing, "credentials", {}))),
            "container_config": runtime_config,
            "config": config,
        }

    def _ensure_provider_v2_shape(self, provider: Provider) -> Provider:
        # Reads should not mutate persisted provider records.
        return provider

    def _summarize_credentials(self, provider_type: str, credentials: Dict[str, Any], deploy_config: Dict[str, Any]) -> Dict[str, Any]:
        validation = ProviderRegistry.validate_provider(provider_type, credentials, deploy_config)
        configured_fields = sorted(
            key for key, value in credentials.items()
            if value not in (None, "", [], {})
        )
        account_label = (
            credentials.get("username")
            or credentials.get("workspace_id")
            or self._mask_secret(credentials.get("api_key"))
            or self._mask_secret(credentials.get("token_id"))
        )
        return {
            "configured_fields": configured_fields,
            "missing_required_credentials": validation.get("credentials", []),
            "missing_required_config": validation.get("config", []),
            "account_label": account_label,
            "has_credentials": bool(configured_fields),
            "ready": not validation.get("credentials") and not validation.get("config"),
        }

    def _build_capabilities(
        self,
        *,
        provider: Provider,
        runtime: Any,
        runtime_config: Optional[Dict[str, Any]],
        deploy_config: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Optional[str]]]:
        deploy_mode = deploy_config.get("deploy_mode", self._default_deploy_mode(provider.type))
        managed_deploy = deploy_mode == "managed" and provider.type in SUPPORTED_MANAGED_DEPLOY_TYPES
        runtime_available = runtime_config is not None

        capabilities = {
            "container": runtime_available,
            "start_container": runtime_available,
            "stop_container": runtime_available,
            "restart_container": runtime_available,
            "view_logs": runtime_available,
            "deploy": managed_deploy,
            "setup": provider.type == "modal" and runtime_available,
            "reconcile": runtime.supports_reconciliation,
            "reset_status": True,
            "manual_deploy": deploy_mode == "manual",
            "managed_deploy": managed_deploy,
            "runtime_only": runtime_available and not managed_deploy,
        }

        reasons = {
            "deploy": None if managed_deploy else (
                "Provider is configured for manual deploy"
                if deploy_mode == "manual"
                else "Managed deploy is unavailable for this provider"
            ),
            "setup": None if capabilities["setup"] else "Setup is only available for Modal providers with a runtime container",
            "reconcile": None if capabilities["reconcile"] else "Runtime worker is unavailable",
        }
        return capabilities, reasons

    def build_provider_environment(self, provider: Provider) -> Dict[str, str]:
        provider = self._ensure_provider_v2_shape(provider)
        runtime_config = self._extract_runtime_config(provider.type, provider.container_config, provider.config or {}) or {}
        deploy_config = self._extract_deploy_config(provider.type, provider.config or {})
        credentials = self._clean_dict(provider.credentials)

        env_vars: Dict[str, str] = {}
        worker_config = self._clean_dict(runtime_config.get("worker"))
        if "max_concurrent_downloads" in worker_config:
            env_vars["MAX_CONCURRENT_DOWNLOADS"] = str(worker_config["max_concurrent_downloads"])
        if "reconciliation_interval_seconds" in worker_config:
            env_vars["RECONCILIATION_INTERVAL_SECONDS"] = str(int(float(worker_config["reconciliation_interval_seconds"])))
        elif "reconciliation_interval_hours" in worker_config:
            env_vars["RECONCILIATION_INTERVAL_SECONDS"] = str(
                int(float(worker_config["reconciliation_interval_hours"]) * 3600)
            )
        if "reconciliation_startup_delay_seconds" in worker_config:
            env_vars["RECONCILIATION_STARTUP_DELAY_SECONDS"] = str(
                int(float(worker_config["reconciliation_startup_delay_seconds"]))
            )
        if "validation_timeout_seconds" in worker_config:
            env_vars["VALIDATION_TIMEOUT_SECONDS"] = str(worker_config["validation_timeout_seconds"])

        if "hf_token" in credentials:
            env_vars["HF_TOKEN"] = credentials["hf_token"]
        if "civitai_token" in credentials:
            env_vars["CIVITAI_TOKEN"] = credentials["civitai_token"]

        if provider.type == "modal":
            if "token_id" in credentials:
                env_vars["MODAL_TOKEN_ID"] = credentials["token_id"]
            if "token_secret" in credentials:
                env_vars["MODAL_TOKEN_SECRET"] = credentials["token_secret"]
            if "username" in credentials:
                env_vars["MODAL_USERNAME"] = credentials["username"]
            if "app_name" in deploy_config:
                env_vars["MODAL_APP_NAME"] = deploy_config["app_name"]
            if "enable_memory_snapshot" in deploy_config:
                env_vars["ENABLE_MEMORY_SNAPSHOT"] = str(bool(deploy_config["enable_memory_snapshot"])).lower()

            comfyui = self._clean_dict(self._clean_dict(deploy_config.get("functions")).get("comfyui"))
            if "gpu_type" in comfyui:
                env_vars["MODAL_GPU_TYPE"] = comfyui["gpu_type"]
            if "cpu" in comfyui:
                env_vars["MODAL_GPU_CPU"] = str(comfyui["cpu"])
            if "timeout_seconds" in comfyui:
                env_vars["MODAL_GPU_TIMEOUT"] = str(comfyui["timeout_seconds"])
            if "max_containers" in comfyui:
                env_vars["MODAL_GPU_MAX_CONTAINERS"] = str(comfyui["max_containers"])
            if "scaledown_window_seconds" in comfyui:
                env_vars["MODAL_GPU_SCALEDOWN"] = str(comfyui["scaledown_window_seconds"])
            if "stall_timeout_seconds" in comfyui:
                env_vars["MODAL_COMFYUI_STALL_TIMEOUT_SECONDS"] = str(comfyui["stall_timeout_seconds"])
            if "max_runs_before_restart" in comfyui:
                env_vars["MODAL_COMFYUI_MAX_RUNS_BEFORE_RESTART"] = str(comfyui["max_runs_before_restart"])
            if "healthcheck_timeout_seconds" in comfyui:
                env_vars["MODAL_COMFYUI_HEALTHCHECK_TIMEOUT_SECONDS"] = str(comfyui["healthcheck_timeout_seconds"])
            if "capture_stall_diagnostics" in comfyui:
                env_vars["MODAL_COMFYUI_CAPTURE_STALL_DIAGNOSTICS"] = str(bool(comfyui["capture_stall_diagnostics"])).lower()
            if "stall_diagnostics_timeout_seconds" in comfyui:
                env_vars["MODAL_COMFYUI_STALL_DIAGNOSTICS_TIMEOUT_SECONDS"] = str(comfyui["stall_diagnostics_timeout_seconds"])
            if "stall_diagnostics_max_chars" in comfyui:
                env_vars["MODAL_COMFYUI_STALL_DIAGNOSTICS_MAX_CHARS"] = str(comfyui["stall_diagnostics_max_chars"])

            download = self._clean_dict(self._clean_dict(deploy_config.get("functions")).get("download"))
            if "timeout_seconds" in download:
                env_vars["MODAL_DOWNLOAD_TIMEOUT"] = str(download["timeout_seconds"])
            if "max_containers" in download:
                env_vars["MODAL_DOWNLOAD_MAX_CONTAINERS"] = str(download["max_containers"])

            storage = self._clean_dict(self._clean_dict(deploy_config.get("functions")).get("storage"))
            if "timeout_seconds" in storage:
                env_vars["MODAL_STORAGE_TIMEOUT"] = str(storage["timeout_seconds"])
            if "max_containers" in storage:
                env_vars["MODAL_STORAGE_MAX_CONTAINERS"] = str(storage["max_containers"])

        elif provider.type == "beam":
            if "api_key" in credentials:
                env_vars["BEAM_API_KEY"] = credentials["api_key"]
            if "workspace_id" in credentials:
                env_vars["BEAM_WORKSPACE_ID"] = credentials["workspace_id"]
            if "gpu_url" in deploy_config:
                env_vars["BEAM_GPU_URL"] = deploy_config["gpu_url"]
            if "storage_url" in deploy_config:
                env_vars["BEAM_STORAGE_URL"] = deploy_config["storage_url"]
            if "download_url" in deploy_config:
                env_vars["BEAM_DOWNLOAD_URL"] = deploy_config["download_url"]
            if "gpu_type" in deploy_config:
                env_vars["BEAM_GPU_TYPE"] = deploy_config["gpu_type"]

            beam_functions = self._clean_dict(deploy_config.get("functions"))
            gpu_func = self._clean_dict(beam_functions.get("comfyui"))
            if "gpu_type" in gpu_func:
                env_vars["BEAM_GPU_TYPE"] = gpu_func["gpu_type"]
            if "cpu" in gpu_func:
                env_vars["BEAM_GPU_CPU"] = str(gpu_func["cpu"])
            if "memory" in gpu_func:
                env_vars["BEAM_GPU_MEMORY"] = str(gpu_func["memory"])
            if "timeout_seconds" in gpu_func:
                env_vars["BEAM_GPU_TIMEOUT"] = str(gpu_func["timeout_seconds"])
            if "keep_warm_seconds" in gpu_func:
                env_vars["BEAM_GPU_KEEP_WARM"] = str(gpu_func["keep_warm_seconds"])
            if "concurrent_requests" in gpu_func:
                env_vars["BEAM_GPU_CONCURRENT"] = str(gpu_func["concurrent_requests"])

            download = self._clean_dict(beam_functions.get("download"))
            if "cpu" in download:
                env_vars["BEAM_DOWNLOAD_CPU"] = str(download["cpu"])
            if "memory" in download:
                env_vars["BEAM_DOWNLOAD_MEMORY"] = str(download["memory"])
            if "timeout_seconds" in download:
                env_vars["BEAM_DOWNLOAD_TIMEOUT"] = str(download["timeout_seconds"])
            if "max_containers" in download:
                env_vars["BEAM_DOWNLOAD_MAX_CONTAINERS"] = str(download["max_containers"])

            storage = self._clean_dict(beam_functions.get("storage"))
            if "cpu" in storage:
                env_vars["BEAM_STORAGE_CPU"] = str(storage["cpu"])
            if "memory" in storage:
                env_vars["BEAM_STORAGE_MEMORY"] = str(storage["memory"])
            if "timeout_seconds" in storage:
                env_vars["BEAM_STORAGE_TIMEOUT"] = str(storage["timeout_seconds"])
            if "concurrent_requests" in storage:
                env_vars["BEAM_STORAGE_CONCURRENT"] = str(storage["concurrent_requests"])

        return env_vars

    def _build_deploy_state(
        self,
        *,
        provider_id: str,
        provider_type: str,
        status: str,
        attempt_id: str,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        message: Optional[str] = None,
        completed_steps: Optional[List[str]] = None,
        failed_steps: Optional[List[str]] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        state: Dict[str, Any] = {
            "provider_id": provider_id,
            "provider_type": provider_type,
            "status": status,
            "attempt_id": attempt_id,
            "updated_at": self._utcnow_iso(),
        }
        if started_at:
            state["started_at"] = started_at
        if finished_at:
            state["finished_at"] = finished_at
        if message:
            state["message"] = message
        if completed_steps:
            state["completed_steps"] = completed_steps
        if failed_steps:
            state["failed_steps"] = failed_steps
        if steps is not None:
            state["steps"] = steps
        return state

    @staticmethod
    def normalize_reconciliation_status(status: Optional[str]) -> str:
        if status in {"started", "queued"}:
            return "queued"
        if status in {"progress", "running", "reconciling"}:
            return "reconciling"
        if status in {"completed", "failed", "idle"}:
            return status
        return "idle"

    def _read_deploy_state(self, provider: Provider) -> Dict[str, Any]:
        config = provider.config if isinstance(provider.config, dict) else {}
        state = config.get(DEPLOY_STATE_KEY)
        return state if isinstance(state, dict) else {"status": "idle"}

    def _read_reconciliation_state(self, provider: Provider) -> Dict[str, Any]:
        config = provider.config if isinstance(provider.config, dict) else {}
        state = config.get(RECONCILIATION_STATE_KEY)
        return state if isinstance(state, dict) else {"status": "idle"}

    def _persist_deploy_state(self, provider: Provider, state: Dict[str, Any]) -> Dict[str, Any]:
        provider = self._ensure_provider_v2_shape(provider)
        config = self._compose_config(
            base_config=provider.config,
            runtime_config=self._extract_runtime_config(provider.type, provider.container_config, provider.config or {}),
            deploy_config=self._extract_deploy_config(provider.type, provider.config or {}),
            deploy_state=state,
            reconciliation_state=self._read_reconciliation_state(provider),
        )
        updated = self.repo.update(provider.id, {"config": config})
        if updated is None:
            raise NotFoundError("Provider", provider.id)
        return state

    def _persist_reconciliation_state(self, provider: Provider, state: Dict[str, Any]) -> Dict[str, Any]:
        provider = self._ensure_provider_v2_shape(provider)
        config = self._compose_config(
            base_config=provider.config,
            runtime_config=self._extract_runtime_config(provider.type, provider.container_config, provider.config or {}),
            deploy_config=self._extract_deploy_config(provider.type, provider.config or {}),
            deploy_state=self._read_deploy_state(provider),
            reconciliation_state=state,
        )
        updated = self.repo.update(provider.id, {"config": config})
        if updated is None:
            raise NotFoundError("Provider", provider.id)
        return state

    def _is_deploy_in_progress(self, state: Dict[str, Any]) -> bool:
        if state.get("status") != "deploying":
            return False
        started_at_raw = state.get("started_at")
        started_at = self._parse_utc_timestamp(started_at_raw)
        if not started_at:
            return True
        age = datetime.now(timezone.utc) - started_at
        return age <= DEPLOY_IN_PROGRESS_TTL

    def _has_active_deploy_attempt_container(
        self,
        container_manager: Any,
        provider_id: str,
        attempt_id: Optional[str],
    ) -> bool:
        """Best-effort probe for the deploy-attempt container tied to persisted deploy_state."""
        if not attempt_id:
            return False

        containers_client = getattr(getattr(container_manager, "client", None), "containers", None)
        if containers_client is None:
            # Fail open when runtime probing is unavailable.
            return True

        expected_name = f"comfy-provider-deploy-{provider_id}-{str(attempt_id)[:8]}"

        try:
            container = containers_client.get(expected_name)
            try:
                container.reload()
            except Exception:
                pass
            status = getattr(container, "status", None)
            return status not in {"exited", "dead", "removing"}
        except Exception:
            pass

        try:
            matches = containers_client.list(
                all=True,
                filters={
                    "label": [
                        "comfy-provider-deploy=true",
                        f"provider-id={provider_id}",
                        f"deploy-attempt-id={attempt_id}",
                    ]
                },
            )
        except Exception as exc:
            logger.warning(
                "provider_deploy_container_probe_failed",
                provider_id=provider_id,
                attempt_id=attempt_id,
                error=str(exc),
            )
            return True

        for container in matches or []:
            try:
                container.reload()
            except Exception:
                pass
            status = getattr(container, "status", None)
            if status not in {"exited", "dead", "removing"}:
                return True

        return False

    def _mark_deploy_state_failed(self, provider: Provider, state: Dict[str, Any], *, message: str) -> Dict[str, Any]:
        failed_state = self._build_deploy_state(
            provider_id=provider.id,
            provider_type=provider.type,
            status="failed",
            attempt_id=state.get("attempt_id") or "stale-state",
            started_at=state.get("started_at"),
            finished_at=self._utcnow_iso(),
            message=message,
            completed_steps=state.get("completed_steps"),
            failed_steps=state.get("failed_steps"),
            steps=state.get("steps") if isinstance(state.get("steps"), list) else None,
        )
        self._persist_deploy_state(provider, failed_state)
        return failed_state

    @staticmethod
    def _is_reconciliation_in_progress(state: Dict[str, Any]) -> bool:
        return ProviderService.normalize_reconciliation_status(state.get("status")) in RECONCILIATION_IN_PROGRESS_STATUSES

    def _is_reconciliation_state_fresh(self, state: Dict[str, Any]) -> bool:
        if not self._is_reconciliation_in_progress(state):
            return True

        updated_at_raw = state.get("updated_at") or state.get("started_at")
        updated_at = self._parse_utc_timestamp(updated_at_raw)
        if not updated_at:
            return True
        age = datetime.now(timezone.utc) - updated_at
        return age <= RECONCILIATION_IN_PROGRESS_TTL

    @staticmethod
    def _decode_exec_output(exec_result: Any) -> tuple[int, str]:
        output = getattr(exec_result, "output", (None, None))
        stdout_bytes = output[0] if isinstance(output, tuple) and len(output) > 0 else None
        stderr_bytes = output[1] if isinstance(output, tuple) and len(output) > 1 else None
        stdout = stdout_bytes.decode("utf-8") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8") if stderr_bytes else ""
        return getattr(exec_result, "exit_code", -1), f"{stdout}{stderr}"

    async def get_provider_deploy_state(self, provider_id: str) -> Dict[str, Any]:
        provider = await self.get_provider(provider_id)
        state = self._read_deploy_state(provider)

        if self._is_deploy_in_progress(state):
            container_manager = None
            try:
                from services.container_manager import get_container_manager

                container_manager = get_container_manager()
            except Exception:
                container_manager = None

            if container_manager and not self._has_active_deploy_attempt_container(
                container_manager,
                provider.id,
                state.get("attempt_id"),
            ):
                return self._mark_deploy_state_failed(
                    provider,
                    state,
                    message="Previous deployment container disappeared and state was marked failed",
                )
            return state

        if state.get("status") == "deploying":
            return self._mark_deploy_state_failed(
                provider,
                state,
                message="Previous deployment state expired and was marked failed",
            )

        return state

    async def get_provider_reconciliation_state(self, provider_id: str) -> Dict[str, Any]:
        provider = await self.get_provider(provider_id)
        state = self._read_reconciliation_state(provider)
        state["status"] = self.normalize_reconciliation_status(state.get("status"))
        if self._is_reconciliation_state_fresh(state):
            return state

        stale_state = {
            "provider_id": provider.id,
            "status": "failed",
            "message": "Reconciliation state expired and was marked failed",
            "started_at": state.get("started_at"),
            "updated_at": self._utcnow_iso(),
            "finished_at": self._utcnow_iso(),
            "phase": state.get("phase"),
            "stats": state.get("stats") or {},
            "errors": state.get("errors") or [],
            "last_contact_at": state.get("last_contact_at"),
            "warning": "Reconciliation state became stale before the worker reported completion",
        }
        self._persist_reconciliation_state(provider, stale_state)
        return stale_state

    async def start_reconciliation_session(self, provider_id: str) -> Dict[str, Any]:
        provider = await self.get_provider(provider_id)
        current_state = self._read_reconciliation_state(provider)
        if self._is_reconciliation_in_progress(current_state) and self._is_reconciliation_state_fresh(current_state):
            return {
                "accepted": False,
                "state": current_state,
                "message": "Reconciliation already in progress for this provider",
            }

        next_state = {
            "provider_id": provider.id,
            "status": "queued",
            "phase": "queued",
            "message": "Reconciliation trigger requested",
            "stats": {},
            "errors": [],
            "started_at": self._utcnow_iso(),
            "updated_at": self._utcnow_iso(),
        }
        self._persist_reconciliation_state(provider, next_state)
        return {"accepted": True, "state": next_state}

    async def upsert_reconciliation_state(self, provider_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        provider = await self.get_provider(provider_id)
        current_state = self._read_reconciliation_state(provider)

        merged = dict(current_state)
        merged.update({k: v for k, v in updates.items() if v is not None})
        merged["provider_id"] = provider.id
        merged["status"] = self.normalize_reconciliation_status(merged.get("status"))
        merged["updated_at"] = self._utcnow_iso()

        status = merged.get("status", "idle")
        if status in RECONCILIATION_IN_PROGRESS_STATUSES and not merged.get("started_at"):
            merged["started_at"] = self._utcnow_iso()
        if status in RECONCILIATION_TERMINAL_STATUSES:
            merged["finished_at"] = self._utcnow_iso()
        if updates.get("last_contact_at"):
            merged["last_contact_at"] = updates["last_contact_at"]

        self._persist_reconciliation_state(provider, merged)
        return merged

    async def deploy_provider_app(self, provider_id: str, container_manager: Any) -> Dict[str, Any]:
        provider = await self.get_provider(provider_id)

        if not container_manager:
            raise ProviderError(provider_id, "Container manager not initialized")

        current_state = self._read_deploy_state(provider)
        if self._is_deploy_in_progress(current_state):
            if not self._has_active_deploy_attempt_container(
                container_manager,
                provider.id,
                current_state.get("attempt_id"),
            ):
                current_state = self._mark_deploy_state_failed(
                    provider,
                    current_state,
                    message="Previous deployment container disappeared and state was marked failed",
                )
            else:
                return {
                    "status": "already_running",
                    "provider_id": provider.id,
                    "provider_type": provider.type,
                    "message": "Deployment already in progress for this provider",
                    "deploy_state": current_state,
                }

        dedup_key = f"provider-deploy:{provider.id}"
        if is_in_flight(dedup_key):
            return {
                "status": "already_running",
                "provider_id": provider.id,
                "provider_type": provider.type,
                "message": "Deployment already in progress for this provider",
                "deploy_state": current_state,
            }

        async def _run_deploy() -> Dict[str, Any]:
            return await self._execute_provider_deploy(provider, container_manager)

        return await deduplicated(dedup_key, _run_deploy)

    async def _execute_provider_deploy(self, provider: Provider, container_manager: Any) -> Dict[str, Any]:
        attempt_id = str(uuid4())
        started_at = self._utcnow_iso()
        provider = self._ensure_provider_v2_shape(provider)
        deploy_config = self._extract_deploy_config(provider.type, provider.config or {})
        deploy_mode = deploy_config.get("deploy_mode", self._default_deploy_mode(provider.type))

        if deploy_mode != "managed":
            raise ValidationError(f"Managed deploy is disabled for provider '{provider.id}'")

        previous_state = self._read_deploy_state(provider)
        resumed_steps: List[str] = []
        if provider.type == "beam" and previous_state.get("status") == "failed":
            resumed_steps = [
                step
                for step in (previous_state.get("completed_steps") or [])
                if step in {"comfy_gpu", "comfy_storage", "comfy_download"}
            ]

        deploying_state = self._build_deploy_state(
            provider_id=provider.id,
            provider_type=provider.type,
            status="deploying",
            attempt_id=attempt_id,
            started_at=started_at,
            message="Deployment started",
            completed_steps=resumed_steps,
            steps=[],
        )
        self._persist_deploy_state(provider, deploying_state)

        orchestrator = ProviderDeployOrchestrator(container_manager)
        deploy_container = None
        try:
            deploy_container = orchestrator.start_attempt_container(
                provider_id=provider.id,
                provider_type=provider.type,
                attempt_id=attempt_id,
                env_vars=self.build_provider_environment(provider),
            )
            deployments = deploy_config.get("targets") or self._default_deploy_targets(provider.type)
            completed_steps = set(resumed_steps)
            results: List[Dict[str, Any]] = []

            for step in deployments:
                name = step.get("name") or "deploy-step"
                command = self._normalize_deploy_step_command(provider.type, step.get("command") or [])
                if not command:
                    continue
                if name in completed_steps:
                    results.append(
                        {
                            "name": name,
                            "success": True,
                            "exit_code": 0,
                            "output": "Skipped; step already completed in previous failed attempt",
                            "skipped": True,
                        }
                    )
                    continue

                try:
                    exec_result = await orchestrator.run_step(deploy_container, command)
                    exit_code, output = self._decode_exec_output(exec_result)
                except ProviderDeployStepTimeoutError as exc:
                    exit_code, output = -1, str(exc)
                except ProviderDeployStepExecutionError as exc:
                    exit_code, output = -1, str(exc)
                success = exit_code == 0
                if success:
                    completed_steps.add(name)
                results.append(
                    {
                        "name": name,
                        "success": success,
                        "exit_code": exit_code,
                        "output": output,
                        "entrypoint": step.get("entrypoint"),
                    }
                )
                self._persist_deploy_state(
                    provider,
                    self._build_deploy_state(
                        provider_id=provider.id,
                        provider_type=provider.type,
                        status="deploying",
                        attempt_id=attempt_id,
                        started_at=started_at,
                        message=f"Deployment running: {name}",
                        completed_steps=sorted(completed_steps),
                        failed_steps=[entry["name"] for entry in results if not entry["success"]],
                        steps=list(results),
                    ),
                )
                if not success:
                    break

            failed_steps = [entry["name"] for entry in results if not entry["success"]]
            if failed_steps:
                failed_state = self._build_deploy_state(
                    provider_id=provider.id,
                    provider_type=provider.type,
                    status="failed",
                    attempt_id=attempt_id,
                    started_at=started_at,
                    finished_at=self._utcnow_iso(),
                    message=f"{provider.type.capitalize()} deploy failed for: {', '.join(failed_steps)}",
                    completed_steps=sorted(completed_steps),
                    failed_steps=failed_steps,
                    steps=results,
                )
                self._persist_deploy_state(provider, failed_state)
                raise ProviderError(
                    provider.id,
                    f"{provider.type.capitalize()} deploy failed for: {', '.join(failed_steps)}. Check deploy details for logs.",
                )

            success_state = self._build_deploy_state(
                provider_id=provider.id,
                provider_type=provider.type,
                status="succeeded",
                attempt_id=attempt_id,
                started_at=started_at,
                finished_at=self._utcnow_iso(),
                message=f"{provider.type.capitalize()} deploy completed",
                completed_steps=sorted(completed_steps),
                steps=results,
            )
            self._persist_deploy_state(provider, success_state)
            return {
                "status": "success",
                "provider_type": provider.type,
                "message": f"{provider.type.capitalize()} app deployed for {provider.id}",
                "deployments": results,
                "deploy_state": success_state,
            }
        except Exception:
            current_state = self._read_deploy_state(provider)
            if current_state.get("status") == "deploying":
                failed_state = self._build_deploy_state(
                    provider_id=provider.id,
                    provider_type=provider.type,
                    status="failed",
                    attempt_id=current_state.get("attempt_id") or attempt_id,
                    started_at=current_state.get("started_at") or started_at,
                    finished_at=self._utcnow_iso(),
                    message=current_state.get("message") or "Deployment failed",
                    completed_steps=current_state.get("completed_steps"),
                    failed_steps=current_state.get("failed_steps"),
                )
                self._persist_deploy_state(provider, failed_state)
            raise
        finally:
            orchestrator.cleanup_container(deploy_container)
    
    async def create_provider(self, provider_data: Dict[str, Any]) -> Provider:
        """
        Create a new provider.
        
        Args:
            provider_data: Provider configuration
            
        Returns:
            Created provider
        """
        # Validate required fields
        if "id" not in provider_data:
            raise ValidationError("Provider ID is required", field="id")
        if "type" not in provider_data:
            raise ValidationError("Provider type is required", field="type")
        
        # Check if already exists
        if self.repo.exists(provider_data["id"]):
            raise ValidationError(f"Provider '{provider_data['id']}' already exists", field="id")
        
        normalized = self._normalize_provider_for_storage(provider_data)
        provider = self.repo.create(normalized)
        
        logger.info("provider_created", provider_id=provider.id, type=provider.type)
        await emit_provider_event(
            EventType.PROVIDER_STATUS, 
            provider.id, 
            {"status": "created", "enabled": provider.enabled}
        )
        
        return self._ensure_provider_v2_shape(provider)
    
    async def get_provider(self, provider_id: str) -> Provider:
        """Get a provider by ID."""
        provider = self.repo.get(provider_id)
        if not provider:
            logger.warning("provider_not_found", provider_id=provider_id)
            raise NotFoundError("Provider", provider_id)
        return self._ensure_provider_v2_shape(provider)
    
    async def list_providers(self) -> List[Dict[str, Any]]:
        """List all providers with their info."""
        providers = self.repo.get_all()
        return [self._provider_to_dict(self._ensure_provider_v2_shape(p)) for p in providers]
    
    def get_enabled_providers(self) -> List[Provider]:
        """Get all enabled providers."""
        return self.repo.get_enabled()
    
    async def update_provider(self, provider_id: str, updates: Dict[str, Any]) -> Provider:
        """
        Update a provider.
        
        Args:
            provider_id: Provider ID
            updates: Fields to update
            
        Returns:
            Updated provider
        """
        existing = await self.get_provider(provider_id)
        normalized = self._normalize_provider_for_storage(updates, existing=existing)
        provider = self.repo.update(
            provider_id,
            {
                "type": normalized["type"],
                "enabled": normalized["enabled"],
                "priority": normalized["priority"],
                "credentials": normalized["credentials"],
                "container_config": normalized["container_config"],
                "config": normalized["config"],
            },
        )
        if not provider:
            logger.warning("provider_update_not_found", provider_id=provider_id)
            raise NotFoundError("Provider", provider_id)
        
        logger.info("provider_updated", provider_id=provider_id)
        
        await emit_provider_event(
            EventType.PROVIDER_STATUS,
            provider_id,
            {"status": "updated", "enabled": provider.enabled}
        )
        
        return self._ensure_provider_v2_shape(provider)
    
    async def delete_provider(self, provider_id: str) -> bool:
        """Delete a provider and cascade delete its status entries."""
        from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
        from services.load_balancer import LoadBalancer
        
        # First, cascade delete all ProviderVersionStatus entries for this provider
        model_repo = ModelRepositoryV2(self.session)
        deleted_count = model_repo.delete_all_statuses_for_provider(provider_id)
        if deleted_count > 0:
            logger.info("provider_cascade_delete", provider_id=provider_id, statuses_deleted=deleted_count)
        
        # Then delete the provider itself
        success = self.repo.delete(provider_id)
        if not success:
            logger.warning("provider_delete_not_found", provider_id=provider_id)
            raise NotFoundError("Provider", provider_id)

        # Remove stale load balancer runtime references for deleted providers.
        lb_runtime = LoadBalancer.default_runtime_state()
        with lb_runtime.lock:
            lb_runtime.provider_failures.pop(provider_id, None)
            lb_runtime.provider_job_counts.pop(provider_id, None)
        LoadBalancer.save_state_to_db(self.session, runtime_state=lb_runtime)
        
        logger.info("provider_deleted", provider_id=provider_id, statuses_cleaned=deleted_count)
        
        await emit_provider_event(
            EventType.PROVIDER_STATUS,
            provider_id,
            {"status": "deleted", "statuses_cleaned": deleted_count}
        )
        
        return True
    
    def get_load_balancing_config(self) -> LoadBalancingConfig:
        """Get load balancing configuration."""
        return self.lb_repo.get()
    
    async def update_load_balancing_config(self, **updates) -> LoadBalancingConfig:
        """Update load balancing configuration."""
        return self.lb_repo.update(**updates)
    
    def _provider_to_dict(self, provider: Provider) -> Dict[str, Any]:
        """Convert provider to dictionary for API responses."""
        provider = self._ensure_provider_v2_shape(provider)
        runtime = resolve_provider_runtime(provider)
        deploy_state = self._read_deploy_state(provider)
        reconciliation_state = self._read_reconciliation_state(provider)
        runtime_config = self._extract_runtime_config(provider.type, provider.container_config, provider.config or {})
        deploy_config = self._extract_deploy_config(provider.type, provider.config or {})
        capabilities, capability_reasons = self._build_capabilities(
            provider=provider,
            runtime=runtime,
            runtime_config=runtime_config,
            deploy_config=deploy_config,
        )
        return {
            "id": provider.id,
            "type": provider.type,
            "enabled": provider.enabled,
            "priority": provider.priority,
            "runtime_config": runtime_config,
            "deploy_config": deploy_config,
            "deploy_state": deploy_state,
            "reconciliation_state": reconciliation_state,
            "runtime_state": {
                "mode": runtime.mode,
                "connected": runtime.connected,
                "status": runtime.status,
                "healthy": runtime.healthy,
                "supports_setup": runtime.supports_setup,
                "supports_reconciliation": runtime.supports_reconciliation,
                "worker_url": runtime.worker_url,
                "container_name": runtime.container_name,
            },
            "capabilities": capabilities,
            "capability_reasons": capability_reasons,
            "credential_summary": self._summarize_credentials(provider.type, self._clean_dict(provider.credentials), deploy_config),
        }
    
    def get_model_cache(self) -> Dict[str, Any]:
        """Get all model metadata cache for reconciliation."""
        from services.model_service_v2 import ModelServiceV2
        model_service = ModelServiceV2(self.session)
        return model_service.get_full_cache()
    
    def get_model_cache_for_directory(self, directory: str) -> List[Dict[str, Any]]:
        """Get model cache for a specific directory."""
        from services.model_service_v2 import ModelServiceV2
        model_service = ModelServiceV2(self.session)
        # get_full_cache returns {directory: [models]}
        cache = model_service.get_full_cache()
        return cache.get(directory, [])
    
    def get_load_balancer_stats(self) -> Dict[str, Any]:
        """Get load balancer statistics."""
        from services.load_balancer_factory import create_load_balancer

        config = self.get_load_balancing_config()
        load_balancer = create_load_balancer(
            self.session,
            strategy=config.strategy if config else None,
        )
        return load_balancer.get_stats()
