# Changelog

All notable changes to TNHFantasy are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — 2026-11-13

### Fixed
- **Comic Export Lifecycle (`backend_v2/api/routes/world_vault/stories.py`)**:
  - Awaited `JobService.update_job` directly in `_run_export` instead of discarding an unawaited coroutine through `asyncio.to_thread`.
  - Snapshotted `job.id`, `job.metadata_`, and `chapter.chapter_number` before spawning background export, eliminating `DetachedInstanceError` reads on closed request sessions.
- **Cross-Process Worker Registry (`backend_v2/infrastructure/worker_registry.py`)**:
  - Converted `_provider_has_ws_connection` from `async def` to synchronous `def` with parameterized SQL intervals.
  - Caught exceptions on `future.result()` in `_run_notify_listener` to write failed outbox results and prevent listener thread crashes.
  - Added `threading.Event` shutdown flag to stop the notification listener loop cleanly on process termination.
- **Model Metadata Resync (`backend_v2/api/routes/models/maintenance.py`)**:
  - Converted `resync_all` to `async def` so `start_background_task` runs on the active event loop.
  - Added `bg_session.rollback()` on model commit failures in `run_background_resync` to prevent `PendingRollbackError` cascades.
- **Worker WebSocket Lifecycle (`backend_v2/api/routes/worker_ws.py`)**:
  - Resolved pending job futures with `ProviderCallError` on output validation or finalization failure.
  - Moved `register_worker` inside `try...finally` so handshake failures always unregister cleanly.
- **In-Process Engine & Reconciliation Lifecycle (`backend_v2/services/`)**:
  - Replaced dead `token`/`status` TaskEvent checks in `world_onboarding_service.py` with canonical `delta`/`completed` event parsing.
  - Tracked active job IDs on child engines in `HybridRemoteEngine` so `cancel_job` propagates aborts and interrupts to ComfyUI/LLM workers.
  - Isolated thread-scoped database sessions for concurrent status updates in `in_process_reconciliation.py`.
  - Synchronized `_ENGINE_CACHE` writes under lock and cached `GoogleLLMEngine` to avoid connection leaks.
  - Awaited `chat_reply` and `narrator` message persistence before running post-turn memory/director stages in `job_processing.py`.
  - Propagated errors in `BeamLLMEngine.list_models` and `validate_models` instead of swallowing failures as empty volumes.
  - Enforced `serves()` and capability filtering on `preferred_provider_id` in `LoadBalancer`.
  - Awaited cancelled fetcher tasks in `BeamEngine.inference`.
  - Normalized naive and aware timestamps using `as_utc()` in `job_service.py` and `lifecycle.py`.
- **Worker Runtimes & Cloud Deployables (`remote_agent/`, `deployables/`)**:
  - Configured `remote_agent` hybrid mode to allow JIT `llama-server` startup on `:8003`.
  - Tracked `lease_acquired` in `vram_manager.py` and ensured clean lease release and client close on `CancelledError`.
  - Concurred and offloaded model downloads in `deployables/modal/llm/app.py` with correct kwargs and volume commit.
  - Confined paths in `remote_agent` and `deployables/beam` storage operations and mapped invalid paths to HTTP 400.
  - Enforced upload size caps and pipeline artifact cleanup across modal and beam deployables.
- **Frontend Reliability & Lifecycle (`frontend_v2/src/`)**:
  - Passed `createEdge.mutateAsync` to `LinkDialog` in `RelationshipGraph.jsx`, fixing edge creation failures.
  - Handled parameter-reuse failures with error toasts in `Dashboard.jsx`.
  - Added `onError` error toasts across `useWorldVaultSearch`, `useAssetTags`, `useLLMProviderStatus`, `useChats`, `useLorebooks`, and `useFavorites`.
  - Revoked `blob:` preview URLs in `ImageToStory.jsx`, `LLMStudio.jsx`, and `Characters.jsx`.
  - Cleaned up reconnect timers in `websocket.js` and transient feedback/ping timers across components.
  - Cached source image instances and added unmount/error guards in `InpaintCanvas.jsx`.
  - Routed image interrogation through `api.post` in `pngInfoReader.js`.

### Changed
- Deduplicated `llm_config` model listing and pre-fetched agent prompt variants to eliminate N+1 queries.
- Switched `core/workflow_builder.py` and `core/workflow_postprocess.py` session imports from `api.deps` to `infrastructure.deps`.

## [2.1.0] — 2026-11-13

### Fixed
- **Database Migrations (`backend_v2/infrastructure/migrations/steps.py`)**:
  - Restored severed column addition and claim indexing in `_migration_add_jobs_claimed_at` (025).
  - Removed unreachable duplicate DDL statements accidentally spliced inside `_migration_099_world_edges`.
  - Added dialect guard to `_migration_087_asset_seed_bigint` so SQLite environments no longer fail on Postgres-only `ALTER COLUMN TYPE` statements.
- **Event Loop Concurrency (`backend_v2/api/routes/settings.py`)**:
  - Converted synchronous scheduler routes (`run_scheduler_job`, `patch_scheduler_job`) from `async def` to `def`, allowing FastAPI to dispatch them to threadpools without blocking the server event loop.
- **Query Performance (`backend_v2/services/checkpoint_recommendations.py`)**:
  - Appended `.limit(1)` to LoRA model query to enforce bounded query execution.
- **Engine Stream Management (`backend_v2/services/engines/worker_transport_engines.py`)**:
  - Added `finally` cleanup to cancel background fetcher tasks and unregister abort handles on stream termination.
- **Job Service Safety (`backend_v2/services/job_service.py`)**:
  - Guarded against `None` return on concurrent job deletions in `update_job`.
  - Normalized naive and timezone-aware timestamps using `as_utc()` before duration arithmetic.
- **WebSocket Job Cancellation (`backend_v2/api/routes/websocket.py`)**:
  - Allowed cancellation of active jobs running across worker boundaries or claimed via PostgreSQL skip-locked queues.
- **Frontend Lifecycle Hygiene (`frontend_v2/src/`)**:
  - Added unmount cleanups for LLM title generation in `StorySandbox.jsx`.
  - Cleaned up timeouts in `BatchAutopopulateModal.jsx` and `ContextMenu.jsx`.
  - Integrated `AbortController` in `DeployTab.jsx` to abort active deploy streams on navigation.
  - Satisfied `exhaustive-deps` in `InstalledTab.jsx` by including `queryClient`.

### Changed
- Synchronized contract test assertions in `test_app_boot_smoke.py` (updated route count for `/api/v2/models/storage-breakdown`) and `test_job_submission_service.py`.

## [2.0.0] — 2026-11-10

### Added
- Comprehensive library storage analytics and category breakdown in Model Manager.
- Telemetry, sampling speed, and transfer metrics in Gallery lightbox modal.

### Fixed
- Deduplicated `charGen*` prompts into shared constants module.
- Mutation error reporting across `useCollections` and `useJobRecovery`.
