# Provider Service - Business logic for provider management
import secrets
from copy import deepcopy
from typing import Any

from sqlmodel import Session
from sqlalchemy import update

from core.entities import VALID_TASK_TYPES, Job, LoadBalancingConfig, Provider
from core.events import EventType, emit_provider_event
from core.exceptions import NotFoundError, ValidationError
from infrastructure.logging import provider_logger
from infrastructure.repositories import LoadBalancingRepository, ProviderRepository
from services.provider_reconciliation_service import ProviderReconciliationService
from services.provider_runtime import resolve_provider_runtime
from services.provider_utils import (
    clean_dict,
    compose_config,
    extract_deploy_config,
    extract_runtime_config,
    mask_secret,
    normalize_reconciliation_status,
    read_reconciliation_state,
)

logger = provider_logger()

# Provider types that are always LLM workers regardless of id/name.
LLM_PROVIDER_TYPES = {"openai_compat", "openai", "anthropic", "google", "gemini", "ollama", "modal_llm"}


def _normalize_capabilities(
    value: Any,
    *,
    existing: Provider | None,
    worker_type: str,
) -> list[str]:
    """Validate and canonicalise `Provider.capabilities` on the write path.

    Validation lives here, not on the model's `field_validator`, because
    SQLModel does not run validators for table models on either assignment or
    construction unless `validate_assignment` is set — and setting it on a model
    this widely used has a blast radius well beyond this column. Every provider
    write funnels through this method, so this is the right seam.

    Unknown entries are REJECTED rather than dropped or ignored. A typo here is
    the worst kind of config error: `serves()` would quietly exclude the
    provider for a task type nobody asked about, the job would fail as "no
    provider available", and nothing would point at a spelling mistake in a JSON
    column. Failing at the write, with the valid set in the message, is the only
    version the operator can act on.

    Absent means "inherit". An existing provider keeps whatever it had; a new
    one with nothing declared gets `[worker_type]`, which is exactly its
    behaviour before this column existed.

    A declared list does NOT need to repeat `worker_type`: `serves()` is
    additive, so `["tts"]` on an image worker means "also does tts". That
    matters because the alternative — requiring the full list — makes a
    narrowed edit a way to take a working provider out of image rotation.
    """
    if value is None:
        current = list(getattr(existing, "capabilities", None) or [])
        if not current and worker_type == "hybrid":
            return ["image", "llm", "tts"]
        return current or [worker_type]

    if not isinstance(value, (list, tuple, set)):
        raise ValidationError(
            f"capabilities must be a list of task types, got {type(value).__name__}"
        )

    declared = [str(v) for v in value if str(v).strip()]
    unknown = sorted({c for c in declared if c not in VALID_TASK_TYPES})
    if unknown:
        raise ValidationError(
            f"unknown provider capabilit{'y' if len(unknown) == 1 else 'ies'} "
            f"{unknown}; valid task types are {sorted(VALID_TASK_TYPES)}"
        )

    # De-duplicate while preserving the declared order, which is how the UI
    # renders them and how a diff reads.
    seen: set[str] = set()
    ordered = [c for c in declared if not (c in seen or seen.add(c))]
    return ordered or (["image", "llm", "tts"] if worker_type == "hybrid" else [worker_type])


def _infer_worker_type(provider_id: str, provider_type: str, explicit: str | None = None) -> str:
    """Infer worker_type, preferring explicit value, then known LLM provider types, then id/type prefixes."""
    if explicit and explicit != "image":
        return explicit
    if str(provider_type).lower() in LLM_PROVIDER_TYPES:
        return "llm"
    if str(provider_id).lower().startswith("llm") or str(provider_type).lower().startswith("llm"):
        return "llm"
    if str(provider_type).lower() == "remote_hybrid" or "hybrid" in str(provider_type).lower():
        return "hybrid"
    return "image"


