# Changelog

All notable changes to TNHFantasy are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — 2026-11-11

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
