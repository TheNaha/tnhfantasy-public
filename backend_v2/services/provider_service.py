# Provider Service - Business logic for provider management
from copy import deepcopy
from typing import Any

from sqlmodel import Session

from core.entities import LoadBalancingConfig, Provider
from core.events import EventType, emit_provider_event
from core.exceptions import NotFoundError, ValidationError
from infrastructure.logging import provider_logger
from infrastructure.providers.provider_registry import ProviderRegistry
from infrastructure.repositories import LoadBalancingRepository, ProviderRepository
from services.provider_deploy_service import ProviderDeployService
from services.provider_env_builder import build_provider_environment
from services.provider_reconciliation_service import ProviderReconciliationService
from services.provider_runtime import resolve_provider_runtime
from services.provider_utils import (
    _get_supported_managed_deploy_types,
    clean_dict,
    compose_config,
    default_deploy_mode,
    extract_deploy_config,
    extract_runtime_config,
    mask_secret,
    normalize_reconciliation_status,
    read_deploy_state,
    read_reconciliation_state,
)

logger = provider_logger()

# Provider types that are always LLM workers regardless of id/name.
LLM_PROVIDER_TYPES = {"openai_compat", "openai", "anthropic", "google", "gemini", "ollama"}


def _infer_worker_type(provider_id: str, provider_type: str, explicit: str | None = None) -> str:
    """Infer worker_type, preferring explicit value, then known LLM provider types, then id/type prefixes."""
    if explicit and explicit != "image":
        return explicit
    if str(provider_type).lower() in LLM_PROVIDER_TYPES:
        return "llm"
    if str(provider_id).lower().startswith("llm") or str(provider_type).lower().startswith("llm"):
        return "llm"
    return "image"


