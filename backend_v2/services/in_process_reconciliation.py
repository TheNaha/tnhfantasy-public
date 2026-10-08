"""In-process model reconciliation runner.

Parity port of `provider_core.reconciliation.run_reconciliation_v2` for
providers whose engine runs inside backend_v2 instead of a sidecar
container. The container worker pulls its inputs over HTTP
(`pending-downloads`, `all-storage-paths`, `batch-status-update`,
`reconciliation-event`) and pushes progress back the same way; here the
backend IS the backend, so the same steps run against the services and
repository directly, with WebSocket fan-out through the in-process event
bus.

Step mapping to the container flow:
  0. validate existing models (skipped on quick sync)
  1. pending downloads + expected paths from the DB
  2. list existing files on provider storage via the engine
  3. mark missing as pending, already-present as ready
  4. download the rest under a semaphore, updating statuses per file
  5. orphan handling: register-then-optionally-delete, with the same
     two-consecutive-sightings stability filter and 20%-or-20 size guard
"""

import asyncio
import os
from typing import Any, Optional

from infrastructure.logging import get_logger
from services.engines.base import EngineAuthError, MODEL_DIRECTORIES

logger = get_logger("in_process_reconciliation")

# One reconciliation per provider. The worker tracks this in its
# ReconciliationState; in-process it is a module-level guard because there
# is no worker process to hold it.
_RUNNING: set[str] = set()
# Strong refs for spawned reconciliation tasks. A bare create_task result is
# only weakly held by the loop: a multi-GB download task was once collected
# mid-run (provider_core/background.py documents exactly this), so the task
# lives here until its done-callback fires.
_RECONCILE_TASKS: set["asyncio.Task"] = set()

# Orphan paths seen by the previous reconciliation per provider. Only a path
# reported orphaned by two consecutive runs is deletable, so a mis-scoped
# listing (wrong prefix, empty page, somebody else's volume) cannot arm a
# mass delete in a single tick. Same rule as the container flow.
_PREVIOUS_ORPHANS: dict[str, set[str]] = {}

# Bulk status-write chunk: mirrors the container's 500-row
# batch-status-update batches (provider_core/reconciliation.py). One giant
# loop holds a DB thread for the whole catalogue on large fleets.
_BULK_WRITE_CHUNK = 500


def _delete_orphans_enabled() -> bool:
    return os.getenv("RECONCILIATION_DELETE_ORPHANS", "false").strip().lower() in ("true", "1", "yes")


