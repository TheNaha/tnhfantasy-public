# Provider lifecycle routes: status, metrics, model management, setup, sync.
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from api.deps import (
    get_model_repo_v2,
    get_model_service_v2,
    get_provider_lifecycle_service,
    get_provider_service,
    get_provider_status_service,
    get_session,
)
from core.exceptions import ComfyError, NotFoundError, ProviderError, ValidationError
from infrastructure.http_client import get_http_client
from infrastructure.logging import api_logger
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2
from infrastructure.repositories.provider_repo import ProviderRepository
from services.credential_crypto import (
    CredentialDecryptionError,
    credential_presence,
    decrypt_credentials,
    encrypt_credentials,
    encryption_status,
)
from services.model_service import ModelServiceV2
from services.provider_deploy import (
    DEPLOY_TARGETS,
    DeployError,
    list_targets,
    repo_root,
    run_deploy,
)
from services.provider_lifecycle_service import ProviderLifecycleService
from services.provider_service import ProviderService
from services.provider_status_service import (
    ProviderStatusService,
    invalidate_provider_status_caches,
)

from .crud import AddCustomProviderModelRequest

logger = api_logger()


router = APIRouter()


def _invalidate_provider_runtime_caches(provider_id: str | None = None) -> None:
    """Clear route-level and provider-status caches after runtime changes."""
    invalidate_provider_status_caches(provider_id)


@router.get("/status-cards")
async def get_provider_status_cards(
    service: ProviderService = Depends(get_provider_service),
    status_service: ProviderStatusService = Depends(get_provider_status_service)
):
    """Return canonical provider status payloads for all configured providers."""
    providers = await service.list_providers()
    cards = await status_service.build_provider_status_cards(providers)

    return {
        "status_cards": cards,
        "count": len(cards),
    }


@router.get("/{provider_id}/status-card")
async def get_provider_status_card(
    provider_id: str,
    status_service: ProviderStatusService = Depends(get_provider_status_service)
):
    """Return canonical provider status payload for a single provider."""
    return await status_service.build_provider_status_card(provider_id)


@router.get("/{provider_id}/live-metrics")
async def get_provider_live_metrics(
    provider_id: str,
    service: ProviderService = Depends(get_provider_service)
):
    """Fetch live metrics from the provider's in-process engine."""
    import time

    from services.provider_runtime import resolve_provider_runtime_async

    provider = await service.get_provider(provider_id)
    runtime = await resolve_provider_runtime_async(provider)

    if runtime.mode == "in_process":
        from services.engines.engine_factory import get_engine
        engine = get_engine(provider_id, provider)
        if engine is None:
            return {"status": "offline", "latency_ms": 0, "error": "No in-process engine available"}
        try:
            start_t = time.time()
            health = await engine.check_health()
            latency = int((time.time() - start_t) * 1000)
            info = {
                "provider_id": provider_id,
                "engine": getattr(engine, "__class__", {}).__name__ or "in_process",
                "healthy": bool(health.get("ready") or health.get("status") == "healthy"),
            }
            return {
                "status": "online" if info["healthy"] else "degraded",
                "latency_ms": latency,
                "info": info,
            }
        except Exception as exc:
            return {
                "status": "offline",
                "latency_ms": 0,
                "error": str(exc),
            }

    if not runtime.worker_url:
        return {"status": "offline", "latency_ms": 0, "error": "No worker URL configured"}

    try:
        http_client = get_http_client()
        start_t = time.time()
        res = await http_client.get(f"{runtime.worker_url}/info", timeout=5.0)
        res.raise_for_status()
        latency = int((time.time() - start_t) * 1000)
        info_data = res.json()

        return {
            "status": "online",
            "latency_ms": latency,
            "info": info_data,
        }
    except Exception as exc:
        return {
            "status": "offline",
            "latency_ms": 0,
            "error": str(exc),
        }


