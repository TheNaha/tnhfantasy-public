# Handoff Report: ComfyUI Wrapper Database and Model Service Refactoring Strategy

## 1. Observation

### Structure of `backend_v2/infrastructure/database.py`

An inspection of `backend_v2/infrastructure/database.py` reveals the following definitions:

*   **Classes**:
    *   `MigrationStep` (Lines 18–25): A frozen dataclass used to register versioned database schema migration steps:
        ```python
        @dataclass(frozen=True)
        class MigrationStep:
            version: str
            description: str
            apply_fn: Callable
        ```
*   **Globals & Constants**:
    *   `SCHEMA_MIGRATIONS_TABLE = "schema_migrations"` (Line 15)
    *   `logger = db_logger()` (Line 12)
    *   `database_url = get_database_url()` (Line 284)
    *   `engine` (Lines 292–326): The `create_engine` execution configured with SQLite PRAGMA tuning (WAL mode, busy_timeout=30s, Cache size=32MB, memory temp_store) and `NullPool`.
*   **Helper Functions**:
    *   `_get_table_columns(conn, table_name: str) -> set[str]` (Lines 27–33)
    *   `_verify_required_columns(conn, table_name: str, required_columns: set[str]) -> None` (Lines 35–43)
    *   `_ensure_schema_migrations_table(conn) -> None` (Lines 45–57)
    *   `_get_applied_migrations(conn) -> set[str]` (Lines 59–68)
    *   `_record_migration(conn, step: MigrationStep) -> None` (Lines 71–82)
*   **Migration Steps**:
    *   `_migration_add_job_timestamps(conn) -> bool` (Lines 84–106) — Migration `001_jobs_started_completed`
    *   `_migration_setup_prompts_fts(conn) -> bool` (Lines 108–157) — Migration `002_prompts_fts`
    *   `_migration_add_provider_status_provider_id(conn) -> bool` (Lines 159–209) — Migration `003_provider_status_provider_id`
    *   `_migration_normalize_legacy_job_statuses(conn) -> bool` (Lines 211–232) — Migration `004_normalize_legacy_job_statuses`
    *   `_migrate_models_to_v2(conn) -> bool` (Lines 422–718) — Migration `005_migrate_models_to_v2`
*   **Registration & Runner Functions**:
    *   `_get_schema_migration_steps() -> list[MigrationStep]` (Lines 234–262)
    *   `_run_migrations() -> None` (Lines 344–372)
*   **Connection, Initialization, and Session Helpers**:
    *   `get_database_url() -> str` (Lines 265–280)
    *   `create_db_and_tables() -> None` (Lines 328–342)
    *   `get_session() -> Generator[Session, None, None]` (Lines 374–388)
    *   `get_session_sync() -> Session` (Lines 390–392)
    *   `get_session_context()` (Lines 395–408)
    *   `create_test_engine()` (Lines 411–420)

---

### Structure of `backend_v2/services/model_service.py`

An inspection of `backend_v2/services/model_service.py` shows the `ModelServiceV2` class:

*   **Classes**:
    *   `ModelServiceV2` (Lines 51–763): Instantiated via `ModelServiceV2(session: Session)` containing `self.repo = ModelRepositoryV2(session)`.
*   **Globals & Constants**:
    *   `_DIRECTORY_TO_MODEL_TYPE = { ... }` (Lines 31–46)
    *   `logger = model_logger()` (Line 48)
*   **Methods**:
    1.  `__init__(self, session: Session)` (Lines 61–63)
    2.  `add_model_from_civitai(self, civitai_data, selected_version_ids)` (Lines 69–115)
    3.  `get_model(self, model_id: int)` (Lines 117–122)
    4.  `list_models(self, include_versions: bool = False)` (Lines 124–127)
    5.  `list_models_by_directory(self, directory: str)` (Lines 129–132)
    6.  `get_models_grouped(self)` (Lines 134–136)
    7.  `delete_model(self, model_id: int)` (Lines 138–146)
    8.  `check_and_trigger_dependencies(self, civitai_data=None, base_model_name=None)` (Lines 148–274)
    9.  `trigger_download_to_providers(self, model_id, version_ids=None, provider_ids=None)` (Lines 282–374)
    10. `add_custom_model(self, *, name, directory, download_url, provider_ids=None, model_type=None)` (Lines 376–442)
    11. `register_discovered_files(self, provider_id, files)` (Lines 444–545)
    12. `trigger_delete_from_providers(self, model_id: int)` (Lines 547–608)
    13. `get_versions(self, model_id: int)` (Lines 614–617)
    14. `set_default_version(self, model_id: int, version_id: int)` (Lines 619–621)
    15. `toggle_version_enabled(self, version_id: int)` (Lines 623–628)
    16. `get_version_for_generation(self, model_id: int, version_id=None)` (Lines 630–663)
    17. `update_provider_file_status(self, file_id, provider_name, status, storage_path=None, size_bytes=None, error_message=None)` (Lines 669–701)
    18. `get_model_provider_statuses(self, model_id: int)` (Lines 703–705)
    19. `get_pending_downloads(self, provider_name: str)` (Lines 711–713)
    20. `get_full_cache(self)` (Lines 715–717)
    21. `search_by_tag(self, tag: str)` (Lines 723–726)
    22. `search_models(self, query="", model_type=None, base_model=None)` (Lines 728–763)

