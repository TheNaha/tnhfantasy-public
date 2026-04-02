# Provider Service - Business logic for provider management
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
from api.provider_runtime import resolve_provider_runtime

logger = provider_logger()


DEPLOY_STATE_KEY = "deploy_state"
DEPLOY_IN_PROGRESS_TTL = timedelta(minutes=30)
RECONCILIATION_STATE_KEY = "reconciliation_state"
RECONCILIATION_IN_PROGRESS_TTL = timedelta(minutes=180)
RECONCILIATION_IN_PROGRESS_STATUSES = {"started", "reconciling", "progress", "running"}
RECONCILIATION_TERMINAL_STATUSES = {"completed", "failed", "idle"}


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
        return state

    def _read_deploy_state(self, provider: Provider) -> Dict[str, Any]:
        config = provider.config if isinstance(provider.config, dict) else {}
        state = config.get(DEPLOY_STATE_KEY)
        return state if isinstance(state, dict) else {"status": "idle"}

    def _read_reconciliation_state(self, provider: Provider) -> Dict[str, Any]:
        config = provider.config if isinstance(provider.config, dict) else {}
        state = config.get(RECONCILIATION_STATE_KEY)
        return state if isinstance(state, dict) else {"status": "idle"}

    def _persist_deploy_state(self, provider: Provider, state: Dict[str, Any]) -> Dict[str, Any]:
        config = dict(provider.config or {})
        config[DEPLOY_STATE_KEY] = state
        updated = self.repo.update(provider.id, {"config": config})
        if updated is None:
            raise NotFoundError("Provider", provider.id)
        return state

    def _persist_reconciliation_state(self, provider: Provider, state: Dict[str, Any]) -> Dict[str, Any]:
        config = dict(provider.config or {})
        config[RECONCILIATION_STATE_KEY] = state
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

    @staticmethod
    def _is_reconciliation_in_progress(state: Dict[str, Any]) -> bool:
        return state.get("status") in RECONCILIATION_IN_PROGRESS_STATUSES

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

    @staticmethod
    def _resolve_running_container(provider_id: str, container_manager: Any):
        container = container_manager.running_containers.get(provider_id)
        if container is not None:
            return container

        container_name = f"comfy-provider-{provider_id}"
        try:
            container = container_manager.client.containers.get(container_name)
        except Exception as exc:
            raise ValidationError(
                f"Container for provider '{provider_id}' not found. Start the container first."
            ) from exc

        if getattr(container, "status", None) != "running":
            raise ValidationError(
                f"Container for provider '{provider_id}' is not running. Start the container first."
            )
        return container

    async def get_provider_deploy_state(self, provider_id: str) -> Dict[str, Any]:
        provider = await self.get_provider(provider_id)
        state = self._read_deploy_state(provider)

        if self._is_deploy_in_progress(state):
            return state

        if state.get("status") == "deploying":
            stale_state = self._build_deploy_state(
                provider_id=provider.id,
                provider_type=provider.type,
                status="failed",
                attempt_id=state.get("attempt_id") or "stale-state",
                started_at=state.get("started_at"),
                finished_at=self._utcnow_iso(),
                message="Previous deployment state expired and was marked failed",
                completed_steps=state.get("completed_steps"),
                failed_steps=state.get("failed_steps"),
            )
            self._persist_deploy_state(provider, stale_state)
            return stale_state

        return state

    async def get_provider_reconciliation_state(self, provider_id: str) -> Dict[str, Any]:
        provider = await self.get_provider(provider_id)
        state = self._read_reconciliation_state(provider)
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
            "status": "started",
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
        merged["updated_at"] = self._utcnow_iso()

        status = merged.get("status", "idle")
        if status in RECONCILIATION_IN_PROGRESS_STATUSES and not merged.get("started_at"):
            merged["started_at"] = self._utcnow_iso()
        if status in RECONCILIATION_TERMINAL_STATUSES:
            merged["finished_at"] = self._utcnow_iso()

        self._persist_reconciliation_state(provider, merged)
        return merged

    async def deploy_provider_app(self, provider_id: str, container_manager: Any) -> Dict[str, Any]:
        provider = await self.get_provider(provider_id)

        if not container_manager:
            raise ProviderError(provider_id, "Container manager not initialized")

        current_state = self._read_deploy_state(provider)
        if self._is_deploy_in_progress(current_state):
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

        container = self._resolve_running_container(provider.id, container_manager)

        async def _run_deploy() -> Dict[str, Any]:
            return self._execute_provider_deploy(provider, container)

        return await deduplicated(dedup_key, _run_deploy)

    def _execute_provider_deploy(self, provider: Provider, container: Any) -> Dict[str, Any]:
        attempt_id = str(uuid4())
        started_at = self._utcnow_iso()

        previous_state = self._read_deploy_state(provider)
        resumed_steps: List[str] = []
        if provider.type == "beam" and previous_state.get("status") == "failed":
            resumed_steps = [
                step
                for step in (previous_state.get("completed_steps") or [])
                if step in {"comfy_gpu", "comfy_storage"}
            ]

        deploying_state = self._build_deploy_state(
            provider_id=provider.id,
            provider_type=provider.type,
            status="deploying",
            attempt_id=attempt_id,
            started_at=started_at,
            message="Deployment started",
            completed_steps=resumed_steps,
        )
        self._persist_deploy_state(provider, deploying_state)

        try:
            if provider.type == "modal":
                logger.info("deploy_modal_start", provider_id=provider.id, attempt_id=attempt_id)
                exec_result = container.exec_run(
                    cmd=["modal", "deploy", "/app/modal_app.py"],
                    stream=False,
                    demux=True,
                )
                exit_code, output = self._decode_exec_output(exec_result)
                logger.info("deploy_modal_output", provider_id=provider.id, attempt_id=attempt_id, output=output)

                if exit_code != 0:
                    failed_state = self._build_deploy_state(
                        provider_id=provider.id,
                        provider_type=provider.type,
                        status="failed",
                        attempt_id=attempt_id,
                        started_at=started_at,
                        finished_at=self._utcnow_iso(),
                        message=f"Modal deploy failed (exit code {exit_code})",
                    )
                    self._persist_deploy_state(provider, failed_state)
                    raise ProviderError(provider.id, f"Modal deploy failed (exit code {exit_code}): {output}")

                success_state = self._build_deploy_state(
                    provider_id=provider.id,
                    provider_type=provider.type,
                    status="succeeded",
                    attempt_id=attempt_id,
                    started_at=started_at,
                    finished_at=self._utcnow_iso(),
                    message="Modal deploy completed",
                )
                self._persist_deploy_state(provider, success_state)
                return {
                    "status": "success",
                    "provider_type": "modal",
                    "message": f"Modal app deployed for {provider.id}",
                    "output": output,
                    "deploy_state": success_state,
                }

            if provider.type == "beam":
                logger.info("deploy_beam_start", provider_id=provider.id, attempt_id=attempt_id)
                deployments = [
                    ("comfy_gpu", ["beam", "deploy", "/app/beam_app.py:comfy_gpu"]),
                    ("comfy_storage", ["beam", "deploy", "/app/beam_app.py:comfy_storage"]),
                ]
                completed_steps = set(resumed_steps)
                results: List[Dict[str, Any]] = []

                for name, cmd in deployments:
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

                    logger.info("deploy_beam_running", provider_id=provider.id, attempt_id=attempt_id, command=" ".join(cmd))
                    exec_result = container.exec_run(cmd=cmd, stream=False, demux=True)
                    exit_code, output = self._decode_exec_output(exec_result)
                    logger.info(
                        "deploy_beam_output",
                        provider_id=provider.id,
                        attempt_id=attempt_id,
                        name=name,
                        output=output,
                    )

                    success = exit_code == 0
                    if success:
                        completed_steps.add(name)
                    results.append(
                        {
                            "name": name,
                            "success": success,
                            "exit_code": exit_code,
                            "output": output,
                        }
                    )

                failed_steps = [entry["name"] for entry in results if not entry["success"]]
                if failed_steps:
                    failed_state = self._build_deploy_state(
                        provider_id=provider.id,
                        provider_type=provider.type,
                        status="failed",
                        attempt_id=attempt_id,
                        started_at=started_at,
                        finished_at=self._utcnow_iso(),
                        message=f"Beam deploy failed for: {', '.join(failed_steps)}",
                        completed_steps=sorted(completed_steps),
                        failed_steps=failed_steps,
                    )
                    self._persist_deploy_state(provider, failed_state)
                    raise ProviderError(
                        provider.id,
                        f"Beam deploy failed for: {', '.join(failed_steps)}. Check logs for details.",
                    )

                success_state = self._build_deploy_state(
                    provider_id=provider.id,
                    provider_type=provider.type,
                    status="succeeded",
                    attempt_id=attempt_id,
                    started_at=started_at,
                    finished_at=self._utcnow_iso(),
                    message="Beam deploy completed",
                    completed_steps=sorted(completed_steps),
                )
                self._persist_deploy_state(provider, success_state)
                return {
                    "status": "success",
                    "provider_type": "beam",
                    "message": f"Beam apps deployed for {provider.id}",
                    "deployments": results,
                    "deploy_state": success_state,
                }

            raise ValidationError(f"Deployment not supported for provider type: {provider.type}")
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
        
        provider = self.repo.create(provider_data)
        
        logger.info("provider_created", provider_id=provider.id, type=provider.type)
        await emit_provider_event(
            EventType.PROVIDER_STATUS, 
            provider.id, 
            {"status": "created", "enabled": provider.enabled}
        )
        
        return provider
    
    async def get_provider(self, provider_id: str) -> Provider:
        """Get a provider by ID."""
        provider = self.repo.get(provider_id)
        if not provider:
            logger.warning("provider_not_found", provider_id=provider_id)
            raise NotFoundError("Provider", provider_id)
        return provider
    
    async def list_providers(self) -> List[Dict[str, Any]]:
        """List all providers with their info."""
        providers = self.repo.get_all()
        return [self._provider_to_dict(p) for p in providers]
    
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
        provider = self.repo.update(provider_id, updates)
        if not provider:
            logger.warning("provider_update_not_found", provider_id=provider_id)
            raise NotFoundError("Provider", provider_id)
        
        logger.info("provider_updated", provider_id=provider_id)
        
        await emit_provider_event(
            EventType.PROVIDER_STATUS,
            provider_id,
            {"status": "updated", "enabled": provider.enabled}
        )
        
        return provider
    
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
        runtime = resolve_provider_runtime(provider)
        deploy_state = self._read_deploy_state(provider)
        reconciliation_state = self._read_reconciliation_state(provider)
        return {
            "id": provider.id,
            "type": provider.type,
            "enabled": provider.enabled,
            "priority": provider.priority,
            "credentials": provider.credentials,
            "config": provider.config,
            "deploy_state": deploy_state,
            "reconciliation_state": reconciliation_state,
            "container_config": provider.container_config,
            "runtime": {
                "mode": runtime.mode,
                "connected": runtime.connected,
                "supports_setup": runtime.supports_setup,
                "supports_reconciliation": runtime.supports_reconciliation,
            },
            "capabilities": {
                "container": runtime.mode == "container_http",
                "start_container": provider.container_config is not None,
                "stop_container": provider.container_config is not None,
                "restart_container": provider.container_config is not None,
                "view_logs": provider.container_config is not None,
                "deploy": provider.type in {"modal", "beam"},
                "setup": runtime.supports_setup,
                "reconcile": runtime.supports_reconciliation,
                "reset_status": True,
            },
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