class ProviderService:
    """
    Handles provider lifecycle and configuration.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.repo = ProviderRepository(session)
        self.lb_repo = LoadBalancingRepository(session)
        self.deploy_service = ProviderDeployService(self.repo)
        self.reconciliation_service = ProviderReconciliationService(self.repo)

    def _normalize_provider_for_storage(self, provider_data: dict[str, Any], existing: Provider | None = None) -> dict[str, Any]:
        payload = deepcopy(provider_data)
        provider_id = payload.get("id") or getattr(existing, "id", "")
        provider_type = payload.get("type") or getattr(existing, "type", "modal")
        
        worker_type = payload.get("worker_type")
        if not worker_type:
            worker_type = getattr(existing, "worker_type", None)

        worker_type = _infer_worker_type(provider_id, provider_type, worker_type)

        payload["worker_type"] = worker_type
        existing_config = clean_dict(getattr(existing, "config", None))
        merged_config = clean_dict(existing_config)
        merged_config.update(clean_dict(payload.get("config")))

        raw_runtime_config = payload.get("runtime_config")
        if raw_runtime_config is None and "container_config" in payload:
            raw_runtime_config = payload.get("container_config")
        if raw_runtime_config is None:
            raw_runtime_config = extract_runtime_config(
                provider_type,
                getattr(existing, "container_config", None),
                merged_config,
            )
        else:
            raw_runtime_config = clean_dict(raw_runtime_config)

        raw_deploy_config = payload.get("deploy_config")
        if raw_deploy_config is None:
            raw_deploy_config = extract_deploy_config(provider_type, merged_config)
        else:
            raw_deploy_config = clean_dict(raw_deploy_config)

        deploy_config = extract_deploy_config(
            provider_type,
            {
                **merged_config,
                "deploy_config": raw_deploy_config,
            },
        )

        runtime_config = raw_runtime_config or None
        config = compose_config(
            base_config=merged_config,
            runtime_config=runtime_config,
            deploy_config=deploy_config,
            deploy_state=read_deploy_state(existing) if existing else None,
            reconciliation_state=read_reconciliation_state(existing) if existing else None,
        )

        return {
            "id": payload.get("id") or getattr(existing, "id", None),
            "type": provider_type,
            "worker_type": payload.get("worker_type"),
            "enabled": payload.get("enabled", getattr(existing, "enabled", True)),
            "priority": payload.get("priority", getattr(existing, "priority", 1)),
            "credentials": clean_dict(payload.get("credentials", getattr(existing, "credentials", {}))),
            "container_config": runtime_config,
            "config": config,
        }

    def _summarize_credentials(self, provider_type: str, credentials: dict[str, Any], deploy_config: dict[str, Any], runtime: Any) -> dict[str, Any]:
        validation = ProviderRegistry.validate_provider(provider_type, credentials, deploy_config)
        configured_fields = sorted(
            key for key, value in credentials.items()
            if value not in (None, "", [], {})
        )
        account_label = (
            credentials.get("username")
            or credentials.get("workspace_id")
            or mask_secret(credentials.get("api_key"))
            or mask_secret(credentials.get("token_id"))
        )
        is_discovery = runtime and getattr(runtime, "mode", None) == "discovery"
        missing_credentials = [] if is_discovery else validation.get("credentials", [])
        missing_config = [] if is_discovery else validation.get("config", [])
        return {
            "configured_fields": configured_fields,
            "missing_required_credentials": missing_credentials,
            "missing_required_config": missing_config,
            "account_label": account_label,
            "has_credentials": bool(configured_fields) or is_discovery,
            "ready": not missing_credentials and not missing_config,
        }

    def _build_capabilities(
        self,
        *,
        provider: Provider,
        runtime: Any,
        runtime_config: dict[str, Any] | None,
        deploy_config: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str | None]]:
        deploy_mode = deploy_config.get("deploy_mode", default_deploy_mode(provider.type))
        managed_deploy = deploy_mode == "managed" and provider.type in _get_supported_managed_deploy_types()
        runtime_available = runtime_config is not None

        capabilities = {
            "container": runtime_available,
            "start_container": False,
            "stop_container": False,
            "restart_container": False,
            "view_logs": False,
            "deploy": runtime_available,
            "setup": provider.type == "modal" and runtime_available,
            "reconcile": runtime.supports_reconciliation,
            "reset_status": True,
            "manual_deploy": deploy_mode == "manual",
            "managed_deploy": False,
            "runtime_only": runtime_available,
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

    # DELEGATED METHODS
    
    def build_provider_environment(self, provider: Provider) -> dict[str, str]:
        return build_provider_environment(provider)

    async def get_provider_deploy_state(self, provider_id: str) -> dict[str, Any]:
        provider = await self.get_provider(provider_id)
        return await self.deploy_service.get_provider_deploy_state(provider)

    async def deploy_provider_app(self, provider_id: str, container_manager: Any) -> dict[str, Any]:
        provider = await self.get_provider(provider_id)
        return await self.deploy_service.deploy_provider_app(provider, container_manager)

    async def get_provider_reconciliation_state(self, provider_id: str) -> dict[str, Any]:
        provider = await self.get_provider(provider_id)
        return await self.reconciliation_service.get_provider_reconciliation_state(provider)

    async def start_reconciliation_session(self, provider_id: str, force: bool = False) -> dict[str, Any]:
        provider = await self.get_provider(provider_id)
        return await self.reconciliation_service.start_reconciliation_session(provider, force=force)

    async def upsert_reconciliation_state(self, provider_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        provider = await self.get_provider(provider_id)
        return await self.reconciliation_service.upsert_reconciliation_state(provider, updates)
    
    @staticmethod
    def normalize_reconciliation_status(status: str | None) -> str:
        return normalize_reconciliation_status(status)
    
    @staticmethod
    def _utcnow_iso() -> str:
        from services.provider_utils import utcnow_iso
        return utcnow_iso()

    # CRUD METHODS
    
    async def create_provider(self, provider_data: dict[str, Any]) -> Provider:
        if "id" not in provider_data:
            raise ValidationError("Provider ID is required", field="id")
        if "type" not in provider_data:
            raise ValidationError("Provider type is required", field="type")
        
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
        
        return provider
    
    async def get_provider(self, provider_id: str) -> Provider:
        provider = self.repo.get(provider_id)
        if not provider:
            logger.warning("provider_not_found", provider_id=provider_id)
            raise NotFoundError("Provider", provider_id)
        return provider
    
    async def list_providers(self) -> list[dict[str, Any]]:
        providers = self.repo.get_all()
        result = [self._provider_to_dict(p) for p in providers]
        # Sort: discovered (live) providers first, then by priority
        result.sort(key=lambda d: (
            0 if d.get("runtime_state", {}).get("discovered") else 1,
            d.get("runtime_state", {}).get("last_seen_at", "") or "",
            d.get("priority", 1),
        ))
        return result
    
    def get_enabled_providers(self) -> list[Provider]:
        return self.repo.get_enabled()
    
    async def update_provider(self, provider_id: str, updates: dict[str, Any]) -> Provider:
        existing = await self.get_provider(provider_id)
        normalized = self._normalize_provider_for_storage(updates, existing=existing)
        provider = self.repo.update(
            provider_id,
            {
                "type": normalized["type"],
                "worker_type": normalized["worker_type"],
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
        
        return provider
    
    async def delete_provider(self, provider_id: str) -> bool:
        from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
        from services.load_balancer import LoadBalancer
        
        model_repo = ModelRepositoryV2(self.session)
        deleted_count = model_repo.delete_all_statuses_for_provider(provider_id)
        if deleted_count > 0:
            logger.info("provider_cascade_delete", provider_id=provider_id, statuses_deleted=deleted_count)
        
        success = self.repo.delete(provider_id)
        if not success:
            logger.warning("provider_delete_not_found", provider_id=provider_id)
            raise NotFoundError("Provider", provider_id)

        await LoadBalancer.remove_provider_state(self.session, provider_id)
        
        logger.info("provider_deleted", provider_id=provider_id, statuses_cleaned=deleted_count)
        
        await emit_provider_event(
            EventType.PROVIDER_STATUS,
            provider_id,
            {"status": "deleted", "statuses_cleaned": deleted_count}
        )
        
        return True
    
    async def upsert_provider_from_discovery(
        self,
        provider_id: str,
        provider_type: str,
        internal_url: str,
        worker_type: str = "image",
    ) -> Provider:
        """Create or update a provider record from a live discovery heartbeat.
        
        This is the mechanism by which external provider containers register
        themselves with the backend. Providers that are never discovered are
        excluded from the active provider list.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        container_name = f"tnhcomfy-{provider_id}"
        container_config = {"container_name": container_name}

        existing = self.repo.get(provider_id)
        if existing:
            updates: dict[str, Any] = {}
            if existing.worker_type != worker_type:
                updates["worker_type"] = worker_type
            config = dict(existing.config or {})
            config["last_seen_at"] = now
            config["discovery_url"] = internal_url
            updates["config"] = config
            if not existing.container_config:
                updates["container_config"] = container_config
            updated = self.repo.update(provider_id, updates)
            logger.info("provider_discovery_updated", provider_id=provider_id, url=internal_url)
            return updated or existing

        provider = self.repo.create({
            "id": provider_id,
            "type": provider_type,
            "worker_type": worker_type,
            "enabled": True,
            "priority": 1,
            "container_config": container_config,
            "config": {
                "last_seen_at": now,
                "discovery_url": internal_url,
                "discovered": True,
            },
        })
        logger.info("provider_discovery_created", provider_id=provider_id, type=provider_type, url=internal_url)
        return provider

    def get_load_balancing_config(self) -> LoadBalancingConfig:
        return self.lb_repo.get()
    
    async def update_load_balancing_config(self, **updates) -> LoadBalancingConfig:
        return self.lb_repo.update(**updates)
    
    def _provider_to_dict(self, provider: Provider) -> dict[str, Any]:
        runtime = resolve_provider_runtime(provider)
        deploy_state = read_deploy_state(provider)
        reconciliation_state = read_reconciliation_state(provider)
        runtime_config = extract_runtime_config(provider.type, provider.container_config, provider.config or {})
        deploy_config = extract_deploy_config(provider.type, provider.config or {})
        capabilities, capability_reasons = self._build_capabilities(
            provider=provider,
            runtime=runtime,
            runtime_config=runtime_config,
            deploy_config=deploy_config,
        )
        provider_config = clean_dict(provider.config or {})
        return {
            "id": provider.id,
            "type": provider.type,
            "worker_type": provider.worker_type,
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
                "discovered": bool(provider_config.get("discovered") or provider_config.get("last_seen_at")),
                "last_seen_at": provider_config.get("last_seen_at"),
                "discovery_url": provider_config.get("discovery_url"),
            },
            "capabilities": capabilities,
            "capability_reasons": capability_reasons,
            "credential_summary": self._summarize_credentials(provider.type, clean_dict(provider.credentials), deploy_config, runtime),
        }
    
    def get_model_cache(self) -> dict[str, Any]:
        from services.model_service import ModelServiceV2
        model_service = ModelServiceV2(self.session)
        return model_service.get_full_cache()
    
    def get_model_cache_for_directory(self, directory: str) -> list[dict[str, Any]]:
        from services.model_service import ModelServiceV2
        model_service = ModelServiceV2(self.session)
        cache = model_service.get_full_cache()
        return cache.get(directory, [])
    
    async def get_load_balancer_stats(self) -> dict[str, Any]:
        from services.load_balancer_factory import create_load_balancer
        config = self.get_load_balancing_config()
        load_balancer = create_load_balancer(
            self.session,
            strategy=config.strategy if config else None,
        )
        return await load_balancer.get_stats()