---

### Code References to be Updated

We searched the `backend_v2` directory using `grep_search` to map all code dependencies.

#### References to `database.py`:
1.  `backend_v2/api/deps.py`:
    *   Line 20: Imports `get_session`, `get_session_context`, and `get_session_sync` from `infrastructure.database`.
2.  `backend_v2/api/lifecycle.py`:
    *   Line 12: Imports `create_db_and_tables` from `infrastructure.database`.
    *   Line 84: Imports `engine` from `infrastructure.database`.
3.  `backend_v2/tests/test_database.py`:
    *   Imports `infrastructure.database as db_module` and tests internal migration functions.
4.  `backend_v2/tests/test_websocket.py`:
    *   Lines 90, 120: Mock-patches `infrastructure.database.get_session_context`.

#### References to `model_service.py`:
1.  `backend_v2/api/deps.py`:
    *   Line 67: Imports `ModelServiceV2` from `services.model_service`.
2.  `backend_v2/api/routes/models/crud.py`:
    *   Line 9: Imports `ModelServiceV2` from `services.model_service`.
3.  `backend_v2/api/routes/models/maintenance.py`:
    *   Line 9: Imports `ModelServiceV2` from `services.model_service`.
4.  `backend_v2/api/routes/models/preview.py`:
    *   Line 9: Imports `ModelServiceV2` from `services.model_service`.
5.  `backend_v2/api/routes/models/provider_sync.py`:
    *   Line 9: Imports `ModelServiceV2` from `services.model_service`.
6.  `backend_v2/api/routes/providers/lifecycle.py`:
    *   Lines 217, 264: Imports `ModelServiceV2` from `services.model_service`.
7.  `backend_v2/services/provider_service.py`:
    *   Lines 387, 392: Imports `ModelServiceV2` from `services.model_service`.
8.  `backend_v2/services/provider_status_service.py`:
    *   Line 15: Imports `ModelServiceV2` from `services.model_service`.
9.  `backend_v2/tests/test_model_service.py`:
    *   Imports `ModelServiceV2` and tests all its methods.
    *   Lines 274, 297: Mock-patches `services.model_service.get_http_client`.

---

## 2. Logic Chain

1.  **Refactoring `database.py`**:
    *   *Premise*: We must separate connection concerns from migrations.
    *   *Split*: `database.py` should only handle the engine setup, SQLite WAL configurations, and session creation/helpers (`get_session`, etc.).
    *   *Migrations Packaging*: A dedicated directory `infrastructure/migrations/` manages schema migration steps. Moving helper functions (like `_get_table_columns`, `_verify_required_columns`, etc.) and the 5 migration functions out of `database.py` preserves engine isolation.
    *   *Transactional Atomicity*: In the original code, migrations run inside a connection block but commit each statement individually (`conn.commit()`) without outer transaction blocks. If a step partially succeeds but then raises an error, the database enters an inconsistent state.
    *   *Solution*: In `infrastructure/migrations/__init__.py`, wrap each migration step in a transaction (`trans = conn.begin()`). If `apply_fn` executes successfully, record the step and call `trans.commit()`. If it returns `False`, rollback. If an exception occurs, rollback and raise a `RuntimeError` to halt database initialization. Remove all internal `.commit()` calls from individual migration functions to make each step atomic.

