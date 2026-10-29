from __future__ import annotations

from typing import Any

from sqlmodel import Session, func, select

from config import get_worker_backend_url
from core.entities import ModelFile, ModelV2, ModelVersion, ProviderVersionStatus
from core.events import redact_secrets
from infrastructure.logging import get_logger
from services.model_service import ModelServiceV2
from services.provider_runtime import resolve_provider_runtime_async
from services.provider_service import ProviderService

logger = get_logger("provider_status_service")

from infrastructure.cache import get_provider_stats_cache, invalidate_cache
import asyncio

# The per-provider model counters the providers page and the sidebar read.
# Every one of them is derived from ProviderVersionStatus rows belonging to THIS
# provider; nothing here is a global catalog count any more. See
# get_provider_sync_stats for what the old shape was doing.
_EMPTY_SYNC_STATS: dict[str, int] = {
    "installed": 0,
    "pending": 0,
    "downloading": 0,
    "failed": 0,
}


def _empty_sync_stats() -> dict[str, int]:
    return dict(_EMPTY_SYNC_STATS)


def invalidate_provider_status_caches(provider_id: str | None = None) -> None:
    """Clear cached provider status snapshots after lifecycle changes."""
    if provider_id:
        invalidate_cache("provider_stats", f"modal_stats_{provider_id}")
    else:
        invalidate_cache("provider_stats")


