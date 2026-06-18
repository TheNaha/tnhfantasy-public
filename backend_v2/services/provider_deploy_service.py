import asyncio
from uuid import uuid4
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from core.entities import Provider
from infrastructure.repositories import ProviderRepository
from core.exceptions import NotFoundError, ValidationError, ProviderError
from services.provider_utils import (
    ensure_provider_v2_shape,
    read_deploy_state,
    extract_runtime_config,
    extract_deploy_config,
    compose_config,
    utcnow_iso,
    parse_utc_timestamp,
    DEPLOY_IN_PROGRESS_TTL,
    read_reconciliation_state,
    default_deploy_mode,
    default_deploy_targets,
    normalize_deploy_step_command
)
from services.provider_env_builder import build_provider_environment
from services.provider_deploy_orchestrator import (
    ProviderDeployOrchestrator,
    ProviderDeployStepExecutionError,
    ProviderDeployStepTimeoutError,
)
from infrastructure.request_dedup import deduplicated, is_in_flight
from infrastructure.logging import provider_logger

logger = provider_logger()

class ProviderDeployService:
    def __init__(self, repo: ProviderRepository):
        self.repo = repo

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
            "updated_at": utcnow_iso(),
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

    def _persist_deploy_state(self, provider: Provider, state: Dict[str, Any]) -> Dict[str, Any]:
        provider = ensure_provider_v2_shape(provider)
        config = compose_config(
            base_config=provider.config,
            runtime_config=extract_runtime_config(provider.type, provider.container_config, provider.config or {}),
            deploy_config=extract_deploy_config(provider.type, provider.config or {}),
            deploy_state=state,
            reconciliation_state=read_reconciliation_state(provider),
        )
        updated = self.repo.update(provider.id, {"config": config})
        if updated is None:
            raise NotFoundError("Provider", provider.id)
        return state

    def _is_deploy_in_progress(self, state: Dict[str, Any]) -> bool:
        if state.get("status") != "deploying":
            return False
        started_at_raw = state.get("started_at")
        started_at = parse_utc_timestamp(started_at_raw)
        if not started_at:
            return True
        age = datetime.now(timezone.utc) - started_at
        return age.total_seconds() <= DEPLOY_IN_PROGRESS_TTL

    def _has_active_deploy_attempt_container(
        self,
        container_manager: Any,
        provider_id: str,
        attempt_id: Optional[str],
    ) -> bool:
        if not attempt_id:
            return False

        containers_client = getattr(getattr(container_manager, "client", None), "containers", None)
        if containers_client is None:
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
            finished_at=utcnow_iso(),
            message=message,
            completed_steps=state.get("completed_steps"),
            failed_steps=state.get("failed_steps"),
            steps=state.get("steps") if isinstance(state.get("steps"), list) else None,
        )
        self._persist_deploy_state(provider, failed_state)
        return failed_state

    @staticmethod
    def _decode_exec_output(exec_result: Any) -> tuple[int, str]:
        output = getattr(exec_result, "output", (None, None))
        stdout_bytes = output[0] if isinstance(output, tuple) and len(output) > 0 else None
        stderr_bytes = output[1] if isinstance(output, tuple) and len(output) > 1 else None
        stdout = stdout_bytes.decode("utf-8") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8") if stderr_bytes else ""
        return getattr(exec_result, "exit_code", -1), f"{stdout}{stderr}"

    async def get_provider_deploy_state(self, provider: Provider) -> Dict[str, Any]:
        state = read_deploy_state(provider)

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

    async def deploy_provider_app(self, provider: Provider, container_manager: Any) -> Dict[str, Any]:
        if not container_manager:
            raise ProviderError(provider.id, "Container manager not initialized")

        current_state = read_deploy_state(provider)
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
        started_at = utcnow_iso()
        provider = ensure_provider_v2_shape(provider)
        deploy_config = extract_deploy_config(provider.type, provider.config or {})
        deploy_mode = deploy_config.get("deploy_mode", default_deploy_mode(provider.type))

        if deploy_mode != "managed":
            raise ValidationError(f"Managed deploy is disabled for provider '{provider.id}'")

        previous_state = read_deploy_state(provider)
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
            deploy_env_vars = build_provider_environment(provider)
            if provider.type == "beam":
                deploy_env_vars.setdefault("CI", "1")

            deploy_container = orchestrator.start_attempt_container(
                provider_id=provider.id,
                provider_type=provider.type,
                attempt_id=attempt_id,
                env_vars=deploy_env_vars,
            )
            deployments = deploy_config.get("targets") or default_deploy_targets(provider.type)
            completed_steps = set(resumed_steps)
            results: List[Dict[str, Any]] = []

            for step in deployments:
                name = step.get("name") or "deploy-step"
                command = normalize_deploy_step_command(provider.type, step.get("command") or [])
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
                    finished_at=utcnow_iso(),
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
                finished_at=utcnow_iso(),
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
            current_state = read_deploy_state(provider)
            if current_state.get("status") == "deploying":
                failed_state = self._build_deploy_state(
                    provider_id=provider.id,
                    provider_type=provider.type,
                    status="failed",
                    attempt_id=current_state.get("attempt_id") or attempt_id,
                    started_at=current_state.get("started_at") or started_at,
                    finished_at=utcnow_iso(),
                    message=current_state.get("message") or "Deployment failed",
                    completed_steps=current_state.get("completed_steps"),
                    failed_steps=current_state.get("failed_steps"),
                )
                self._persist_deploy_state(provider, failed_state)
            raise
        finally:
            orchestrator.cleanup_container(deploy_container)
