from datetime import datetime, timezone
from typing import Any

from core.entities import Provider
from core.exceptions import NotFoundError
from infrastructure.repositories import ProviderRepository
from services.provider_utils import (
    RECONCILIATION_IN_PROGRESS_STATUSES,
    RECONCILIATION_IN_PROGRESS_TTL,
    RECONCILIATION_TERMINAL_STATUSES,
    compose_config,
    extract_deploy_config,
    extract_runtime_config,
    normalize_reconciliation_status,
    parse_utc_timestamp,
    read_deploy_state,
    read_reconciliation_state,
    utcnow_iso,
)


class ProviderReconciliationService:
    def __init__(self, repo: ProviderRepository):
        self.repo = repo

    def _persist_reconciliation_state(self, provider: Provider, state: dict[str, Any]) -> dict[str, Any]:
        config = compose_config(
            base_config=provider.config,
            runtime_config=extract_runtime_config(provider.type, provider.container_config, provider.config or {}),
            deploy_config=extract_deploy_config(provider.type, provider.config or {}, provider.worker_type or "image"),
            deploy_state=read_deploy_state(provider),
            reconciliation_state=state,
        )
        updated = self.repo.update(provider.id, {"config": config})
        if updated is None:
            raise NotFoundError("Provider", provider.id)
        return state

    def _is_reconciliation_in_progress(self, state: dict[str, Any]) -> bool:
        return normalize_reconciliation_status(state.get("status")) in RECONCILIATION_IN_PROGRESS_STATUSES

    def _is_reconciliation_state_fresh(self, state: dict[str, Any]) -> bool:
        if not self._is_reconciliation_in_progress(state):
            return True

        updated_at_raw = state.get("updated_at") or state.get("started_at")
        updated_at = parse_utc_timestamp(updated_at_raw)
        if not updated_at:
            return True
        age = datetime.now(timezone.utc) - updated_at
        return age.total_seconds() <= RECONCILIATION_IN_PROGRESS_TTL

    async def get_provider_reconciliation_state(self, provider: Provider) -> dict[str, Any]:
        state = read_reconciliation_state(provider)
        state["status"] = normalize_reconciliation_status(state.get("status"))
        if self._is_reconciliation_state_fresh(state):
            return state

        stale_state = {
            "provider_id": provider.id,
            "status": "failed",
            "message": "Reconciliation state expired and was marked failed",
            "started_at": state.get("started_at"),
            "updated_at": utcnow_iso(),
            "finished_at": utcnow_iso(),
            "phase": state.get("phase"),
            "stats": state.get("stats") or {},
            "errors": state.get("errors") or [],
            "last_contact_at": state.get("last_contact_at"),
            "warning": "Reconciliation state became stale before the worker reported completion",
        }
        self._persist_reconciliation_state(provider, stale_state)
        return stale_state

    async def start_reconciliation_session(self, provider: Provider, force: bool = False) -> dict[str, Any]:
        current_state = read_reconciliation_state(provider)
        if not force and self._is_reconciliation_in_progress(current_state) and self._is_reconciliation_state_fresh(current_state):
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
            "started_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
        }
        self._persist_reconciliation_state(provider, next_state)
        return {"accepted": True, "state": next_state}

    async def upsert_reconciliation_state(self, provider: Provider, updates: dict[str, Any]) -> dict[str, Any]:
        current_state = read_reconciliation_state(provider)

        merged = dict(current_state)
        merged.update({k: v for k, v in updates.items() if v is not None})
        merged["provider_id"] = provider.id
        merged["status"] = normalize_reconciliation_status(merged.get("status"))
        merged["updated_at"] = utcnow_iso()

        status = merged.get("status", "idle")
        if status in RECONCILIATION_IN_PROGRESS_STATUSES and not merged.get("started_at"):
            merged["started_at"] = utcnow_iso()
        if status in RECONCILIATION_TERMINAL_STATUSES:
            merged["finished_at"] = utcnow_iso()
        if updates.get("last_contact_at"):
            merged["last_contact_at"] = updates["last_contact_at"]

        self._persist_reconciliation_state(provider, merged)
        return merged
