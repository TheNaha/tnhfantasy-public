from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from cachetools import TTLCache
from sqlmodel import Session, select

from services.provider_runtime import resolve_provider_runtime
from config import get_worker_backend_url
from core.entities import ModelFile, ModelVersion, ModelV2
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from services.container_manager import get_container_manager
from services.model_service import ModelServiceV2
from services.provider_service import ProviderService

logger = get_logger("provider_status_service")

_modal_stats_cache = TTLCache(maxsize=10, ttl=30)


def invalidate_provider_status_caches(provider_id: Optional[str] = None) -> None:
    """Clear cached provider status snapshots after lifecycle changes."""
    if provider_id:
        _modal_stats_cache.pop(f"modal_stats_{provider_id}", None)
        return
    _modal_stats_cache.clear()


class ProviderStatusService:
    """Build canonical provider status payloads outside of route handlers."""

    def __init__(
        self,
        session: Session,
        provider_service: Optional[ProviderService] = None,
    ) -> None:
        self.session = session
        self.provider_service = provider_service or ProviderService(session)

    @staticmethod
    def normalize_reconciliation_for_card(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Normalize reconciliation state for provider card display."""
        normalized = dict(state or {})
        status = ProviderService.normalize_reconciliation_status(normalized.get("status"))
        normalized["status"] = status
        if status in {"completed", "failed"} and not normalized.get("phase"):
            normalized["phase"] = status
        if status == "queued" and not normalized.get("phase"):
            normalized["phase"] = "queued"
        return normalized

    @staticmethod
    def empty_storage_payload(provider_id: str, error: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "provider_id": provider_id,
            "total": 0,
            "by_directory": {},
        }
        if error:
            payload["error"] = error
        return payload

    @staticmethod
    def _storage_payload_from_reconciliation_state(
        provider_id: str,
        reconciliation_state: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Derive storage stats from persisted reconciliation state when available."""
        if not isinstance(reconciliation_state, dict):
            return None

        stats = reconciliation_state.get("stats")
        if not isinstance(stats, dict) or not stats:
            return None

        by_directory = stats.get("by_directory")
        if not isinstance(by_directory, dict):
            by_directory = {}

        total_value = None
        for key in ("total", "total_models", "total_models_in_storage"):
            value = stats.get(key)
            if isinstance(value, (int, float)):
                total_value = value
                break

        if total_value is None and by_directory:
            total_value = sum(
                int(value)
                for value in by_directory.values()
                if isinstance(value, (int, float))
            )

        if total_value is None:
            return None

        return {
            "provider_id": provider_id,
            "total": int(total_value),
            "by_directory": by_directory,
        }

    async def get_provider_sync_status(self, provider_id: str) -> Dict[str, Any]:
        """Return V2-backed sync counts for a provider."""
        service = ModelServiceV2(self.session)
        stmt = select(ModelFile, ModelVersion, ModelV2).join(
            ModelVersion, ModelFile.version_id == ModelVersion.id
        ).join(
            ModelV2, ModelVersion.model_id == ModelV2.id
        ).where(
            ModelVersion.is_enabled == True
        )

        rows = self.session.exec(stmt).all()
        status_map = service.repo.get_provider_statuses_for_files(
            [file.id for file, _version, _model in rows],
            provider_id,
        )

        stats = {
            "installed": 0,
            "pending": 0,
            "downloading": 0,
            "failed": 0,
        }
        models = []

        for file, _version, model in rows:
            provider_status = status_map.get(file.id)
            status = provider_status.status if provider_status else "pending"
            normalized_status = "installed" if status == "ready" else status
            stats[normalized_status] = stats.get(normalized_status, 0) + 1
            models.append({
                "file_id": file.id,
                "model_id": model.id,
                "name": file.storage_filename,
                "directory": f"models/{model.directory}",
                "provider_status": {
                    "status": normalized_status,
                    "storage_path": provider_status.storage_path if provider_status else None,
                    "size_bytes": provider_status.size_bytes if provider_status else None,
                    "error_message": provider_status.error_message if provider_status else None,
                },
                "size": (file.size_kb or 0) * 1024,
            })

        return {
            "provider": provider_id,
            "total_models": len(models),
            "stats": stats,
            "models": models,
        }

    async def get_provider_storage_stats(
        self,
        provider_id: str,
        provider: Optional[Any] = None,
        reconciliation_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Fetch provider storage stats from the worker with cache and fallbacks."""
        cache_key = f"modal_stats_{provider_id}"

        if reconciliation_state is None:
            try:
                reconciliation_state = await self.provider_service.get_provider_reconciliation_state(provider_id)
            except Exception:
                reconciliation_state = None

        state_payload = self._storage_payload_from_reconciliation_state(provider_id, reconciliation_state)
        if state_payload:
            _modal_stats_cache[cache_key] = state_payload
            return state_payload

        if cache_key in _modal_stats_cache:
            return _modal_stats_cache[cache_key]

        provider = provider or await self.provider_service.get_provider(provider_id)
        runtime = resolve_provider_runtime(provider)
        if runtime.mode not in ("container_http", "discovery"):
            return self.empty_storage_payload(
                provider_id,
                "Stats are only available for container-backed or discovered providers",
            )

        container_manager = get_container_manager()
        if not container_manager:
            return self.empty_storage_payload(provider_id, "Container manager not initialized")

        try:
            container = container_manager.client.containers.get(
                runtime.container_name or f"comfy-provider-{provider_id}"
            )
            if container.status != "running":
                return self.empty_storage_payload(provider_id, "Container not running")
        except Exception:
            return self.empty_storage_payload(provider_id, "Container not found")

        # Workers now use unified /provider-stats endpoint
        stats_endpoint = "/provider-stats"
        http_client = get_http_client()
        worker_url = f"{runtime.worker_url}{stats_endpoint}"

        try:
            response = await http_client.get(worker_url, timeout=45.0)
            if response.status_code != 200:
                return self.empty_storage_payload(provider_id, f"HTTP {response.status_code}")

            payload = response.json()
            result = {
                "provider_id": payload.get("provider_id") or provider_id,
                "total": payload.get("total", 0),
                "by_directory": payload.get("by_directory") or {},
            }
            if payload.get("error"):
                result["error"] = payload["error"]

            _modal_stats_cache[cache_key] = result
            return result
        except (httpx.HTTPError, ValueError) as exc:
            error_message = str(exc).strip() or type(exc).__name__
            logger.error(
                "provider_storage_stats_fetch_failed",
                provider_id=provider_id,
                worker_url=worker_url,
                error_type=type(exc).__name__,
                error=error_message,
            )
            return self.empty_storage_payload(provider_id, error_message)

    async def get_live_reconciliation_state(
        self,
        provider_id: str,
        provider: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Refresh reconciliation state from the worker when possible."""
        persisted_state = await self.provider_service.get_provider_reconciliation_state(provider_id)
        provider = provider or await self.provider_service.get_provider(provider_id)
        runtime = resolve_provider_runtime(provider)

        if runtime.mode not in ("container_http", "discovery"):
            return self.normalize_reconciliation_for_card(persisted_state)

        http_client = get_http_client()
        try:
            response = await http_client.get(
                f"{runtime.worker_url}/reconciliation-status",
                timeout=10.0,
            )
            if response.status_code != 200:
                if persisted_state.get("status") and persisted_state.get("status") != "idle":
                    return self.normalize_reconciliation_for_card(persisted_state)
                return self.normalize_reconciliation_for_card({
                    "provider_id": provider_id,
                    "status": "idle",
                    "warning": f"Worker returned HTTP {response.status_code} for reconciliation status",
                })

            worker_state = response.json()
            merged_state = await self.provider_service.upsert_reconciliation_state(
                provider_id,
                {
                    **worker_state,
                    "last_contact_at": ProviderService._utcnow_iso(),
                },
            )
            return self.normalize_reconciliation_for_card(merged_state)
        except (httpx.HTTPError, ValueError) as exc:
            if persisted_state.get("status") and persisted_state.get("status") != "idle":
                merged_state = await self.provider_service.upsert_reconciliation_state(
                    provider_id,
                    {"warning": f"Worker unreachable: {str(exc)}"},
                )
                return self.normalize_reconciliation_for_card(merged_state)
            return self.normalize_reconciliation_for_card({
                "provider_id": provider_id,
                "status": "idle",
                "warning": f"Worker unreachable: {str(exc)}",
            })

    @staticmethod
    def build_provider_diagnostics(
        *,
        provider_id: str,
        provider_info: Dict[str, Any],
        runtime: Any,
        storage_stats: Dict[str, Any],
        reconciliation_state: Dict[str, Any],
        deploy_state: Dict[str, Any],
        model_sync: Dict[str, Any],
    ) -> Dict[str, Any]:
        warnings: List[str] = []
        errors: List[str] = []

        if storage_stats.get("error"):
            warnings.append(f"Storage stats unavailable: {storage_stats['error']}")
        if reconciliation_state.get("warning"):
            warnings.append(reconciliation_state["warning"])
        if reconciliation_state.get("error"):
            errors.append(reconciliation_state["error"])
        if reconciliation_state.get("status") == "failed" and reconciliation_state.get("message"):
            errors.append(reconciliation_state["message"])
        if deploy_state.get("status") == "failed" and deploy_state.get("message"):
            errors.append(deploy_state["message"])
        if model_sync.get("stats", {}).get("downloading", 0) > 0 and reconciliation_state.get("status") == "idle":
            warnings.append("Database download state is active while reconciliation is idle")

        updated_candidates = [
            reconciliation_state.get("updated_at"),
            reconciliation_state.get("last_contact_at"),
            deploy_state.get("updated_at"),
        ]

        return {
            "provider_id": provider_id,
            "warnings": warnings,
            "errors": errors,
            "worker": {
                "backend_url": get_worker_backend_url(),
                "worker_url": runtime.worker_url,
                "mode": runtime.mode,
                "connected": runtime.connected,
                "supports_setup": runtime.supports_setup,
                "supports_reconciliation": runtime.supports_reconciliation,
            },
            "affected_provider_ids": [provider_id],
            "updated_at": max((value for value in updated_candidates if value), default=None),
            "provider_enabled": provider_info.get("enabled", True),
        }

    async def build_provider_status_card(
        self,
        provider_id: str,
        *,
        provider_payload: Optional[Dict[str, Any]] = None,
        provider: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Build the canonical provider status payload used by provider cards."""
        provider = provider or await self.provider_service.get_provider(provider_id)
        provider_info = provider_payload or self.provider_service._provider_to_dict(provider)
        runtime = resolve_provider_runtime(provider)

        sync_status = await self.get_provider_sync_status(provider_id)
        model_sync = {
            "provider_id": provider_id,
            "total_models": sync_status.get("total_models", 0),
            "stats": sync_status.get("stats") or {},
            "updated_at": ProviderService._utcnow_iso(),
        }
        reconciliation_state = await self.get_live_reconciliation_state(provider_id, provider)
        storage_stats = await self.get_provider_storage_stats(
            provider_id,
            provider,
            reconciliation_state=reconciliation_state,
        )
        deploy_state = await self.provider_service.get_provider_deploy_state(provider_id)
        diagnostics = self.build_provider_diagnostics(
            provider_id=provider_id,
            provider_info=provider_info,
            runtime=runtime,
            storage_stats=storage_stats,
            reconciliation_state=reconciliation_state,
            deploy_state=deploy_state,
            model_sync=model_sync,
        )

        return {
            "provider_id": provider_id,
            "provider_type": provider_info.get("type"),
            "runtime": {
                **(provider_info.get("runtime_state") or {}),
                "enabled": provider_info.get("enabled", True),
                "backend_url": get_worker_backend_url(),
                "worker_url": runtime.worker_url,
                "capabilities": provider_info.get("capabilities") or {},
            },
            "model_sync": model_sync,
            "storage": storage_stats,
            "reconciliation": reconciliation_state,
            "deploy": deploy_state,
            "diagnostics": diagnostics,
        }

    def build_provider_status_card_fallback(
        self,
        provider_info: Dict[str, Any],
        *,
        error: str = "Failed to build provider status card",
    ) -> Dict[str, Any]:
        """Return a stable fallback status card when live assembly fails."""
        provider_id = provider_info.get("id")
        runtime_state = provider_info.get("runtime_state") or {}
        return {
            "provider_id": provider_id,
            "provider_type": provider_info.get("type"),
            "runtime": runtime_state,
            "model_sync": {"provider_id": provider_id, "total_models": 0, "stats": {}},
            "storage": self.empty_storage_payload(provider_id, error),
            "reconciliation": self.normalize_reconciliation_for_card(
                provider_info.get("reconciliation_state") or {}
            ),
            "deploy": provider_info.get("deploy_state") or {"status": "idle"},
            "diagnostics": {
                "provider_id": provider_id,
                "warnings": [error],
                "errors": [],
                "worker": {
                    "backend_url": get_worker_backend_url(),
                    "worker_url": None,
                    "mode": runtime_state.get("mode"),
                    "connected": runtime_state.get("connected", False),
                },
                "affected_provider_ids": [provider_id],
                "updated_at": None,
                "provider_enabled": provider_info.get("enabled", True),
            },
            "error": error,
        }

    async def build_provider_record(
        self,
        provider_id: str,
        *,
        provider_payload: Optional[Dict[str, Any]] = None,
        provider: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Build the canonical provider record returned by /api/providers."""
        provider = provider or await self.provider_service.get_provider(provider_id)
        base_payload = provider_payload or self.provider_service._provider_to_dict(provider)
        status_card = await self.build_provider_status_card(
            provider_id,
            provider_payload=base_payload,
            provider=provider,
        )

        return {
            "id": base_payload.get("id"),
            "type": base_payload.get("type"),
            "enabled": base_payload.get("enabled", True),
            "priority": base_payload.get("priority"),
            "runtime_config": base_payload.get("runtime_config"),
            "deploy_config": base_payload.get("deploy_config"),
            "runtime_state": status_card.get("runtime", {}),
            "deploy_state": status_card.get("deploy", {}),
            "reconciliation_state": status_card.get("reconciliation", {}),
            "model_sync": status_card.get("model_sync", {}),
            "storage": status_card.get("storage", {}),
            "capabilities": base_payload.get("capabilities", {}),
            "capability_reasons": base_payload.get("capability_reasons", {}),
            "diagnostics": status_card.get("diagnostics", {}),
            "credential_summary": base_payload.get("credential_summary", {}),
        }

    async def build_provider_records(
        self,
        providers: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Build canonical provider records for a list response."""
        providers = providers if providers is not None else await self.provider_service.list_providers()
        records = []
        for provider in providers:
            provider_id = provider.get("id")
            if not provider_id:
                continue
            try:
                records.append(
                    await self.build_provider_record(
                        provider_id,
                        provider_payload=provider,
                    )
                )
            except Exception as exc:
                logger.warning("provider_record_failed", provider_id=provider_id, error=str(exc))
                records.append(self.build_provider_status_card_fallback(provider, error=str(exc)))
        return records

    async def build_provider_status_cards(
        self,
        providers: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Build canonical provider status cards for all providers."""
        providers = providers if providers is not None else await self.provider_service.list_providers()
        cards: Dict[str, Dict[str, Any]] = {}

        for provider in providers:
            provider_id = provider.get("id")
            if not provider_id:
                continue
            try:
                cards[provider_id] = await self.build_provider_status_card(
                    provider_id,
                    provider_payload=provider,
                )
            except Exception as exc:
                logger.warning("provider_status_card_failed", provider_id=provider_id, error=str(exc))
                cards[provider_id] = self.build_provider_status_card_fallback(provider)

        return cards