@router.get("/{provider_id}/modal-stats")
async def get_provider_modal_stats(
    provider_id: str,
    service: ProviderService = Depends(get_provider_service),
    status_service: ProviderStatusService = Depends(get_provider_status_service)
):
    """
    Get model counts directly from provider storage via the in-process engine.
    Cached for 30 seconds to reduce load.
    Works with both Modal and Beam providers.
    """
    # Get provider to verify it exists
    provider = await service.get_provider(provider_id)
    return await status_service.get_provider_storage_stats(provider_id, provider)


@router.get("/{provider_id}/sync-status")
async def get_provider_sync_status(
    provider_id: str,
    status_service: ProviderStatusService = Depends(get_provider_status_service)
):
    """Return V2-backed sync counts for a provider."""
    return await status_service.get_provider_sync_status(provider_id)


@router.get("/{provider_id}/models")
async def get_provider_models(
    provider_id: str,
    status: str | None = None,
    status_service: ProviderStatusService = Depends(get_provider_status_service)
):
    """Return provider models grouped by directory using the V2 schema."""
    sync_status = await get_provider_sync_status(provider_id, status_service)
    grouped: dict[str, list[dict[str, Any]]] = {}

    for model in sync_status["models"]:
        model_status = model["provider_status"]["status"]
        if status and model_status != status:
            continue
        grouped.setdefault(model["directory"], []).append(model)

    return {
        "provider": provider_id,
        "models": grouped,
    }


@router.delete("/{provider_id}/models")
async def remove_model_from_provider(
    provider_id: str,
    directory: str,
    filename: str,
    service: ModelServiceV2 = Depends(get_model_service_v2),
    provider_service: ProviderService = Depends(get_provider_service)
):
    """Delete a model file from one provider and mark it pending again in V2."""
    normalized_directory = directory.replace("models/", "", 1)
    file = service.repo.get_file_by_storage_path(normalized_directory, filename)
    if not file:
        raise NotFoundError("Resource", "Model file not found")

    provider = await provider_service.get_provider(provider_id)

    storage_path = f"models/{normalized_directory}/{filename}"

    from services.provider_runtime import resolve_provider_runtime_async
    runtime = await resolve_provider_runtime_async(provider)
    if getattr(runtime, "mode", "") == "in_process":
        from services.engines.engine_factory import get_engine

        engine = get_engine(provider_id, provider)
        if engine is None:
            logger.warning("provider_model_delete_no_engine", provider_id=provider_id, path=storage_path)
        else:
            try:
                deleted = await engine.delete_file(storage_path)
                if not deleted:
                    logger.warning("provider_model_delete_not_confirmed", provider_id=provider_id, path=storage_path)
                for suffix in (".json", ".preview.png", ".sha256"):
                    try:
                        await engine.delete_file(storage_path + suffix)
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("provider_model_delete_failed", provider_id=provider_id, path=storage_path, error=str(exc))
    else:
        logger.warning(
            "provider_model_delete_no_engine",
            provider_id=provider_id,
            path=storage_path,
            mode=getattr(runtime, "mode", ""),
        )

    await asyncio.to_thread(
        service.update_provider_file_status,
        file_id=file.id,
        provider_id=provider_id,
        status="pending",
        storage_path=storage_path,
        size_bytes=None,
        error_message=None,
    )

    try:
        from services.load_balancer import LoadBalancer

        LoadBalancer.invalidate_model_availability_cache(provider_id=provider_id)
    except Exception as exc:
        logger.debug("availability_cache_invalidate_failed", error=str(exc))

    return {
        "status": "success",
        "provider_id": provider_id,
        "directory": f"models/{normalized_directory}",
        "filename": filename,
    }


@router.post("/models/custom")
async def add_custom_model_to_providers(
    request: AddCustomProviderModelRequest,
    service: ModelServiceV2 = Depends(get_model_service_v2)
):
    """Create a V2 custom model entry and trigger downloads for the selected providers."""
    model_name = request.model_data.get("name", "").strip()
    model_url = request.model_data.get("url", "").strip()
    model_type = request.model_data.get("type")

    if not model_name or not model_url:
        raise ValidationError("Model name and URL are required")

    result = await service.add_custom_model(
        name=model_name,
        directory=request.directory,
        download_url=model_url,
        provider_ids=request.provider_ids,
        model_type=model_type,
    )
    return {
        "status": "success",
        "model": result,
        "provider_ids": request.provider_ids,
    }