2.  **Refactoring `model_service.py`**:
    *   *Premise*: `ModelServiceV2` is bloated (~760 lines) and mixes CivitAI sync, file downloading, dependency loading, and provider reconciliation.
    *   *Downloader Service (`model_downloader.py`)*: Groups all methods interacting with worker nodes to request downloads, track statuses, cancel, delete files, handle custom URLs, and download system-level dependencies.
    *   *Reconciliation Service (`model_reconciliation.py`)*: Groups methods that register discovered model files from providers and synchronize them with SQLite state.
    *   *Sync Service (`model_civitai_sync.py`)*: Contains `add_model_from_civitai` which parses JSON payloads and handles schema entities. It communicates with `ModelDownloader` to trigger downloading of newly created files or Flux dependencies.
    *   *Facade Pattern vs. Refactoring Import References*:
        *   *Option A (Facade)*: Keep `ModelServiceV2` inside `model_service.py` as an orchestrator. It instantiates the three new services on `__init__(session)` and delegates method calls to them.
            *   *Advantage*: 0 modifications required in the rest of the codebase (e.g. routes and dependencies) except test assertions. Safe and backward-compatible.
        *   *Option B (Direct Imports)*: Delete or empty the facade, and rewrite all import statements in the 9 dependent files to point directly to `ModelDownloader`, `ModelReconciliationService`, or `ModelCivitaiSyncService`.
            *   *Advantage*: Maximum architectural purity.
            *   *Disadvantage*: High risk of import errors and test failures.
        *   *Recommendation*: Choose Option A (Facade) for immediate execution to guarantee backward compatibility, and plan Option B as a progressive cleanup task.

---

## 3. Caveats

*   **SQLite-Specific Transactions**: While SQLAlchemy transactions (`conn.begin()`) work perfectly in SQLite, SQLite auto-commits DDL statements (like `ALTER TABLE`) if not running inside a proper transaction block. However, Python's `sqlite3` driver handles transaction states automatically. It is vital to test the atomic rollback behavior by intentionally injecting syntax errors into a migration step to verify that it does not leave orphan tables or columns.
*   **Test Patch Paths**: The network efficiency tests in `tests/test_model_service.py` patch `services.model_service.get_http_client`. Since downloaders are moved to `services.model_downloader.py`, these patches must be updated to target `services.model_downloader.get_http_client`, or the tests will fail.

---

## 4. Conclusion

The recommended action is to proceed with the split by building:
1.  A clean SQLite engine/session utility in `backend_v2/infrastructure/database.py`.
2.  A standalone database migration package in `backend_v2/infrastructure/migrations/` using explicit transaction boundaries (`conn.begin()`) and error raising.
3.  Three specialized sub-services for downloading, reconciliation, and CivitAI syncing, coupled with a facade class in `backend_v2/services/model_service.py` that delegates tasks to keep integration seamless.

---

## 5. Refactoring Proposal & Migration Plan

### Step 1: Split `database.py` into a Migrations Package

#### A. Keep `backend_v2/infrastructure/database.py` Clean
Remove all migration functions, helper functions (`_get_table_columns`, etc.), and the `MigrationStep` dataclass.
Update `create_db_and_tables()` to delegate migrations to the new module:

```python
def create_db_and_tables() -> None:
    """Create all tables in the database."""
    # Import entities for registration with SQLModel...
    from core.entities import Collection, CollectionImage, Download, Job, LoadBalancerState, LoadBalancingConfig, Prompt, Provider
    from core.entities_v2 import ModelFile, ModelImage, ModelTag, ModelV2, ModelVersion, ProviderVersionStatus

    SQLModel.metadata.create_all(engine)

    # Run migrations using the split migration runner
    from infrastructure.migrations import run_migrations
    run_migrations(engine)
```

#### B. Create the Migrations Package: `backend_v2/infrastructure/migrations/`

Create `backend_v2/infrastructure/migrations/steps.py` and populate it with:
*   `MigrationStep` dataclass.
*   All helper methods: `_get_table_columns`, `_verify_required_columns`, `_ensure_schema_migrations_table`, `_get_applied_migrations`, `_record_migration`.
*   All 5 migration step functions (001–005).
*   **CRITICAL**: Remove `conn.commit()` from all of these helper and migration functions to let the transaction runner control the transaction boundary.
*   `_get_schema_migration_steps()` registry function.

Create `backend_v2/infrastructure/migrations/__init__.py` with the following transaction runner:

