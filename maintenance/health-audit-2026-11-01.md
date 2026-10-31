# Maintenance Audit & Remediation Plan 2026-11-01

**Date:** 2026-11-01
**Branch:** `maintenance/health-audit-2026-11-01`
**Scope:** Whole repository (`backend_v2/`, `frontend_v2/`, `remote_agent/`, `deployables/`, `scripts/`).
**Status:** 🔄 IN PROGRESS

---

## 0. Baseline

- **Git Commit:** `a047063c` (maintenance(2026-10-31): comprehensive health audit and remediation)
- **Backend Lint (ruff):** 0 errors / 0 warnings ✅
- **Frontend Lint (eslint):** 0 errors / 0 warnings ✅
- **Frontend Build (vite):** clean ✅
- **Frontend Tests (vitest):** 2059 passed, 0 failed ✅
- **Backend Tests (pytest):** ❌ FAILING — 21 failures across 6 test files
  - `test_job_service.py`: 2 failures (datetime conversion in `_row_to_job`)
  - `test_job_queue.py`: 5 failures (`now()` function on SQLite)
  - `test_jobs.py`: 7 failures (cascading from `now()` failure)
  - `test_jobs_extended.py`: 4 failures (cascading from `now()` failure)
  - `test_job_submission_service.py`: 1 failure
  - `test_job_submission_parity.py`: 1 failure

---

## 1. Findings

### Critical Bugs & Correctness

#### CRIT-1: `_row_to_job` datetime conversion broken on SQLAlchemy 2.1 (SQLAlchemy 2.0.52 vs 2.1.6)
- **Location:** `backend_v2/infrastructure/repositories/job_repo.py:496-503`
- **Evidence:** The `_row_to_job` method checks `col_type is datetime` to decide whether to convert raw SQLite datetime strings. On the container (SQLAlchemy 2.1.6), `UTCDateTime.python_type` returns `object` instead of `datetime`, so `col_type is datetime` is `False`. Raw SQL queries (`SELECT jobs.*`) on SQLite return datetime columns as strings (e.g., `'2026-10-31 06:34:02.659974'`). The strings are never converted to `datetime` objects. This causes `_job_to_dict` in `services/job_service.py:1224` to call `.isoformat()` on a string, raising `AttributeError: 'str' object has no attribute 'isoformat'`.
- **Failing tests:** `test_job_service.py::TestJobServiceSearch::test_search_finds_prompt_match`, `test_search_respects_limit`
- **Fix:** Check `issubclass(col_type, datetime)` or use `inspect(Job).columns[key].type` isinstance checks against `DateTime`/`TypeDecorator` more robustly. Alternatively, check the column type class name or use `isinstance(col.type, sqltypes.TypeDecorator)` and check `impl`.

#### CRIT-2: `_DB_CLAIMS_ENABLED` is `True` in container but tests use SQLite
- **Location:** `backend_v2/services/job_queue.py:28`
- **Evidence:** `_DB_CLAIMS_ENABLED = database_url.startswith("postgresql")` is evaluated once at module import. In the Docker container, `POSTGRES_HOST` is set in `.env`, so `database_url` resolves to `postgresql://comfy:comfy@db:5432/comfy`. This makes `_DB_CLAIMS_ENABLED = True`. When test code creates `JobQueue()` instances, they inherit `self._use_db_claims = True`. The `_stamp_fn()` method then returns `"now()"` (PostgreSQL's `NOW()` function). But tests use in-memory SQLite, which doesn't have a `now()` function, causing `sqlite3.OperationalError: no such function: now`.
- **Failing tests:** 19 tests across `test_job_queue.py`, `test_jobs.py`, `test_jobs_extended.py`, `test_job_submission_service.py`, `test_job_submission_parity.py`
- **Fix:** The `JobQueue.__init__` should determine `_use_db_claims` based on the **actual** session's dialect at construction time, not a module-level constant evaluated at import. Alternatively, set `self._use_db_claims = _DB_CLAIMS_ENABLED and self.session.bind.dialect.name == "postgresql"`.

### Architecture & Performance

#### PERF-1: Race conditions on TTLCache access from async coroutines
- **Location:** `backend_v2/services/engines/engine_factory.py:63` (`_ENGINE_CACHE`), `backend_v2/services/load_balancer.py:42-50` (`_provider_health_cache`, `_capability_cache`)
- **Evidence:** Three module-level `TTLCache` instances are accessed from async coroutines without locks. The check-then-act pattern (`if key in cache: return cache[key]`) is not atomic across coroutines — multiple coroutines can simultaneously see a cache miss, all construct engines/health caches, and all write. While `TTLCache` is thread-safe for individual operations, the compound operations are not protected. This is a medium-severity issue because the consequences are extra engine construction (wasteful but not crashing) and potentially stale reads.
- **Fix:** Use `asyncio.Lock` per-cache-key or a single lock around cache miss handling. The `_load_state_lock` pattern in `load_balancer.py:181-189` already demonstrates the correct approach.

---

## 2. Remediation Plan

### Phase 1: Fix failing tests (CRIT-1, CRIT-2)
- Fix `_row_to_job` datetime conversion in `job_repo.py`
- Fix `_use_db_claims` determination in `job_queue.py`
- Re-run all tests to verify

### Phase 2: Address race conditions (PERF-1)
- Add asyncio locks around TTLCache access in `engine_factory.py` and `load_balancer.py`
- Verify no test regressions

### Phase 3: Final verification
- Full backend test suite
- Backend lint
- Frontend lint + tests + build