# ============================================================================
# PROVIDER SETUP ENDPOINT
# ============================================================================


@router.post("/{provider_id}/models/sync")
async def trigger_provider_sync(
    provider_id: str,
    lifecycle: ProviderLifecycleService = Depends(get_provider_lifecycle_service)
):
    """Trigger a reconciliation sync for a provider."""
    return await lifecycle.sync_provider_models(provider_id)


@router.post("/{provider_id}/setup")
async def setup_provider(
    provider_id: str,
    lifecycle: ProviderLifecycleService = Depends(get_provider_lifecycle_service)
):
    """Run the engine's setup_models to initialize remote storage."""
    try:
        return await lifecycle.setup_provider(provider_id)
    except ProviderError as exc:
        detail = str(exc)
        raise ComfyError(detail) from exc
    except ValueError as exc:
        raise ComfyError(f"Failed to run provider setup: {exc!s}") from exc


# ============================================================================
# CREDENTIALS — write-only by construction
# ============================================================================
#
# These routes are the only way a credential enters the database now that the
# Providers UI manages them, and they are shaped so that reading one back is not
# merely discouraged but not implemented:
#
#   * `PUT`  merges and encrypts. The response carries no value, ever.
#   * `DELETE /{key}` clears one key, addressed by name.
#   * `GET`   returns PRESENCE and a masked hint — which keys are set, never
#             what they are. `credential_presence` has no code path that emits a
#             secret, so there is nothing to get wrong here.
#
# There is deliberately no "set to empty string" path: an empty credential reads
# as absent to every engine (`can_create_engine` tests truthiness), so clearing a
# key is the only honest way to remove it and a blank field must not silently
# mean "keep the old value" either.
#
# `provider_service` already refuses to serialize `credentials` (see
# `_provider_to_dict`), and `tests/test_provider_credentials.py` asserts that
# end-to-end through the real routes. These routes are the other half of that
# guarantee: they exist so the credential never needs to be read back.


class SetProviderCredentialsRequest(BaseModel):
    """A partial credential update. Omitted keys are left untouched."""

    credentials: dict[str, Any] = Field(
        default_factory=dict,
        description="Key/value pairs to merge into the provider's credential bag",
    )
    #: Replace rather than merge. Needed when a key is being REMOVED by omission,
    #: which merge cannot express.
    replace: bool = Field(
        default=False,
        description="Replace the whole bag instead of merging into it",
    )


@router.get("/{provider_id}/credentials")
def get_provider_credentials(
    # Plain `def`, not `async def`: nothing here awaits, and Fernet
    # decryption plus a session commit are blocking work. An `async def`
    # that never awaits runs on the event loop instead of FastAPI's
    # threadpool, so decrypting a credential would stall every other
    # request. `test_event_loop_invariant.py` enforces this.
    provider_id: str,
    session: Session = Depends(get_session),
):
    """Which credentials are set, and a masked hint for each. Never the values.

    Masking rather than omitting is a judgement call: four characters either side
    of the middle is enough for the owner to confirm "yes, that is the token I
    pasted" and useless to anyone who obtains the response. Omitting entirely
    would leave the UI unable to tell "not set" from "set to something I can't
    see", which is the ambiguity that makes people re-paste tokens.
    """
    repo = ProviderRepository(session)
    row = repo.get_raw(provider_id)
    if row is None:
        raise NotFoundError("Provider", provider_id)

    try:
        presence = credential_presence(row.credentials)
    except CredentialDecryptionError as exc:
        # Not a 500. The row exists and holds secrets; we simply cannot read
        # them, and the operator needs to be told that in words.
        raise ComfyError(str(exc)) from exc

    return {
        "provider_id": provider_id,
        "credentials": presence,
        "encryption": encryption_status(),
    }