class ProviderService:
    """
    Handles provider lifecycle and configuration.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.repo = ProviderRepository(session)
        self.lb_repo = LoadBalancingRepository(session)
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
        payload["capabilities"] = _normalize_capabilities(
            payload.get("capabilities"),
            existing=existing,
            worker_type=worker_type,
        )
        existing_config = clean_dict(getattr(existing, "config", None))
        merged_config = clean_dict(existing_config)
        merged_config.update(clean_dict(payload.get("config")))

        # `runtime_config` is legacy placement: an explicit payload value
        # (including null, which is what the current UI sends) wins, otherwise
        # the stored value round-trips untouched.
        if "runtime_config" in payload:
            runtime_config = clean_dict(payload.get("runtime_config")) or None
        else:
            runtime_config = extract_runtime_config(merged_config)

        raw_deploy_config = clean_dict(payload.get("deploy_config"))
        deploy_config = extract_deploy_config(
            {
                **merged_config,
                "deploy_config": raw_deploy_config,
            },
        )

        config = compose_config(
            base_config=merged_config,
            runtime_config=runtime_config,
            deploy_config=deploy_config,
            reconciliation_state=read_reconciliation_state(existing) if existing else None,
        )

        return {
            "id": payload.get("id") or getattr(existing, "id", None),
            "type": provider_type,
            "worker_type": payload.get("worker_type"),
            "enabled": payload.get("enabled", getattr(existing, "enabled", True)),
            "priority": payload.get("priority", getattr(existing, "priority", 1)),
            "credentials": clean_dict(payload.get("credentials", getattr(existing, "credentials", {}))),
            "config": config,
            # Column name, so `repo.create`/`repo.update` (which splat this
            # dict into the model) persist it rather than dropping a kwarg it
            # does not recognise. The wire name is `declared_capabilities`;
            # the route maps between the two.
            "capabilities": payload.get("capabilities"),
        }

    def _summarize_credentials(self, provider_type: str, credentials: dict[str, Any], deploy_config: dict[str, Any], runtime: Any) -> dict[str, Any]:
        # Required-field answers come from the engine registry (the in-process
        # source of truth), not the container-era ProviderRegistry whose
        # `required_credentials` still demand e.g. a Modal `username` nobody
        # needs anymore. Validating the wrong contract marked healthy
        # in-process providers `ready: false` on every status card.
        from services.engines.registry import missing_provider_fields
        validation = missing_provider_fields(provider_type, credentials, deploy_config)
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
        missing_credentials = validation["credentials"]
        missing_config = validation["config"]
        return {
            "configured_fields": configured_fields,
            "missing_required_credentials": missing_credentials,
            "missing_required_config": missing_config,
            "account_label": account_label,
            "has_credentials": bool(configured_fields),
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
        capabilities = {
            "setup": runtime.supports_setup,
            "reconcile": runtime.supports_reconciliation,
            "reset_status": True,
        }

        reasons = {
            "setup": None if capabilities["setup"] else "Setup is only available for Modal providers with an in-process engine",
            "reconcile": None if capabilities["reconcile"] else "Runtime worker is unavailable",
        }
        return capabilities, reasons

    async def get_provider_reconciliation_state(self, provider_id: str) -> dict[str, Any]:
        provider = await self.get_provider(provider_id)
        return await self.reconciliation_service.get_provider_reconciliation_state(provider)

    async def start_reconciliation_session(self, provider_id: str, force: bool = False) -> dict[str, Any]:
        provider = await self.get_provider(provider_id)
        return await self.reconciliation_service.start_reconciliation_session(provider, force=force)

    def upsert_reconciliation_state(self, provider_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Merge reconciliation state for a provider and persist it.

        Synchronous since 2026-10-03: the repository read plus the state merge
        plus the commit have no suspension in them, so the `async def` this
        replaced ran a blocking write on the event loop for every worker
        heartbeat that pushed a reconciliation event. Callers that are
        themselves `async def` go through `asyncio.to_thread`.
        """
        provider = self.repo.get(provider_id)
        if not provider:
            logger.warning("provider_not_found", provider_id=provider_id)
            raise NotFoundError("Provider", provider_id)
        return self.reconciliation_service.upsert_reconciliation_state(provider, updates)
    
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
        result.sort(key=lambda d: d.get("priority", 1))
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
                "config": normalized["config"],
                "capabilities": normalized["capabilities"],
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
    
    def _base_config(self, provider: Provider) -> dict[str, Any]:
        """The provider's composed config, ready to have one key changed.

        `_normalize_provider_for_storage` cannot be used to *remove* a key: it
        merges the payload over the existing config, so a payload without
        `worker_token` leaves the stored token in place. Revoking that way
        returned `revoked: true` while leaving the credential live — the one
        outcome worse than not having the feature. Normalising with an empty
        payload gives the composed config, which is then written back verbatim;
        doing so is idempotent.
        """
        return self._normalize_provider_for_storage({}, existing=provider)["config"]

    async def mint_worker_token(self, provider_id: str) -> str:
        """Generate a fresh external-worker token for `provider_id` and return it.

        The external-worker WebSocket (`/ws/worker/{provider_id}`) authenticates
        against `config.worker_token`. That key was readable but had no way to be
        produced: nothing in the backend, the provider containers, the frontend,
        compose or the docs ever set it, so the check could only ever fail, no
        worker could ever register, `is_worker_connected` was permanently False,
        and `resolve_provider_runtime` could never return `mode="external_worker"`.
        The tests passed because they hand-built a provider with the key already
        present.

        Rotating replaces any previous token, so a leaked one is invalidated by
        minting again. The token is returned once and never re-read through the
        provider payload: `_provider_to_dict` redacts it.

        This app has no authentication, so minting is as reachable as every other
        provider write here. It is no weaker than the rest of the surface, but it
        does write a credential — see docs/audit-2026-09-26-followup.md.
        """
        config = self._base_config(await self.get_provider(provider_id))
        token = secrets.token_urlsafe(32)
        config["worker_token"] = token
        self.repo.update(provider_id, {"config": config})
        logger.info("provider_worker_token_minted", provider_id=provider_id)
        return token

    async def revoke_worker_token(self, provider_id: str) -> bool:
        """Remove the external-worker token, disconnecting the mode entirely."""
        config = self._base_config(await self.get_provider(provider_id))
        if not config.pop("worker_token", None):
            return False
        self.repo.update(provider_id, {"config": config})
        logger.info("provider_worker_token_revoked", provider_id=provider_id)
        return True

    def _detach_provider_jobs(self, provider_id: str) -> int:
        """Null out `jobs.provider_id` for a deleted provider, in one statement.

        Returns the number of rows updated. Uses a Core UPDATE rather than an
        ORM load-and-mutate so the row count is known without materialising the
        job rows, and so the whole detach is one round trip regardless of how
        many jobs the provider has run.
        """
        result = self.session.exec(
            update(Job).where(Job.provider_id == provider_id).values(provider_id=None)
        )
        rowcount = result.rowcount or 0
        if rowcount:
            self.session.commit()
        return rowcount

    async def delete_provider(self, provider_id: str) -> bool:
        from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
        from services.load_balancer import LoadBalancer
        
        model_repo = ModelRepositoryV2(self.session)
        deleted_count = model_repo.delete_all_statuses_for_provider(provider_id)
        if deleted_count > 0:
            logger.info("provider_cascade_delete", provider_id=provider_id, statuses_deleted=deleted_count)

        # `jobs.provider_id` is a plain column with NO ACTION foreign key to
        # providers (migration 063), so deleting a provider that has run a job
        # raised ForeignKeyViolationError and 500'd. Job history is worth
        # keeping, so the reference is cleared rather than cascading: the rows
        # stay and the provider column becomes NULL, which is exactly what the
        # column's `str | None` type already allows.
        #
        # Done as one statement-level UPDATE. Selecting the matching rows and
        # assigning them in Python had no LIMIT and pulled every `Job` — with
        # its multi-KB `workflow` and `metadata` JSONB — into memory, then
        # flushed it back as one UPDATE per row, all inline on the event loop
        # (this route awaits the service directly).
        jobs_detached = self._detach_provider_jobs(provider_id)
        if jobs_detached:
            logger.info("provider_jobs_detached", provider_id=provider_id, jobs_detached=jobs_detached)
        
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
    
    def get_load_balancing_config(self) -> LoadBalancingConfig:
        return self.lb_repo.get()
    
    async def update_load_balancing_config(self, **updates) -> LoadBalancingConfig:
        return self.lb_repo.update(**updates)
    
    def _provider_to_dict(self, provider: Provider) -> dict[str, Any]:
        runtime = resolve_provider_runtime(provider)
        reconciliation_state = read_reconciliation_state(provider)
        runtime_config = extract_runtime_config(provider.config or {})
        deploy_config = extract_deploy_config(provider.config or {})
        capabilities, capability_reasons = self._build_capabilities(
            provider=provider,
            runtime=runtime,
            runtime_config=runtime_config,
            deploy_config=deploy_config,
        )
        provider_config = clean_dict(provider.config or {})
        # Only specific keys are read off `provider_config` below, so the token was
        # not being emitted today. Popping it here means that stays true if anyone
        # ever spreads the whole config into the payload, and `has_worker_token` is
        # the only thing the UI needs to know about it.
        has_worker_token = bool(provider_config.get("worker_token"))
        provider_config.pop("worker_token", None)
        return {
            "id": provider.id,
            "type": provider.type,
            "worker_type": provider.worker_type,
            "enabled": provider.enabled,
            "priority": provider.priority,
            "runtime_config": runtime_config,
            "deploy_config": deploy_config,
            "reconciliation_state": reconciliation_state,
            "has_worker_token": has_worker_token,
            "runtime_state": {
                "mode": runtime.mode,
                "connected": runtime.connected,
                "status": runtime.status,
                "healthy": runtime.healthy,
                "supports_setup": runtime.supports_setup,
                "supports_reconciliation": runtime.supports_reconciliation,
                "worker_url": runtime.worker_url,
            },
            "capabilities": capabilities,
            "capability_reasons": capability_reasons,
            # The DB column the load balancer's `serves()` reads. Exposed under
            # its own name because `capabilities` above is the unrelated UI
            # action map the frontend has always consumed under that key — two
            # different meanings on one field, where the one that answers "can
            # this provider serve TTS" was the one missing.
            "declared_capabilities": list(provider.capabilities or []),
            # Validated against the engine config: credentials plus the union
            # of stored config and engine settings.
            "credential_summary": self._summarize_credentials(
                provider.type,
                clean_dict(provider.credentials),
                {**(provider.config or {}), **deploy_config},
                runtime,
            ),
        }
    
    async def get_load_balancer_stats(self) -> dict[str, Any]:
        from services.load_balancer_factory import create_load_balancer
        config = self.get_load_balancing_config()
        load_balancer = create_load_balancer(
            self.session,
            strategy=config.strategy if config else None,
        )
        return await load_balancer.get_stats()