class ProviderStatusService:
    """Build canonical provider status payloads outside of route handlers."""

    def __init__(
        self,
        session: Session,
        provider_service: ProviderService | None = None,
    ) -> None:
        self.session = session
        self.provider_service = provider_service or ProviderService(session)

    @staticmethod
    def normalize_reconciliation_for_card(state: dict[str, Any] | None) -> dict[str, Any]:
        """Normalize reconciliation state for provider card display.

        Redaction happens HERE, on the whole state, not on the individual
        fields the card happens to surface. The leak was a CivitAI download
        token in the state that `provider_core/downloads.py` produced by putting
        it in the URL (`?token=`), lost through a transport exception's message
        text, persisted as a reconciliation error, and served straight back by
        `/api/v2/providers/status-cards`. Scrubbing the state on the way out
        covers rows that already contain the secret as well as future ones, and
        survives the error moving to a new key.
        """
        normalized = redact_secrets(dict(state or {}))
        status = ProviderService.normalize_reconciliation_status(normalized.get("status"))
        normalized["status"] = status
        if status in {"completed", "failed"} and not normalized.get("phase"):
            normalized["phase"] = status
        if status == "queued" and not normalized.get("phase"):
            normalized["phase"] = "queued"
        return normalized

    @staticmethod
    def empty_storage_payload(provider_id: str, error: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider_id": provider_id,
            "total": 0,
            "by_directory": {},
        }
        if error:
            payload["error"] = redact_secrets(error)
        return payload

    @staticmethod
    def _storage_payload_from_reconciliation_state(
        provider_id: str,
        reconciliation_state: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
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

    async def get_provider_sync_status(self, provider_id: str) -> dict[str, Any]:
        """Return V2-backed sync counts for a provider.

        Per-provider like :meth:`get_provider_sync_stats`: only model files this
        provider has a ``ProviderVersionStatus`` row for are listed, and a file
        with no row for this provider is *not* reported as ``pending`` on it.
        The old version listed the whole enabled catalog and defaulted every
        untracked file to ``pending``, which is how a provider that had never
        been asked to install anything was reported as holding the entire
        library in a queue.
        """
        service = ModelServiceV2(self.session)
        stmt = (
            select(ModelFile, ModelVersion, ModelV2)
            .join(ModelVersion, ModelFile.version_id == ModelVersion.id)
            .join(ModelV2, ModelVersion.model_id == ModelV2.id)
            .join(ProviderVersionStatus, ProviderVersionStatus.file_id == ModelFile.id)
            .where(
                ModelVersion.is_enabled == True,  # noqa: E712
                ProviderVersionStatus.provider_id == provider_id,
            )
            .order_by(ModelFile.storage_filename)
        )

        rows = self.session.exec(stmt).all()
        status_map = service.repo.get_provider_statuses_for_files(
            [file.id for file, _version, _model in rows],
            provider_id,
        )

        stats = _empty_sync_stats()
        models = []

        for file, _version, model in rows:
            provider_status = status_map.get(file.id)
            status = provider_status.status if provider_status else "pending"
            normalized_status = "installed" if status == "ready" else status
            if normalized_status in stats:
                stats[normalized_status] += 1
            models.append({
                "file_id": file.id,
                "model_id": model.id,
                "name": file.storage_filename,
                "directory": f"models/{model.directory}",
                "provider_status": {
                    "status": normalized_status,
                    "storage_path": provider_status.storage_path if provider_status else None,
                    "size_bytes": provider_status.size_bytes if provider_status else None,
                    "error_message": redact_secrets(provider_status.error_message) if provider_status else None,
                },
                "size": (file.size_kb or 0) * 1024,
            })

        return {
            "provider": provider_id,
            "total_models": len(models),
            "stats": stats,
            "models": models,
        }

    async def get_provider_sync_stats(
        self,
        provider_id: str,
        provider: Any | None = None,
    ) -> dict[str, Any]:
        """Aggregated per-provider model sync counts using SQL GROUP BY.

        Corrected semantics — every number below is scoped to ``provider_id``:

        ``total_models``
            Number of model files this provider has an install record for
            (``ProviderVersionStatus`` rows). It is NOT the size of the model
            catalog. It used to be: the query had no provider filter, so all
            five providers reported the same global total (521 on the live
            instance), including ``llm-local``, an LLM worker with no image
            models at all.
        ``stats``
            Counts of this provider's rows by status. ``pending`` used to be
            computed as ``global_total - this_provider's rows``, so a provider
            with zero rows claimed the entire catalog was queued on it. It is
            now just the number of this provider's own rows in ``pending`` —
            0 when nothing has been assigned to it.
        ``catalog_models``
            The global count of enabled model files, under a name that says so.
        ``has_install_intent``
            Whether this provider has any install record at all. A provider with
            ``False`` should be rendered as "not managing models", not as
            "N queued".

        An LLM or TTS provider reports all zeros: neither installs image models,
        so any number here would be fiction. The check was `worker_type ==
        "llm"` only, so a TTS provider fell through to the image branch and its
        card claimed to be tracking the whole 525-model image catalogue — live
        proof on the running stack, `tts-modal-hp196` reporting
        `"is_image_provider": true, "catalog_models": 525, "total_models": 0`.
        """
        if provider is None:
            provider = await self.provider_service.get_provider(provider_id)
        worker_type = getattr(provider, "worker_type", None) or "image"
        serves_fn = getattr(provider, "serves", None)
        serves_image = serves_fn("image") if callable(serves_fn) else (worker_type in ("image", "hybrid"))
        if worker_type not in ("image", "hybrid") and not serves_image:
            # Standalone LLM and TTS workers do not install image models. Reported as an
            # explicit zero rather than a real query so the card never shows a
            # count. Keyed on "is it an image provider" rather than on an
            # enumeration of the kinds that are not, so the next worker type
            # added is covered by default.
            return {
                "provider_id": provider_id,
                "total_models": 0,
                "stats": _empty_sync_stats(),
                "catalog_models": None,
                "has_install_intent": False,
                "is_image_provider": False,
            }

        stats_stmt = (
            select(
                ProviderVersionStatus.status,
                func.count(ProviderVersionStatus.id),
            )
            .join(ModelFile, ProviderVersionStatus.file_id == ModelFile.id)
            .join(ModelVersion, ModelFile.version_id == ModelVersion.id)
            .where(
                ModelVersion.is_enabled == True,  # noqa: E712
                ProviderVersionStatus.provider_id == provider_id,
            )
            .group_by(ProviderVersionStatus.status)
        )

        status_counts = self.session.exec(stats_stmt).all()

        stats = _empty_sync_stats()
        tracked_count = 0
        for status, count in status_counts:
            normalized = "installed" if status == "ready" else status
            if normalized in stats:
                stats[normalized] += count
            tracked_count += count

        return {
            "provider_id": provider_id,
            "total_models": tracked_count,
            "stats": stats,
            "catalog_models": self._catalog_model_count(),
            "has_install_intent": tracked_count > 0,
            "is_image_provider": True,
        }

    def _catalog_model_count(self) -> int:
        """Global count of enabled model files (labelled `catalog_models`).

        Cheap and provider-independent, so it is computed once per status-card
        build rather than once per provider.
        """
        from sqlmodel import func as _func, select as _select

        return int(
            self.session.exec(
                _select(_func.count(ModelFile.id))
                .join(ModelVersion, ModelFile.version_id == ModelVersion.id)
                .where(ModelVersion.is_enabled == True)  # noqa: E712
            ).one()
        )

    async def get_provider_storage_stats(
        self,
        provider_id: str,
        provider: Any | None = None,
        reconciliation_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch provider storage stats from the worker with cache and fallbacks to DB."""
        cache_key = f"modal_stats_{provider_id}"

        if reconciliation_state is None:
            try:
                reconciliation_state = await self.provider_service.get_provider_reconciliation_state(provider_id)
            except Exception as exc:
                logger.warning("provider_reconciliation_fetch_failed", provider_id=provider_id, error=str(exc))
                reconciliation_state = None

        state_payload = self._storage_payload_from_reconciliation_state(provider_id, reconciliation_state)
        _modal_stats_cache = get_provider_stats_cache()
        
        if state_payload:
            _modal_stats_cache[cache_key] = state_payload
            return state_payload

        if cache_key in _modal_stats_cache:
            return _modal_stats_cache[cache_key]

        # Fall back to querying the database directly
        try:
            count = self.session.exec(
                select(func.count(ProviderVersionStatus.id))
                .where(
                    ProviderVersionStatus.provider_id == provider_id
                )
                .where(ProviderVersionStatus.status == "ready")
            ).one()
            
            result = {
                "provider_id": provider_id,
                "total": count,
                "by_directory": {},
            }
            _modal_stats_cache = get_provider_stats_cache()
            _modal_stats_cache[cache_key] = result
            return result
        except Exception as exc:
            logger.error(
                "provider_storage_stats_fetch_failed",
                provider_id=provider_id,
                error=str(exc),
            )
            return self.empty_storage_payload(provider_id, str(exc))

    async def get_live_reconciliation_state(
        self,
        provider_id: str,
        provider: Any | None = None,
    ) -> dict[str, Any]:
        """Return the latest known reconciliation state (uses websockets for live updates)."""
        persisted_state = await self.provider_service.get_provider_reconciliation_state(provider_id)
        return self.normalize_reconciliation_for_card(persisted_state)

    async def get_live_deploy_state(
        self,
        provider_id: str,
        provider: Any | None = None,
    ) -> dict[str, Any]:
        """Return the latest deployment state for this provider if one was run, else idle."""
        from services.provider_deploy import get_last_deploy

        last = get_last_deploy(provider_id=provider_id)
        if last:
            return {
                "status": "completed" if last.get("ok") else "failed",
                "target": last.get("target"),
                "artifact": last.get("artifact"),
                "ok": last.get("ok"),
                "exit_code": last.get("exit_code"),
                "elapsed_seconds": last.get("elapsed_seconds"),
                "updated_at": last.get("timestamp"),
                "dry_run": last.get("dry_run", False),
                "output_tail": (last.get("output") or "")[-2000:] if last.get("output") else None,
            }
        return {"status": "idle"}

    @staticmethod
    def build_provider_diagnostics(
        *,
        provider_id: str,
        provider_info: dict[str, Any],
        runtime: Any,
        storage_stats: dict[str, Any],
        reconciliation_state: dict[str, Any],
        deploy_state: dict[str, Any],
        model_sync: dict[str, Any],
    ) -> dict[str, Any]:
        warnings: list[str] = []
        errors: list[str] = []

        # Provider-supplied text. Redacted HERE as well as in the caller, because
        # this is a public static method and a caller that reaches it directly
        # would otherwise be the one path that skips the scrub. Redaction is
        # idempotent, so the double application costs nothing.
        # See normalize_reconciliation_for_card for the leak this closes.
        storage_stats = redact_secrets(storage_stats)
        reconciliation_state = redact_secrets(reconciliation_state)
        deploy_state = redact_secrets(deploy_state)

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

    @staticmethod
    def _normalize_components(components: Any, cached_engine: Any) -> dict[str, Any] | None:
        """Normalise engine component health to per-service name/port/status.

        Remote engines already collect ``components`` as a dict of service →
        {status, port, url, latency_ms}; the poller's VRAM sample and the UI's
        component chips both want that shape guaranteed. Missing fields become
        explicit "unknown" markers instead of absent keys — a consumer must
        never have to branch on key presence to render a chip.
        """
        if not components and not hasattr(cached_engine, "comfy_port"):
            return None
        normalized: dict[str, Any] = {}
        raw = components if isinstance(components, dict) else {}
        if not raw and hasattr(cached_engine, "comfy_port"):
            raw = {
                "comfyui": {"status": "unknown", "port": getattr(cached_engine, "comfy_port", 8188)},
                "agent": {"status": "unknown", "port": getattr(cached_engine, "agent_port", 8001)},
                "llm": {"status": "unknown", "port": getattr(cached_engine, "llm_port", 8003)},
            }
        for name, entry in raw.items():
            if not isinstance(entry, dict):
                entry = {"status": entry} if entry is not None else {}
            status = entry.get("status")
            port = entry.get("port")
            normalized[name] = {
                "name": name,
                "status": str(status) if status else "unknown",
                "port": port if isinstance(port, int) else None,
                "url": entry.get("url"),
                "latency_ms": entry.get("latency_ms"),
            }
        return normalized or None

    async def build_provider_status_card(
        self,
        provider_id: str,
        *,
        provider_payload: dict[str, Any] | None = None,
        provider: Any | None = None,
    ) -> dict[str, Any]:
        """Build the canonical provider status payload used by provider cards."""
        provider = provider or await self.provider_service.get_provider(provider_id)
        provider_info = provider_payload or self.provider_service._provider_to_dict(provider)
        runtime = await resolve_provider_runtime_async(provider)

        sync_status = await self.get_provider_sync_stats(provider_id, provider=provider)
        model_sync = {
            "provider_id": provider_id,
            "total_models": sync_status.get("total_models", 0),
            "stats": sync_status.get("stats") or {},
            # Global catalog size, and whether this provider is managing models
            # at all. Consumers must use `total_models` for "how many models
            # does this provider track" and `catalog_models` (or nothing) for the
            # library size — the two used to be the same global number.
            "catalog_models": sync_status.get("catalog_models"),
            "has_install_intent": bool(sync_status.get("has_install_intent")),
            "is_image_provider": bool(sync_status.get("is_image_provider", True)),
            "updated_at": ProviderService._utcnow_iso(),
        }
        reconciliation_state = await self.get_live_reconciliation_state(provider_id, provider)
        storage_stats = await self.get_provider_storage_stats(
            provider_id,
            provider,
            reconciliation_state=reconciliation_state,
        )
        deploy_state = await self.get_live_deploy_state(provider_id, provider)
        diagnostics = self.build_provider_diagnostics(
            provider_id=provider_id,
            provider_info=provider_info,
            runtime=runtime,
            storage_stats=storage_stats,
            reconciliation_state=redact_secrets(reconciliation_state),
            deploy_state=redact_secrets(deploy_state),
            model_sync=model_sync,
        )

        from services.engines.engine_factory import _ENGINE_CACHE
        from services.engines.registry import resolve_transport
        from services.provider_telemetry_service import (
            SERVERLESS_TRANSPORTS,
            telemetry_service,
        )

        cached_engine = _ENGINE_CACHE.get(provider_id)
        transport = resolve_transport(provider_info.get("type"))

        # Core engine-derived telemetry (unchanged contract), then extended
        # with the poller's own view: liveness, VRAM history and — for
        # serverless transports — the inferred warm-window lifecycle.
        telemetry: dict[str, Any] = {}
        if cached_engine is not None:
            last_health = getattr(cached_engine, "_last_health", None) or {}
            gpu = getattr(cached_engine, "detected_gpu", None) or getattr(cached_engine, "_detected_gpu", None) or last_health.get("detected_gpu")
            policy = getattr(cached_engine, "concurrency_policy", None) or getattr(cached_engine, "_resolved_policy", None) or last_health.get("concurrency_policy")
            warm = getattr(cached_engine, "warm_workload", None) or getattr(cached_engine, "_last_workload", None) or last_health.get("warm_workload")
            components = self._normalize_components(
                last_health.get("components"), cached_engine
            )
            if gpu or policy or warm or components:
                telemetry = {
                    "detected_gpu": gpu,
                    "concurrency_policy": policy,
                    "warm_workload": warm,
                    "components": components,
                }

        poller_status = telemetry_service.get_provider_status(provider_id)
        if transport in SERVERLESS_TRANSPORTS:
            lifecycle = await telemetry_service.compute_serverless_lifecycle(provider)
        else:
            lifecycle = None
        # The P4 spike's Modal management-plane metadata (App.lookup + info),
        # probed by the poller when the transport is modal.
        try:
            from services.provider_probe import get_cached_management

            management = get_cached_management(provider_id)
        except Exception:
            management = None
        telemetry.update(
            {
                "status": poller_status.get("status"),
                "last_seen_at": poller_status.get("last_seen_at"),
                "missed_probes": poller_status.get("missed_probes", 0),
                "components": telemetry.get("components"),
                "history": {"vram": telemetry_service.get_vram_history(provider_id)},
                "lifecycle": lifecycle,
                "management": management,
                "transport": transport,
            }
        )

        diagnostics["telemetry"] = telemetry

        return {
            "provider_id": provider_id,
            "provider_type": provider_info.get("type"),
            "runtime": {
                **(provider_info.get("runtime_state") or {}),
                "enabled": provider_info.get("enabled", True),
                "backend_url": get_worker_backend_url(),
                "worker_url": runtime.worker_url,
                "mode": runtime.mode,
                "status": runtime.status,
                "connected": runtime.connected,
                "capabilities": provider_info.get("capabilities") or {},
                "telemetry": telemetry,
            },
            "model_sync": model_sync,
            "storage": redact_secrets(storage_stats),
            "reconciliation": redact_secrets(reconciliation_state),
            "deploy": redact_secrets(deploy_state),
            "diagnostics": diagnostics,
        }

    def build_provider_status_card_fallback(
        self,
        provider_info: dict[str, Any],
        *,
        error: str = "Failed to build provider status card",
    ) -> dict[str, Any]:
        """Return a stable fallback status card when live assembly fails."""
        provider_id = provider_info.get("id")
        runtime_state = provider_info.get("runtime_state") or {}
        error = redact_secrets(error)
        return {
            "provider_id": provider_id,
            "provider_type": provider_info.get("type"),
            "runtime": runtime_state,
            "model_sync": {
                "provider_id": provider_id,
                "total_models": 0,
                "stats": _empty_sync_stats(),
                "catalog_models": None,
                "has_install_intent": False,
                "is_image_provider": True,
            },
            "storage": self.empty_storage_payload(provider_id, error),
            "reconciliation": self.normalize_reconciliation_for_card(
                provider_info.get("reconciliation_state") or {}
            ),
            "deploy": redact_secrets(provider_info.get("deploy_state") or {"status": "idle"}),
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
        provider_payload: dict[str, Any] | None = None,
        provider: Any | None = None,
    ) -> dict[str, Any]:
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
            "worker_type": base_payload.get("worker_type"),
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
            # The DB column the load balancer's `serves()` reads, under its own
            # name. `capabilities` above is the UI action map; this list is what
            # answers "which task types will this provider be offered", and it
            # was the half that no code path could write or read.
            "declared_capabilities": base_payload.get("declared_capabilities") or [],
            "capability_reasons": base_payload.get("capability_reasons", {}),
            # Whether a worker token exists, never the token itself. Lets the UI
            # show "external worker configured" and offer rotate/revoke without
            # ever reading the credential back.
            "has_worker_token": base_payload.get("has_worker_token", False),
            "diagnostics": status_card.get("diagnostics", {}),
            "credential_summary": base_payload.get("credential_summary", {}),
        }

    async def build_provider_records(
        self,
        providers: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build canonical provider records for a list response.

        Concurrent, and order-preserving. This was a serial `for` loop, so
        `GET /api/v2/providers/` paid the sum of every provider's latency rather
        than the slowest one — and each record resolves a runtime target, which
        probes the Docker socket. With the snapshot cache the probes are cheap, but
        the per-provider model/sync/reconciliation calls are network round trips to
        the provider itself and were strictly serialised for no reason.

        `asyncio.gather` is used rather than a TaskGroup because each record is
        independently guarded: one provider failing must not cancel the others,
        and the per-provider `except` below already decides that. Order is restored
        explicitly because gather preserves input order only for homogeneous
        awaitables, and the mixed record/fallback results are appended in
        completion order otherwise.
        """
        providers = providers if providers is not None else await self.provider_service.list_providers()

        async def _build(provider: dict[str, Any], provider_id: str) -> dict[str, Any]:
            try:
                return await self.build_provider_record(
                    provider_id,
                    provider_payload=provider,
                )
            except Exception as exc:
                logger.warning("provider_record_failed", provider_id=provider_id, error=str(exc))
                return self.build_provider_status_card_fallback(provider, error=str(exc))

        buildable = [(p, p["id"]) for p in providers if p.get("id")]
        if not buildable:
            return []
        return list(await asyncio.gather(*(_build(p, pid) for p, pid in buildable)))

    async def build_provider_status_cards(
        self,
        providers: list[dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Build canonical provider status cards for all providers.

        Concurrent. This was the serial `for` loop that
        `build_provider_records` above carries a sixteen-line docstring about
        having replaced: it paid the SUM of every provider's latency where the
        slowest one would do, and each card resolves a runtime target, which
        probes the Docker socket. It is live — `api/routes/providers/lifecycle.py`
        calls it — so the page was still paying the serial sum after the records
        path stopped.

        Same shape and the same reasoning as `build_provider_records`: gather,
        per-provider exception isolation, and the results are re-keyed rather
        than appended, so completion order cannot affect the output.
        """
        providers = providers if providers is not None else await self.provider_service.list_providers()

        async def _build(provider: dict[str, Any], provider_id: str) -> tuple[str, dict[str, Any]]:
            try:
                return provider_id, await self.build_provider_status_card(
                    provider_id,
                    provider_payload=provider,
                )
            except Exception as exc:
                logger.warning("provider_status_card_failed", provider_id=provider_id, error=str(exc))
                return provider_id, self.build_provider_status_card_fallback(provider)

        buildable = [(p, p["id"]) for p in providers if p.get("id")]
        if not buildable:
            return {}
        return dict(await asyncio.gather(*(_build(p, pid) for p, pid in buildable)))