@router.put("/{provider_id}/credentials")
def set_provider_credentials(
    # Plain `def`, not `async def`: nothing here awaits, and Fernet
    # decryption plus a session commit are blocking work. An `async def`
    # that never awaits runs on the event loop instead of FastAPI's
    # threadpool, so decrypting a credential would stall every other
    # request. `test_event_loop_invariant.py` enforces this.
    provider_id: str,
    request: SetProviderCredentialsRequest,
    session: Session = Depends(get_session),
):
    """Merge (or replace) credential values. Write-only.

    An empty-string value is rejected rather than stored: every engine reads a
    credential with a truthiness test, so an empty string is indistinguishable
    from an absent key and storing it would make the provider look configured
    while dispatching unauthenticated. Clear the key instead.
    """
    if not request.credentials and not request.replace:
        raise ValidationError("no credentials supplied")

    blanks = [k for k, v in request.credentials.items() if v == ""]
    if blanks:
        raise ValidationError(
            f"{', '.join(sorted(blanks))} submitted as an empty string. An empty "
            f"credential reads as absent, so this would silently leave the "
            f"provider unauthenticated — DELETE the key to remove it."
        )

    repo = ProviderRepository(session)
    raw = repo.get_raw(provider_id)
    if raw is None:
        raise NotFoundError("Provider", provider_id)

    try:
        existing = decrypt_credentials(raw.credentials)
    except CredentialDecryptionError as exc:
        raise ComfyError(str(exc)) from exc

    merged = (
        dict(request.credentials)
        if request.replace
        else {**existing, **request.credentials}
    )

    repo.update(provider_id, {"credentials": merged})
    _invalidate_provider_runtime_caches(provider_id)

    logger.info(
        "provider_credentials_updated",
        provider_id=provider_id,
        keys=sorted(request.credentials),
        replaced=request.replace,
        encrypted=encryption_status()["enabled"],
    )

    # Presence only. Deliberately recomputed rather than echoed from the request,
    # so a key the schema stripped cannot come back out through the response.
    return {
        "provider_id": provider_id,
        "credentials": credential_presence(
            encrypt_credentials(merged) if encryption_status()["enabled"] else merged
        ),
        "encryption": encryption_status(),
    }


@router.delete("/{provider_id}/credentials/{key}")
def delete_provider_credential(
    # Plain `def`, not `async def`: nothing here awaits, and Fernet
    # decryption plus a session commit are blocking work. An `async def`
    # that never awaits runs on the event loop instead of FastAPI's
    # threadpool, so decrypting a credential would stall every other
    # request. `test_event_loop_invariant.py` enforces this.
    provider_id: str,
    key: str,
    session: Session = Depends(get_session),
):
    """Remove one credential by name. Its presence, not its value, is all that leaks."""
    repo = ProviderRepository(session)
    raw = repo.get_raw(provider_id)
    if raw is None:
        raise NotFoundError("Provider", provider_id)

    try:
        existing = decrypt_credentials(raw.credentials)
    except CredentialDecryptionError as exc:
        raise ComfyError(str(exc)) from exc

    if key not in existing:
        raise NotFoundError(
            f"provider '{provider_id}' credential", key
        )

    existing.pop(key)
    repo.update(provider_id, {"credentials": existing})
    _invalidate_provider_runtime_caches(provider_id)
    logger.info("provider_credential_cleared", provider_id=provider_id, key=key)

    return {
        "provider_id": provider_id,
        "credentials": credential_presence(
            encrypt_credentials(existing) if encryption_status()["enabled"] else existing
        ),
        "encryption": encryption_status(),
    }



# ============================================================================
# PROVIDER STATUS CLEANUP
# ============================================================================