```python
import logging
from infrastructure.logging import db_logger
from infrastructure.migrations.steps import (
    _get_schema_migration_steps,
    _ensure_schema_migrations_table,
    _get_applied_migrations,
    _record_migration
)

logger = db_logger()

def run_migrations(engine) -> None:
    """
    Run schema migrations for existing databases cleanly inside transactions.
    Throws RuntimeError on failure.
    """
    from sqlalchemy import inspect

    with engine.connect() as conn:
        inspector = inspect(engine)

        # If jobs table is missing, the DB is empty. tables are created via metadata.create_all
        if "jobs" not in inspector.get_table_names():
            logger.info("migration_skip_empty_db", reason="jobs_table_missing")
            return

        # Ensure schema_migrations table is created (wrapped in its own transaction)
        trans = conn.begin()
        try:
            _ensure_schema_migrations_table(conn)
            trans.commit()
        except Exception as e:
            trans.rollback()
            logger.error("migration_table_creation_failed", error=str(e))
            raise RuntimeError(f"Failed to create schema migrations table: {e}") from e

        applied_versions = _get_applied_migrations(conn)

        for step in _get_schema_migration_steps():
            if step.version in applied_versions:
                continue

            logger.info("migration_apply_start", version=step.version, description=step.description)
            
            # Start atomic transaction for each migration step
            trans = conn.begin()
            try:
                applied = step.apply_fn(conn)
                if applied:
                    _record_migration(conn, step)
                    trans.commit()
                    logger.info("migration_applied_success", version=step.version)
                else:
                    trans.rollback()
                    logger.info("migration_step_skipped", version=step.version, reason="apply_fn returned False")
            except Exception as e:
                trans.rollback()
                logger.error("migration_failed", version=step.version, error=str(e))
                raise RuntimeError(f"Migration {step.version} failed: {e}") from e
```

---

### Step 2: Split `model_service.py` into Sub-Services

#### A. Create `backend_v2/services/model_downloader.py`
Move downstream worker download API and status monitoring methods here.
*   **Class**: `ModelDownloader`
*   **Methods**:
    *   `trigger_download_to_providers`
    *   `trigger_delete_from_providers`
    *   `add_custom_model`
    *   `check_and_trigger_dependencies`
    *   `update_provider_file_status`
    *   `get_model_provider_statuses`

#### B. Create `backend_v2/services/model_reconciliation.py`
Move disk discovery synchronization here.
*   **Class**: `ModelReconciliationService`
*   **Methods**:
    *   `register_discovered_files`
    *   `get_pending_downloads`
    *   `get_full_cache`

#### C. Create `backend_v2/services/model_civitai_sync.py`
Move JSON payload syncing here.
*   **Class**: `ModelCivitaiSyncService`
*   **Methods**:
    *   `add_model_from_civitai` (uses `ModelDownloader` to trigger downloads)

#### D. Refactor `backend_v2/services/model_service.py` to be a Facade
Inherit or aggregate services to ensure 100% compatibility:

