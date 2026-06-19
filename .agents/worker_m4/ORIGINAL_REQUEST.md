## 2026-06-19T12:50:17Z

Your role is Worker M4 for the ComfyUI Wrapper Audit, Consolidation, and Repair project.
Your working directory is /home/thenaha/containers/stacks/comfyui/.agents/worker_m4.
Your task is to implement Milestone 4 (Backend Refactoring & Decoupling).

Specifically, you must:
1. Refactor backend_v2/infrastructure/database.py:
   - Extract the `MigrationStep` dataclass, the helper functions (_get_table_columns, _verify_required_columns, _ensure_schema_migrations_table, _get_applied_migrations, _record_migration), and all 5 migration step functions (001-005) into a new module `backend_v2/infrastructure/migrations/steps.py`.
   - Remove any internal `.commit()` calls from within these helper and migration functions in `steps.py` to allow the outer transaction runner to handle commit/rollback boundaries.
   - Implement the transaction runner `run_migrations(engine)` in `backend_v2/infrastructure/migrations/__init__.py`. Ensure it wraps each migration step execution in a transaction block using SQLAlchemy/SQLModel (e.g. `trans = conn.begin()`), commits if successful, rolls back on Failure/Exception, and raises a `RuntimeError` on failure so database initialization halts.
   - Keep `backend_v2/infrastructure/database.py` focused purely on database URL config, engine creation, SQLite connection tuning, session helpers (`get_session`, `get_session_sync`, etc.), and `create_db_and_tables` which should call `run_migrations(engine)` from `infrastructure.migrations`.
   
2. Refactor backend_v2/services/model_service.py:
   - Split the logic of `ModelServiceV2` into three new specialized service files:
     - `backend_v2/services/model_downloader.py`: Contains class `ModelDownloader` wrapping downsteam worker downloads, status updates, custom model registration, and dependency tracking (`trigger_download_to_providers`, `trigger_delete_from_providers`, `add_custom_model`, `check_and_trigger_dependencies`, `update_provider_file_status`, `get_model_provider_statuses`).
     - `backend_v2/services/model_reconciliation.py`: Contains class `ModelReconciliationService` wrapping provider model directory reconciliation and caching (`register_discovered_files`, `get_pending_downloads`, `get_full_cache`).
     - `backend_v2/services/model_civitai_sync.py`: Contains class `ModelCivitaiSyncService` wrapping CivitAI metadata importing/parsing logic (`add_model_from_civitai`).
   - Rewrite `backend_v2/services/model_service.py` to act as a Facade class `ModelServiceV2` that instantiates these sub-services on initialization (`__init__`) and delegates method calls to them, ensuring 100% backward compatibility with all existing callers.
   
3. Adjust tests:
   - Update `backend_v2/tests/test_model_service.py` to adjust any mock patches that targeted `services.model_service` (like `services.model_service.get_http_client` which should now patch `services.model_downloader.get_http_client` or similar) to ensure all tests pass.
   - Run the database and model service tests (`pytest backend_v2/tests/test_database.py` and `pytest backend_v2/tests/test_model_service.py`).
   - Run the full backend test suite to make sure no regressions were introduced.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

When complete, notify parent conversation d4553e37-d267-4d5b-ba70-743258ac2a78 by calling send_message with recipient parent.
Provide a detailed handoff in /home/thenaha/containers/stacks/comfyui/.agents/worker_m4/handoff.md documenting your changes and test results.