@router.post("/cleanup-orphaned-statuses")
async def cleanup_orphaned_provider_statuses(
    service: ProviderService = Depends(get_provider_service),
    model_repo: ModelRepositoryV2 = Depends(get_model_repo_v2)
):
    """
    Clean up ProviderVersionStatus records for providers that no longer exist.
    This fixes the desync between model status indicators and actual provider list.

    Should be run once after deleting providers to clean up orphaned status entries
    from before the cascade delete feature was added.
    """
    # Get list of active provider IDs
    providers = await service.list_providers()
    active_provider_ids = [p["id"] for p in providers]

    # Clean up orphaned statuses
    result = model_repo.cleanup_orphaned_provider_statuses(active_provider_ids)
    stale_reset_count = model_repo.reset_stale_downloading_statuses(
        stale_before=datetime.now(timezone.utc) - timedelta(minutes=120),
        provider_names=active_provider_ids,
    )
    _invalidate_provider_runtime_caches()

    return {
        "status": "success",
        "message": f"Cleaned up {result['deleted_count']} orphaned status entries and reset {stale_reset_count} stale downloads",
        "deleted_count": result["deleted_count"],
        "orphaned_providers": result["orphaned_providers"],
        "active_providers": active_provider_ids,
        "orphaned_statuses_removed": result["deleted_count"],
        "stale_downloading_reset": stale_reset_count,
        "affected_provider_ids": sorted(set(active_provider_ids + result["orphaned_providers"])),
    }


@router.post("/state/cleanup")
async def cleanup_provider_state(
    service: ProviderService = Depends(get_provider_service),
    model_repo: ModelRepositoryV2 = Depends(get_model_repo_v2)
):
    """Explicit maintenance action for provider state hygiene."""
    return await cleanup_orphaned_provider_statuses(service, model_repo)


# ============================================================================
# DEPLOY
# ============================================================================
#
# This is the route `scripts/deploy.sh`'s header says does not exist. It does
# now, deliberately, and the reasoning that argued against it is preserved in
# `services/provider_deploy.py` rather than deleted: it still does not stream a
# build, it still runs the same script, and the output is capped.
#
# The honest characterisation of the change is that this converts "the API is
# open to the network perimeter" into "the API can run the vendor CLI". That is
# a real widening, chosen over leaving the only way to ship a deployable fix
# off-box. The mitigations are structural rather than a flag: the target is an
# allowlist key, the command is an argv list with no shell, the script path is
# resolved server-side, the child's environment is rebuilt from scratch rather
# than inherited, and one deploy runs at a time.


class DeployRequest(BaseModel):
    target: str = Field(
        description="One of: image, tts, llm, beam, all"
    )
    dry_run: bool = Field(
        default=False,
        description="Resolve and print what would be deployed without deploying",
    )
    provider_id: str | None = Field(
        default=None,
        description=(
            "Which provider row's credentials to authenticate with. Defaults to "
            "the highest-priority enabled provider for the target's transport."
        ),
    )
    timeout: float | None = Field(
        default=None, description="Seconds before the deploy is terminated",
    )
    stream: bool = Field(
        default=False, description="Stream deploy output line-by-line as NDJSON",
    )


@router.get("/deploy/targets")
def list_deploy_targets():
    """What can be deployed from this process, and whether the script is present.

    Plain `def`: nothing awaits, and filesystem probing is blocking work.
    """
    return {"targets": list_targets(), "repo_root": str(repo_root() or "")}