```python
from typing import Dict, Any, List, Optional
from sqlmodel import Session
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2

from services.model_downloader import ModelDownloader
from services.model_reconciliation import ModelReconciliationService
from services.model_civitai_sync import ModelCivitaiSyncService

class ModelServiceV2:
    def __init__(self, session: Session):
        self.session = session
        self.repo = ModelRepositoryV2(session)
        self.downloader = ModelDownloader(session)
        self.reconciler = ModelReconciliationService(session)
        self.sync = ModelCivitaiSyncService(session, downloader=self.downloader)

    # Civitai Sync Delegation
    async def add_model_from_civitai(self, civitai_data: Dict[str, Any], selected_version_ids: List[int]) -> Dict[str, Any]:
        return await self.sync.add_model_from_civitai(civitai_data, selected_version_ids)

    # Downloader Delegation
    async def trigger_download_to_providers(self, model_id: int, version_ids: List[int] = None, provider_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        return await self.downloader.trigger_download_to_providers(model_id, version_ids, provider_ids)

    async def trigger_delete_from_providers(self, model_id: int) -> Dict[str, Any]:
        return await self.downloader.trigger_delete_from_providers(model_id)

    async def add_custom_model(self, *, name: str, directory: str, download_url: str, provider_ids: Optional[List[str]] = None, model_type: Optional[str] = None) -> Dict[str, Any]:
        return await self.downloader.add_custom_model(name=name, directory=directory, download_url=download_url, provider_ids=provider_ids, model_type=model_type)

    async def check_and_trigger_dependencies(self, civitai_data: Optional[Dict[str, Any]] = None, base_model_name: Optional[str] = None) -> Dict[str, Any]:
        return await self.downloader.check_and_trigger_dependencies(civitai_data, base_model_name)

    async def update_provider_file_status(self, file_id: int, provider_name: str, status: str, storage_path: Optional[str] = None, size_bytes: Optional[int] = None, error_message: Optional[str] = None) -> Dict[str, Any]:
        return await self.downloader.update_provider_file_status(file_id, provider_name, status, storage_path, size_bytes, error_message)

    async def get_model_provider_statuses(self, model_id: int) -> Dict[str, Dict[str, Any]]:
        return await self.downloader.get_model_provider_statuses(model_id)

    # Reconciliation Delegation
    async def register_discovered_files(self, provider_id: str, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        return await self.reconciler.register_discovered_files(provider_id, files)

    def get_pending_downloads(self, provider_name: str) -> List[Dict[str, Any]]:
        return self.reconciler.get_pending_downloads(provider_name)

    def get_full_cache(self) -> Dict[str, List[Dict[str, Any]]]:
        return self.reconciler.get_full_cache()

    # Repository / Simple Querying methods
    async def get_model(self, model_id: int) -> Dict[str, Any]:
        from core.exceptions import NotFoundError
        model = self.repo.get_model(model_id)
        if not model:
            raise NotFoundError("Model", str(model_id))
        return self.repo.model_to_dict(model)

    async def list_models(self, include_versions: bool = False) -> List[Dict[str, Any]]:
        models = self.repo.get_all_models()
        return self.repo.models_to_dict(models, include_versions=include_versions)

    async def list_models_by_directory(self, directory: str) -> List[Dict[str, Any]]:
        models = self.repo.get_models_by_directory(directory)
        return self.repo.models_to_dict(models, include_versions=True)

    async def get_models_grouped(self) -> Dict[str, List[Dict[str, Any]]]:
        return self.repo.get_grouped_by_directory()

    async def delete_model(self, model_id: int) -> bool:
        from core.exceptions import NotFoundError
        if not self.repo.get_model(model_id):
            raise NotFoundError("Model", str(model_id))
        await self.downloader.trigger_delete_from_providers(model_id)
        return self.repo.delete_model(model_id)

    async def get_versions(self, model_id: int) -> List[Dict[str, Any]]:
        versions = self.repo.get_versions_for_model(model_id)
        return [self.repo._version_to_dict(v) for v in versions]

    async def set_default_version(self, model_id: int, version_id: int) -> bool:
        return self.repo.set_default_version(model_id, version_id)

    async def toggle_version_enabled(self, version_id: int) -> Optional[Dict[str, Any]]:
        version = self.repo.toggle_version_enabled(version_id)
        if version:
            return self.repo._version_to_dict(version)
        return None

    async def get_version_for_generation(self, model_id: int, version_id: Optional[int] = None) -> Dict[str, Any]:
        from core.entities_v2 import ModelVersion
        from core.exceptions import NotFoundError
        if version_id:
            version = self.session.get(ModelVersion, version_id)
        else:
            version = self.repo.get_default_version(model_id)
        if not version:
            raise NotFoundError("Version", str(version_id or "default"))
        file = self.repo.get_primary_file_for_version(version.id)
        if not file:
            raise NotFoundError("File", f"for version {version.id}")
        model = self.repo.get_model(model_id)
        return {
            "model_id": model_id,
            "version_id": version.id,
            "model_name": model.name,
            "version_name": version.name,
            "base_model": version.base_model,
            "directory": model.directory,
            "storage_path": f"models/{model.directory}/{file.storage_filename}",
            "trained_words": version.trained_words
        }

    async def search_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        models = self.repo.search_by_tag(tag)
        return self.repo.models_to_dict(models, include_versions=False)

    async def search_models(self, query: str = "", model_type: Optional[str] = None, base_model: Optional[str] = None) -> List[Dict[str, Any]]:
        from sqlmodel import select, or_
        from core.entities_v2 import ModelV2
        stmt = select(ModelV2)
        if query:
            stmt = stmt.where(or_(ModelV2.name.ilike(f"%{query}%"), ModelV2.creator_username.ilike(f"%{query}%")))
        if model_type:
            stmt = stmt.where(ModelV2.type == model_type)
        models = list(self.session.exec(stmt).all())
        if base_model:
            filtered = []
            for model in models:
                versions = self.repo.get_versions_for_model(model.id)
                if any(v.base_model == base_model for v in versions):
                    filtered.append(model)
            models = filtered
        return self.repo.models_to_dict(models, include_versions=False)
```

---

## 6. Verification Method

### Test Executions
Run the test suites locally to ensure all endpoints, lifecycles, and database actions are preserved:

1.  **Database Tests**:
    ```bash
    pytest backend_v2/tests/test_database.py
    ```
2.  **Model Service Tests**:
    ```bash
    pytest backend_v2/tests/test_model_service.py
    ```

### Invalidation Conditions
If the unit test suite fails due to unresolved mock references (specifically `services.model_service.get_http_client` patching in `tests/test_model_service.py`), update the patches to `services.model_downloader.get_http_client` immediately.
If the database migration fails with locked database exceptions on SQLite, verify that SQLite's WAL mode and busy timeout are configured correctly, and confirm that there are no overlapping connection pools in the testing engine.