def _max_concurrent_downloads(provider: Any = None) -> int:
    config = getattr(provider, "config", None) or {}
    for key in ("max_concurrent_downloads",):
        try:
            value = int(config.get(key) or os.getenv("MAX_CONCURRENT_DOWNLOADS", "") or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    # Same default the container image workers reconciled under
    # (`MAX_CONCURRENT_DOWNLOADS=5` in image_worker/worker.py; the base
    # default of 2 never applied to them). Explicit per-provider
    # `max_concurrent_downloads` or MAX_CONCURRENT_DOWNLOADS wins.
    return 5


def _safe_deletion_limit(total_files: int, orphaned_count: int) -> int:
    """Mirror provider_core.reconciliation.calculate_safe_deletion_limit."""
    max_deletions = max(20, total_files // 5)
    if orphaned_count > max_deletions > 0:
        logger.warning(
            "in_process_reconcile_orphan_limit",
            orphans=orphaned_count,
            limit=max_deletions,
        )
        return max_deletions
    return orphaned_count


def is_reconciliation_running(provider_id: str) -> bool:
    return provider_id in _RUNNING


async def trigger_in_process_reconciliation(
    provider_id: str,
    *,
    provider: Any = None,
    engine: Any = None,
    quick_sync: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Start an in-process reconciliation for a provider (non-blocking).

    Returns immediately after spawning the background task, mirroring the
    container `POST /reconcile` answers (`started` / `already_running`).
    Engines without a model tree (LLM, TTS) finish synchronously with a
    `skipped` outcome instead of sitting at "reconciling" forever — the
    same vocabulary the lifecycle service already honours from workers.
    """
    from services.engines.engine_factory import get_engine

    if provider_id in _RUNNING:
        return {
            "status": "already_running",
            "provider_id": provider_id,
            "message": "Reconciliation already in progress",
        }

    resolved_engine = engine or get_engine(provider_id, provider)
    if resolved_engine is None:
        return {
            "status": "failed",
            "provider_id": provider_id,
            "message": "No in-process engine available for provider",
        }

    discovery_only = False
    if not getattr(resolved_engine, "manages_model_files", False):
        # Plain Direct ComfyUI has no mutation surface, but its /object_info
        # graph names every loadable model: register those as discovered
        # instead of skipping, like the legacy direct_url client did.
        if not getattr(resolved_engine, "supports_discovery_reconcile", False):
            return {
                "status": "skipped",
                "provider_id": provider_id,
                "message": "Provider has no model tree to reconcile",
            }
        discovery_only = True

    _RUNNING.add(provider_id)
    task = asyncio.create_task(
        _run_reconciliation(provider_id, resolved_engine, provider, quick_sync, force, discovery_only),
        name=f"in-process-reconcile:{provider_id}",
    )
    _RECONCILE_TASKS.add(task)

    def _done(_t: asyncio.Task) -> None:
        _RUNNING.discard(provider_id)
        _RECONCILE_TASKS.discard(_t)

    task.add_done_callback(_done)
    sync_mode = "Quick Sync" if quick_sync else "Full Reconciliation"
    return {
        "status": "started",
        "provider_id": provider_id,
        "message": f"In-process {sync_mode} started",
    }


async def _push_with_retry(provider_service: Any, provider_id: str, updates: dict[str, Any]) -> None:
    """Persist reconciliation state with container-parity retries.

    Mirrors provider_core push_reconciliation_event (3 attempts, 0.5s
    backoff): a transient DB hiccup mid-run must not lose the whole state.
    Raises on final failure so the run fails loudly instead of stalling.
    """
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            await asyncio.to_thread(
                provider_service.upsert_reconciliation_state, provider_id, updates
            )
            return
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(0.5)
    if last_exc is not None:
        raise last_exc


async def _run_reconciliation(
    provider_id: str,
    engine: Any,
    provider: Any,
    quick_sync: bool,
    force: bool,
    discovery_only: bool = False,
) -> None:
    from api import deps as api_deps
    from core.events import Event, EventType, emit_provider_stats
    from services.provider_service import ProviderService

    session = api_deps.get_session_sync()
    try:
        provider_service = api_deps.get_provider_service(session)
        model_service = api_deps.get_model_service_v2(session)
        event_bus = api_deps.get_event_bus()

        stats: dict[str, Any] = {
            "downloads_completed": 0,
            "downloads_failed": 0,
            "deletions_completed": 0,
            "invalid_cleaned": 0,
            "total_models": 0,
            "missing_reported": 0,
        }
        errors: list[str] = []
        current_download: Optional[dict[str, Any]] = None
        active_downloads: list[dict[str, Any]] = []

        async def push_state(
            status: str,
            phase: Optional[str] = None,
            message: Optional[str] = None,
        ) -> None:
            """Persist reconciliation state and fan out to WebSocket clients.

            Same payload the `POST /reconciliation-event` route builds from
            worker pushes, minus the HTTP round trip.
            """
            normalized = ProviderService.normalize_reconciliation_status(status)
            persistence_updates: dict[str, Any] = {
                "provider_id": provider_id,
                "status": normalized,
                "phase": phase,
                "current_download": current_download,
                "active_downloads": list(active_downloads),
                "errors": list(errors),
                "message": message,
                "last_contact_at": ProviderService._utcnow_iso(),
                "stats": dict(stats),
            }
            await _push_with_retry(
                provider_service, provider_id, persistence_updates
            )
            event_type = {
                "started": EventType.RECONCILIATION_STARTED,
                "reconciling": EventType.RECONCILIATION_PROGRESS,
                "progress": EventType.RECONCILIATION_PROGRESS,
                "completed": EventType.RECONCILIATION_COMPLETED,
                "failed": EventType.RECONCILIATION_FAILED,
            }.get(normalized, EventType.RECONCILIATION_PROGRESS)
            try:
                await event_bus.publish(
                    Event(type=event_type, data={**persistence_updates, "stats": dict(stats)})
                )
            except Exception as exc:
                # Event fan-out must never fail the run: the container
                # path's POST /reconciliation-event swallowed push
                # failures with retries, and reconciliation itself
                # succeeded regardless.
                logger.warning(
                    "in_process_reconcile_event_push_failed",
                    provider_id=provider_id,
                    error=str(exc),
                )
            if stats:
                try:
                    await emit_provider_stats(provider_id, dict(stats))
                except Exception as exc:
                    logger.warning(
                        "in_process_reconcile_stats_push_failed",
                        provider_id=provider_id,
                        error=str(exc),
                    )

        # The same session guard the container path takes before POSTing
        # /reconcile: a run already in flight answers already_running.
        session_state = await provider_service.start_reconciliation_session(provider_id, force=force)
        if not session_state.get("accepted"):
            await push_state("reconciling", phase="running", message=session_state.get("message"))
            return

        sync_mode = "Quick Sync" if quick_sync else "Full Reconciliation"
        logger.info("in_process_reconcile_start", provider_id=provider_id, mode=sync_mode)
        await push_state("reconciling", phase="starting", message=f"In-process {sync_mode} started")

        try:
            if not quick_sync:
                await push_state("reconciling", phase="validating", message="Checking for invalid or partial downloads...")
                try:
                    # Prefer the single-call probe (mirrors the container's
                    # /validate-all-models reconcile probe, which raised on
                    # non-200 instead of reporting a clean sweep).
                    validate_all = getattr(engine, "validate_all_models", None)
                    if callable(validate_all):
                        validation_result = await validate_all(MODEL_DIRECTORIES, True)
                    else:
                        try:
                            validation_result = await engine.validate_models(MODEL_DIRECTORIES, True)
                        except TypeError:
                            # Engines whose upstream has no delete-invalid switch
                            # validate read-only.
                            validation_result = await engine.validate_models(MODEL_DIRECTORIES)
                    if not isinstance(validation_result, dict):
                        validation_result = {"total_invalid": 0, "total_partial": 0}
                    invalid_count = int(validation_result.get("total_invalid", 0) or 0)
                    partial_count = int(validation_result.get("total_partial", 0) or 0)
                    stats["invalid_cleaned"] = invalid_count + partial_count
                except Exception as exc:
                    # Visible in reconciliation state, not just the server
                    # log: a failed validation step must not read as "all
                    # models valid" (the container's Modal twin logged a
                    # warning here too, but it was attached to the run).
                    errors.append(f"Validation step failed: {exc}")
                    logger.warning("in_process_reconcile_validate_failed", provider_id=provider_id, error=str(exc))

            await push_state("reconciling", phase="fetching", message="Querying pending downloads...")

            def _load_inputs() -> tuple[list[dict[str, Any]], set[str]]:
                pending = model_service.reconciliation.get_pending_downloads(provider_id)
                expected = set(model_service.repo.get_all_storage_paths())
                return pending, expected

            pending_downloads, all_expected_paths = await asyncio.to_thread(_load_inputs)
            logger.info(
                "in_process_reconcile_pending",
                provider_id=provider_id,
                pending=len(pending_downloads),
                expected=len(all_expected_paths),
            )

            await push_state("reconciling", phase="fetching", message="Checking existing files on provider storage...")

            list_errors: list[str] = []

            async def _fetch_dir(directory: str) -> tuple[str, list[dict[str, Any]]]:
                try:
                    try:
                        # Cold volumes need the reconcile budget (container
                        # _fetch_dir wait_for 3600s); engines default to the
                        # fast 60s UI budget otherwise.
                        return directory, await engine.list_models(directory, timeout=3600.0)
                    except TypeError:
                        return directory, await engine.list_models(directory)
                except EngineAuthError:
                    # A rejected credential must fail the run loudly (the
                    # container probes raised on 401); swallowing it reports
                    # a clean sweep for a provider we cannot even read.
                    raise
                except Exception as exc:
                    logger.warning(
                        "in_process_reconcile_list_failed",
                        provider_id=provider_id,
                        directory=directory,
                        error=str(exc),
                    )
                    list_errors.append(directory)
                    return directory, []

            try:
                listed = await asyncio.gather(*[_fetch_dir(d) for d in MODEL_DIRECTORIES])
            except EngineAuthError as exc:
                errors.append(f"Listing failed: {exc}")
                await push_state("failed", phase="failed", message=f"Reconciliation failed: {exc}")
                return
            if list_errors:
                # Any listing failure fails the run (parity with container
                # gather with no return_exceptions — one dir failure aborted
                # the whole listing into fatal → failed). Proceeding on a
                # partial listing marks every file in the failed dirs missing
                # and re-downloads the world.
                message = f"Storage listing failed for {len(list_errors)} directorie(s): {', '.join(sorted(list_errors)[:5])}"
                errors.append(message)
                await push_state("failed", phase="failed", message=f"Reconciliation failed: {message}")
                return
            existing_files_dict: dict[str, dict[str, Any]] = {}
            for directory, files in listed:
                for entry in files if isinstance(files, list) else []:
                    if not isinstance(entry, dict):
                        continue
                    name = entry.get("name") or os.path.basename(
                        entry.get("path") or entry.get("storage_path") or ""
                    )
                    if not name:
                        continue
                    existing_files_dict[f"{directory}/{name}"] = entry
            existing_files = set(existing_files_dict.keys())
            stats["total_models"] = len(existing_files)

            by_directory: dict[str, int] = {}
            for path in existing_files:
                parts = path.split("/")
                directory = "/".join(parts[:-1]) if len(parts) > 1 else "root"
                by_directory[directory] = by_directory.get(directory, 0) + 1
            # Legacy ReconciliationStats keys, kept so raw-stats consumers
            # (cards, status payloads) read the same shape from either path.
            stats["total_models_in_storage"] = len(existing_files)
            stats["by_directory"] = dict(by_directory)
            stats["downloads_queued"] = len(pending_downloads)

            def _bulk_mark_missing(paths: list[str]) -> None:
                # Resolve file_ids first: a None file_id would create a
                # garbage status row instead of updating the file's row (same
                # lookup the batch-status-update route performs).
                # Chunked like the container's 500-row batch-status-update
                # batches: one giant to_thread loop holds the DB for the
                # whole catalogue on large fleets.
                for offset in range(0, len(paths), _BULK_WRITE_CHUNK):
                    chunk = paths[offset:offset + _BULK_WRITE_CHUNK]
                    path_to_id = model_service.repo.get_file_ids_by_storage_paths(chunk)
                    for storage_path in chunk:
                        file_id = path_to_id.get(storage_path)
                        if file_id is None:
                            continue
                        model_service.repo.update_provider_status(
                            file_id=file_id,
                            provider_id=provider_id,
                            status="pending",
                            storage_path=storage_path,
                            force_create=True,
                        )

            missing_files = all_expected_paths - existing_files
            if missing_files and not discovery_only:
                # Discovery-only rigs (plain Direct, no mutation surface) must
                # never mark missing → pending: they cannot download, so those
                # rows would sit immortal-pending forever (parity with legacy
                # direct_url run_reconciliation register-discovered path).
                stats["missing_reported"] = len(missing_files)
                await asyncio.to_thread(_bulk_mark_missing, sorted(missing_files))
                if not quick_sync:
                    pending_downloads, _ = await asyncio.to_thread(
                        lambda: (model_service.reconciliation.get_pending_downloads(provider_id), None)
                    )
                    stats["downloads_queued"] = len(pending_downloads)

            def _bulk_mark_ready(items: list[dict[str, Any]]) -> None:
                for offset in range(0, len(items), _BULK_WRITE_CHUNK):
                    chunk = items[offset:offset + _BULK_WRITE_CHUNK]
                    paths = [i.get("storage_path") for i in chunk if i.get("file_id") is None and i.get("storage_path")]
                    path_to_id = model_service.repo.get_file_ids_by_storage_paths(paths) if paths else {}
                    for item in chunk:
                        file_id = item.get("file_id") or path_to_id.get(item.get("storage_path") or "")
                        if file_id is None:
                            continue
                        model_service.repo.update_provider_status(
                            file_id=file_id,
                            provider_id=provider_id,
                            status="ready",
                            storage_path=item.get("storage_path"),
                            size_bytes=item.get("size_bytes"),
                            force_create=True,
                        )

            downloads_needed: list[dict[str, Any]] = []
            already_ready: list[dict[str, Any]] = []
            for file_info in pending_downloads:
                storage_path = file_info.get("storage_path", "")
                if storage_path in existing_files:
                    already_ready.append(
                        {
                            "file_id": file_info["file_id"],
                            "status": "ready",
                            "storage_path": storage_path,
                        }
                    )
                else:
                    downloads_needed.append(file_info)

            if already_ready:
                await asyncio.to_thread(_bulk_mark_ready, already_ready)

            # Safety net: every expected file present on storage reads ready,
            # even without a status row (post-cleanup, provider id change).
            ready_paths = {item["storage_path"] for item in already_ready}
            statusless = [
                {"file_id": None, "status": "ready", "storage_path": path}
                for path in all_expected_paths
                if path in existing_files and path not in ready_paths
            ]
            if statusless:
                await asyncio.to_thread(_bulk_mark_ready, statusless)

            if discovery_only:
                # Parity with the legacy direct_url run_reconciliation
                # register-discovered path: loadable-but-unknown models are
                # imported into the catalogue instead of dropped. The listing
                # above already resolved the rig's loadables via /object_info.
                discovered = [
                    {
                        "path": path,
                        "size_bytes": (existing_files_dict.get(path) or {}).get("size", 0),
                    }
                    for path in sorted(existing_files)
                ]
                try:
                    await model_service.reconciliation.register_discovered_files(
                        provider_id, discovered
                    )
                except Exception as exc:
                    errors.append(f"Discovery registration failed: {exc}")
                    logger.warning(
                        "in_process_reconcile_discovery_register_failed",
                        provider_id=provider_id,
                        error=str(exc),
                    )
                    await push_state(
                        "failed",
                        phase="failed",
                        message=f"Discovery failed: {exc}",
                    )
                    return
                stats["files_discovered"] = len(discovered)
                await push_state(
                    "completed",
                    phase="completed",
                    message=f"Discovered and registered {len(discovered)} models from ComfyUI.",
                )
                return

            if quick_sync:
                await push_state("completed", phase="completed", message="Quick sync complete!")
                return

            token_for = getattr(engine, "download_token_for_url", None)
            semaphore = asyncio.Semaphore(max(1, _max_concurrent_downloads(provider)))
            total_downloads = len(downloads_needed)
            active_lock = asyncio.Lock()

            async def download_single(file_info: dict[str, Any], index: int) -> None:
                nonlocal current_download
                file_id = file_info["file_id"]
                display_name = f"{file_info.get('model_name', 'Unknown')} ({file_info.get('version_name', 'v1')})"
                storage_path = file_info["storage_path"]
                download_url = file_info["download_url"]
                download_info = {
                    "name": display_name,
                    "file_id": file_id,
                    "progress": 0.0,
                    "index": index + 1,
                    "total": total_downloads,
                }
                async with semaphore:
                    async with active_lock:
                        active_downloads.append(download_info)
                    current_download = download_info
                    await push_state("reconciling", phase="downloading", message=f"Downloading {display_name}...")
                    logger.info("in_process_reconcile_download_start", provider_id=provider_id, path=storage_path)

                    def _mark_downloading() -> None:
                        model_service.repo.update_provider_status(
                            file_id=file_id,
                            provider_id=provider_id,
                            status="downloading",
                            storage_path=storage_path,
                            force_create=True,
                        )

                    await asyncio.to_thread(_mark_downloading)
                    try:
                        token = token_for(download_url) if callable(token_for) else None
                        await engine.download_file(download_url, storage_path, token)
                        stats["downloads_completed"] += 1

                        def _mark_ready() -> None:
                            model_service.repo.update_provider_status(
                                file_id=file_id,
                                provider_id=provider_id,
                                status="ready",
                                storage_path=storage_path,
                                size_bytes=int((file_info.get("size_kb") or 0) * 1024),
                                force_create=True,
                            )

                        await asyncio.to_thread(_mark_ready)
                    except Exception as exc:
                        stats["downloads_failed"] += 1
                        errors.append(f"{display_name}: {exc}")
                        # Bound as a default: `except ... as exc` deletes the
                        # name on block exit, so a closure over it would be a
                        # late-binding landmine if the thread hop outlived it.
                        def _mark_failed(_err: str = str(exc)) -> None:
                            model_service.repo.update_provider_status(
                                file_id=file_id,
                                provider_id=provider_id,
                                status="failed",
                                error_message=_err,
                                force_create=True,
                            )

                        await asyncio.to_thread(_mark_failed)
                    finally:
                        async with active_lock:
                            active_downloads[:] = [
                                d for d in active_downloads if d.get("file_id") != file_id
                            ]
                        current_download = None
                        await push_state("reconciling", phase="downloading")

            if downloads_needed:
                await push_state(
                    "reconciling",
                    phase="downloading",
                    message=f"Downloading {total_downloads} files...",
                )
                await asyncio.gather(
                    *[download_single(f, i) for i, f in enumerate(downloads_needed)],
                    return_exceptions=True,
                )

            await push_state("reconciling", phase="deleting", message="Checking for orphaned files...")

            if not all_expected_paths:
                logger.warning("in_process_reconcile_no_expected", provider_id=provider_id)
            else:
                orphaned = sorted(p for p in existing_files if p not in all_expected_paths)
                if orphaned:
                    orphan_infos = [
                        {
                            "path": path,
                            "size_bytes": (existing_files_dict.get(path) or {}).get("size", 0),
                            "sha256": (existing_files_dict.get(path) or {}).get("sha256"),
                        }
                        for path in orphaned
                    ]
                    registration = await model_service.reconciliation.register_discovered_files(
                        provider_id, orphan_infos
                    )
                    if registration.get("imported", 0):
                        deletion_candidates: list[dict[str, Any]] = []
                    else:
                        deletion_candidates = orphan_infos

                    if deletion_candidates:
                        if _delete_orphans_enabled():
                            previous = _PREVIOUS_ORPHANS.get(provider_id, set())
                            candidates = [c for c in deletion_candidates if c["path"] in previous]
                            newly_seen = len(deletion_candidates) - len(candidates)
                            if newly_seen:
                                logger.info(
                                    "in_process_reconcile_orphans_not_stable",
                                    provider_id=provider_id,
                                    newly_seen=newly_seen,
                                )
                            _PREVIOUS_ORPHANS[provider_id] = {c["path"] for c in deletion_candidates}
                            candidates = candidates[: _safe_deletion_limit(len(existing_files), len(candidates))]
                            for orphan in candidates:
                                try:
                                    delete_model = getattr(engine, "delete_model", None)
                                    if callable(delete_model):
                                        # Beam: /delete-model removes sidecars too.
                                        deleted = await delete_model(orphan["path"])
                                    else:
                                        deleted = await engine.delete_file(orphan["path"])
                                    if deleted is False:
                                        logger.error(
                                            "in_process_reconcile_delete_failed",
                                            provider_id=provider_id,
                                            path=orphan["path"],
                                        )
                                        continue
                                    stats["deletions_completed"] += 1
                                except Exception as exc:
                                    logger.error(
                                        "in_process_reconcile_delete_failed",
                                        provider_id=provider_id,
                                        path=orphan["path"],
                                        error=str(exc),
                                    )
                            logger.info(
                                "in_process_reconcile_orphans_deleted",
                                provider_id=provider_id,
                                deleted=stats["deletions_completed"],
                                candidates=len(candidates),
                            )
                        else:
                            # Dry run only logs (container parity): promoting
                            # here would delete on the next tick after the
                            # flag flips, skipping the two-sighting stability
                            # the container path requires.
                            logger.info(
                                "in_process_reconcile_orphans_dry_run",
                                provider_id=provider_id,
                                count=len(deletion_candidates),
                            )

            await push_state("completed", phase="completed", message="Reconciliation complete!")
            logger.info("in_process_reconcile_done", provider_id=provider_id, stats=stats)
        except Exception as exc:
            logger.exception("in_process_reconcile_fatal", provider_id=provider_id, error=str(exc))
            errors.append(f"Fatal error: {exc}")
            await push_state("failed", phase="failed", message=f"Reconciliation failed: {exc}")
    finally:
        _RUNNING.discard(provider_id)
        try:
            session.close()
        except Exception:
            pass


#: Mirror the legacy worker's 2h force-reconcile interval
#: (provider_core/background.py:145), driven by the app scheduler.
IN_PROCESS_RECONCILE_INTERVAL_SECONDS = 7200


async def run_periodic_in_process_reconciliation() -> dict[str, Any]:
    """Scheduler tick: a full force-reconcile for every in-process provider.

    Runs detached per provider through trigger_in_process_reconciliation
    (returning immediately when one is already running), so a slow volume
    never blocks the next tick.
    """
    from services.provider_runtime import use_in_process_engines

    if not use_in_process_engines():
        return {"status": "skipped", "reason": "in-process engines disabled"}
    from api import deps as api_deps
    from infrastructure.models.provider import Provider
    from sqlmodel import select

    session = api_deps.get_session_sync()
    try:
        providers = list(session.exec(select(Provider).where(Provider.enabled == True)).all())  # noqa: E712
    finally:
        try:
            session.close()
        except Exception:
            pass
    started: list[str] = []
    skipped: list[str] = []
    for provider in providers:
        try:
            from services.engines.engine_factory import get_engine

            engine = get_engine(provider.id, provider)
            if engine is None:
                continue
            if not getattr(engine, "manages_model_files", False) and not getattr(
                engine, "supports_discovery_reconcile", False
            ):
                continue
            outcome = await trigger_in_process_reconciliation(
                provider.id, provider=provider, engine=engine, force=True
            )
            if outcome.get("status") == "started":
                started.append(provider.id)
            else:
                skipped.append(provider.id)
        except Exception as exc:
            logger.warning(
                "periodic_in_process_reconcile_trigger_failed",
                provider_id=getattr(provider, "id", "?"),
                error=str(exc),
            )
    return {"status": "ok", "started": started, "skipped": skipped}