@router.post("/deploy")
async def deploy_provider_target(
    request: DeployRequest,
    service: ProviderService = Depends(get_provider_service),
    session: Session = Depends(get_session),
):
    """Deploy a cloud worker. Requires the vendor CLI on THIS host.

    A 4xx from here is a configuration problem — no script, unknown target, no
    provider whose credentials match the transport. A failure inside the vendor
    CLI comes back as `ok: false` with the script's output attached, because a
    non-zero exit from `deploy.sh` is a real answer about the deploy and turning
    it into a generic HTTP error throws away the only useful part.
    """
    if request.target not in DEPLOY_TARGETS:
        raise ValidationError(
            f"unknown deploy target {request.target!r}. Valid targets: "
            f"{', '.join(sorted(DEPLOY_TARGETS))}"
        )

    transport = DEPLOY_TARGETS[request.target]["transport"]
    repo = ProviderRepository(session)

    provider = None
    if request.provider_id:
        provider = repo.get_raw(request.provider_id)
        if provider is None:
            raise NotFoundError("Provider", request.provider_id)
        if not _transport_matches(provider.type, transport):
            raise ValidationError(
                f"provider {request.provider_id!r} is type {provider.type!r}, which "
                f"cannot authenticate a {transport!r} deploy. Pick a "
                f"{transport} provider, or name one explicitly if the two happen "
                f"to share credentials."
            )
    else:
        # No explicit row: take the highest-priority enabled one whose transport
        # matches, because deploying `beam` with Modal credentials fails inside
        # the CLI rather than here. `all` accepts either.
        wanted = None if transport == "modal+beam" else transport
        for candidate in sorted(
            repo.get_enabled(), key=lambda p: (p.priority, p.id)
        ):
            if wanted is None or _transport_matches(candidate.type, wanted):
                provider = repo.get_raw(candidate.id)
                break

    chosen_provider_id = provider.id if provider is not None else request.provider_id
    resolved_creds: dict[str, Any] = {}

    if chosen_provider_id:
        from services.engines.engine_factory import get_provider_env
        try:
            resolved_creds.update(get_provider_env(chosen_provider_id))
        except Exception as exc:
            logger.warning("deploy_get_provider_env_failed", provider_id=chosen_provider_id, error=str(exc))

    if provider is not None and provider.credentials:
        try:
            db_creds = decrypt_credentials(provider.credentials)
            if db_creds:
                resolved_creds.update(db_creds)
        except CredentialDecryptionError as exc:
            raise ComfyError(str(exc)) from exc

    credentials = resolved_creds if resolved_creds else None

    if request.stream:
        from fastapi.responses import StreamingResponse
        from services.provider_deploy import stream_deploy

        if chosen_provider_id:
            _invalidate_provider_runtime_caches(chosen_provider_id)

        generator = stream_deploy(
            request.target,
            dry_run=request.dry_run,
            credentials=credentials,
            timeout=request.timeout,
            provider_id=chosen_provider_id,
        )
        return StreamingResponse(
            generator,
            media_type="application/x-ndjson",
            headers={
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache",
            },
        )

    try:
        result = await run_deploy(
            request.target,
            dry_run=request.dry_run,
            credentials=credentials,
            timeout=request.timeout,
            provider_id=chosen_provider_id,
        )
        if chosen_provider_id:
            _invalidate_provider_runtime_caches(chosen_provider_id)
        return result
    except DeployError as exc:
        raise ComfyError(str(exc)) from exc


@router.get("/{provider_id}/logs")
async def get_provider_logs(
    provider_id: str,
    session: Session = Depends(get_session),
    status_service: ProviderStatusService = Depends(get_provider_status_service),
):
    """Activity and diagnostic logs for a provider: latest deploy, recent job errors, and diagnostics."""
    repo = ProviderRepository(session)
    provider = repo.get(provider_id)
    if not provider:
        raise NotFoundError("Provider", provider_id)

    from services.provider_deploy import get_last_deploy, get_active_deploy
    from core.entities import Job, JobStatus
    from sqlmodel import select, desc

    deploy_log = get_last_deploy(provider_id=provider_id)
    if not deploy_log and provider.type:
        # Fall back to target-based deploy log if any matches this provider's category
        target = "tts" if "tts" in provider.type else "llm" if "llm" in provider.type else "beam" if "beam" in provider.type else "image"
        deploy_log = get_last_deploy(target=target)

    active_deploy = get_active_deploy(provider_id=provider_id)
    if not active_deploy and provider.type:
        active_deploy = get_active_deploy()

    # Fetch recent job failures for this provider
    try:
        stmt = (
            select(Job)
            .where(Job.provider_id == provider_id)
            .where(Job.status == JobStatus.FAILED)
            .order_by(desc(Job.created_at))
            .limit(10)
        )
        failed_jobs = session.exec(stmt).all()
        recent_failures = [
            {
                "id": j.id,
                "task_type": j.task_type,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "error": j.error,
                "message": j.message,
            }
            for j in failed_jobs
        ]
    except Exception as exc:
        logger.warning("get_provider_logs_failed_jobs_query_error", provider_id=provider_id, error=str(exc))
        recent_failures = []

    # Fetch recent jobs (both completed and failed) with performance & timing diagnostics
    recent_jobs = []
    try:
        stmt_all = (
            select(Job)
            .where(Job.provider_id == provider_id)
            .order_by(desc(Job.created_at))
            .limit(10)
        )
        jobs = session.exec(stmt_all).all()
        for j in jobs:
            diag = (j.metadata_ or {}).get("diagnostics", {}) if isinstance(j.metadata_, dict) else {}
            timings = diag.get("timings")
            duration_s = None
            if j.completed_at and j.created_at:
                duration_s = round((j.completed_at - j.created_at).total_seconds(), 2)
            recent_jobs.append({
                "id": j.id,
                "task_type": j.task_type,
                "status": j.status.value if hasattr(j.status, "value") else str(j.status),
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "duration_seconds": duration_s,
                "timings": timings,
                "error": j.error,
                "message": j.message,
            })
    except Exception as exc:
        logger.warning("get_provider_logs_recent_jobs_query_error", provider_id=provider_id, error=str(exc))
        recent_jobs = []

    # Get status card for diagnostics & connectivity summary
    status_card = await status_service.build_provider_status_card(provider_id, provider=provider)

    return {
        "provider_id": provider_id,
        "deploy": deploy_log,
        "active_deploy": active_deploy,
        "recent_failures": recent_failures,
        "recent_jobs": recent_jobs,
        "diagnostics": status_card.get("diagnostics", {}),
        "runtime": status_card.get("runtime", {}),
        "reconciliation": status_card.get("reconciliation", {}),
    }


@router.post("/{provider_id}/free-vram")
async def free_provider_vram(
    provider_id: str,
    service: ProviderService = Depends(get_provider_service),
):
    """Purge GPU VRAM and reset model caching on remote worker engine."""
    provider = await service.get_provider(provider_id)
    if not provider:
        raise NotFoundError("Provider", provider_id)

    from services.engines.engine_factory import get_engine, can_create_engine
    if not can_create_engine(provider):
        raise ValidationError(f"Provider {provider_id} cannot run in-process engine")

    engine = get_engine(provider_id, provider)
    if not engine:
        raise NotFoundError(f"Engine for provider {provider_id} could not be initialized")

    if not hasattr(engine, "free_vram"):
        raise ValidationError(f"Engine {engine.__class__.__name__} does not support free_vram")

    try:
        success = await engine.free_vram()
        _invalidate_provider_runtime_caches(provider_id)
        return {
            "status": "success",
            "provider_id": provider_id,
            "freed": bool(success),
            "message": "GPU VRAM successfully purged and models unloaded",
        }
    except Exception as exc:
        logger.warning("provider_free_vram_failed", provider_id=provider_id, error=str(exc))
        raise ComfyError(f"Failed to free GPU VRAM: {exc!s}") from exc



def _transport_matches(provider_type: str | None, transport: str) -> bool:
    """Does a provider type authenticate against this deploy transport?

    By prefix, not by enumeration: `registry.ENGINE_SPECS` is the list of types
    and it grows. `modal`, `modal_llm`, `modal_tts` all carry a Modal token;
    `beam`, `beam_llm`, `beam_tts` all carry a Beam key. An unknown type matches
    nothing, which makes a newly added transport fail loudly here rather than
    silently deploying with the wrong credentials.
    """
    name = str(provider_type or "")
    return transport == "modal" and name.startswith("modal") or (
        transport == "beam" and name.startswith("beam")
    )
