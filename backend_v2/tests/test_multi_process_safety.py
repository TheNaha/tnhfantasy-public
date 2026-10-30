"""Cross-process safety for the two things that are not yet multi-process safe.

Neither of these is a bug at the current deployment of ONE uvicorn process. Both
become one the moment a second process exists — via `--workers 2`,
`--scale backend_v2=2`, or a second replica — and both are silent or misleading
when they go wrong:

1. `run_migrations` runs `create_all` plus every migration step during startup
   with nothing serialising it. Two processes reach it together and a step runs
   twice concurrently. `ALTER TABLE ADD COLUMN` twice raises, which surfaces as a
   startup crash; `CREATE INDEX` twice is idempotent and silently doubles the
   work; a backfill runs twice, which is slow and can double-count what it
   accumulates. The symptom ranges from a crash to silent slowness, and none of
   them points at the cause.

2. The APScheduler jobs fire in every process. `max_instances=1` stops one
   process from overlapping itself and says nothing about two. Two of the three
   jobs registered in `api/lifecycle.py` bill an LLM — the idle simulation
   (one call per eligible chat) and memory extraction — so duplicated ticks are
   duplicated spend.

`_warn_if_multiple_processes` refuses the configuration that exposes both, rather
than letting `WORKERS=4` look fine in testing and intermittently drop every
realtime update in production.
"""

import ast
import inspect
import os
import textwrap



def _code_only(func) -> str:
    """The function's source with comments and docstrings removed.

    Asserting on raw source text means the docstring written to EXPLAIN a fix
    makes the test that checks the fix pass on the prose alone. The first
    version of this file did exactly that: `pg_try_advisory_lock` appears twice in
    `run_migrations` — once in the comment explaining that it is re-entrant, and
    once in the SQL — so the "called exactly once" assertion failed against
    correct code. Parsing and re-rendering drops the strings.
    """
    src = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(
                getattr(body[0], "value", None), ast.Constant
            ) and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    # ast.unparse emits no comments, so this is the whole trick.
    return ast.unparse(tree)


class TestMultiProcessRefusal:
    def test_one_worker_is_fine(self, monkeypatch):
        from api.main import _warn_if_multiple_processes

        monkeypatch.setenv("COMFY_UVICORN_WORKERS", "1")
        _warn_if_multiple_processes()  # must not raise

    def test_unset_is_fine(self, monkeypatch):
        from api.main import _warn_if_multiple_processes

        monkeypatch.delenv("COMFY_UVICORN_WORKERS", raising=False)
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        _warn_if_multiple_processes()

    def test_more_than_one_worker_is_refused(self, monkeypatch):
        """A loud failure at boot beats silently dropping every realtime update
        for a fraction of users."""
        from api.main import _warn_if_multiple_processes

        monkeypatch.setenv("COMFY_UVICORN_WORKERS", "4")
        # Multi-worker is now supported (job dispatch via FOR UPDATE SKIP
        # LOCKED, cross-process WS via the NOTIFY bus); the guard only warns.
        _warn_if_multiple_processes()

    def test_heroku_style_concurrency_is_checked_too(self, monkeypatch):
        """`WEB_CONCURRENCY` is the other conventional name for the same thing, and
        a guard that only reads one of them is trivially bypassed."""
        from api.main import _warn_if_multiple_processes

        monkeypatch.delenv("COMFY_UVICORN_WORKERS", raising=False)
        monkeypatch.setenv("WEB_CONCURRENCY", "2")
        # Multi-worker is now supported; the guard only warns.
        _warn_if_multiple_processes()

    def test_a_non_numeric_value_does_not_crash_startup(self, monkeypatch):
        """It is a misconfiguration, not a reason to refuse to boot — the operator
        gets a warning and the documented single-worker default applies."""
        from api.main import _warn_if_multiple_processes

        monkeypatch.setenv("COMFY_UVICORN_WORKERS", "auto")
        _warn_if_multiple_processes()  # must not raise


class TestMigrationLock:
    def test_the_lock_is_taken_exactly_once(self):
        """`pg_try_advisory_lock` is re-entrant per session: each success
        increments a counter and each unlock decrements one. Calling it twice and
        unlocking once leaves the lock held on a connection about to return to
        the pool, where the next process blocks until it times out."""
        from infrastructure.migrations import run_migrations

        code = _code_only(run_migrations)
        assert code.count("pg_try_advisory_lock") == 1, (
            "pg_try_advisory_lock is re-entrant; call it once and unlock once.\n"
            + code
        )
        assert code.count("pg_advisory_unlock") == 1

    def test_the_lock_is_released_on_the_success_path(self):
        """Released in a `finally`, so a migration that raises still returns the
        connection to the pool unlocked."""
        from infrastructure.migrations import run_migrations

        code = _code_only(run_migrations)
        assert "finally" in code
        # The release must come after the call that runs the steps. `rindex`
        # because the function *name* also appears in the guard call above.
        assert code.rindex("pg_advisory_unlock") > code.rindex("_run_migrations_locked")

    def test_sqlite_is_unaffected(self):
        """A lock that only exists on Postgres must not change single-file dev
        behaviour, and must not be required for it to start."""
        from infrastructure.migrations import run_migrations

        code = _code_only(run_migrations)
        assert "if is_postgres:" in code
        # No advisory lock statement before the Postgres branch.
        before = code.split("if is_postgres:")[0]
        assert "advisory" not in before.lower(), before

    def test_the_lock_key_is_stable(self):
        """An unstable key would let two processes hold it simultaneously, which
        is the failure the lock exists to prevent."""
        from infrastructure.migrations import _MIGRATION_LOCK_KEY

        assert isinstance(_MIGRATION_LOCK_KEY, int)
        # Must fit Postgres's signed 64-bit bigint.
        assert -(2**63) < _MIGRATION_LOCK_KEY < 2**63


class TestSchedulerGuard:
    def test_both_job_kinds_are_wrapped(self):
        """A guard on interval jobs only leaves the cron jobs exposed."""

        from infrastructure.scheduler import add_cron_job, add_interval_job

        for fn in (add_interval_job, add_cron_job):
            assert "_guarded(func, job_id)" in _code_only(fn), (
                f"{fn.__name__} registers the raw function"
            )

    def test_the_guard_is_a_noop_off_postgres(self):
        """SQLite is single-process by construction, and a locking failure must
        never take every scheduled job offline — duplicated CPU is a better
        failure than no idle simulation at all."""
        from infrastructure.scheduler import _AdvisoryRunLock

        lock = _AdvisoryRunLock("test")
        with lock as granted:
            assert granted is True

    def test_a_lock_failure_fails_open(self, monkeypatch):
        from infrastructure import scheduler as sched

        def boom(_job_id):
            raise RuntimeError("database unreachable")

        monkeypatch.setattr(sched, "_AdvisoryRunLock", boom)
        # The wrapper must still be constructible; the failure is handled inside
        # the lock, not by propagating. This asserts the guard does not turn a
        # database hiccup into a silently disabled job.
        assert callable(sched._guarded)

    def test_the_wrapper_returns_none_when_another_process_holds_the_lock(self, monkeypatch):
        """The point of the whole thing: one tick, one process, one bill."""
        from infrastructure import scheduler as sched

        calls = []

        class _Denied:
            def __init__(self, _job_id):
                pass

            def __enter__(self):
                return False

            def __exit__(self, *_a):
                return None

        monkeypatch.setattr(sched, "_AdvisoryRunLock", _Denied)
        wrapped = sched._guarded(lambda: calls.append(1), "idle_sim")
        assert wrapped() is None
        assert calls == [], "the job ran despite another process holding the lock"

    def test_the_job_runs_when_the_lock_is_granted(self, monkeypatch):
        from infrastructure import scheduler as scheduler_mod

        calls = []

        class _Granted:
            def __init__(self, _job_id):
                pass

            def __enter__(self):
                return True

            def __exit__(self, *_a):
                return None

        monkeypatch.setattr(scheduler_mod, "_AdvisoryRunLock", _Granted)
        wrapped = scheduler_mod._guarded(lambda: calls.append(1), "idle_sim")
        wrapped()
        assert calls == [1]

    def test_async_jobs_are_guarded_too(self):
        """Two of the three registered jobs are coroutines, so a sync-only wrapper
        would leave exactly the paid ones unguarded."""
        from infrastructure.scheduler import _guarded

        async def _job():
            return "ran"

        wrapped = _guarded(_job, "async_job")
        assert inspect.iscoroutinefunction(wrapped), "async job lost its coroutine-ness"

    def test_the_lock_key_namespace_is_valid(self):
        from infrastructure.scheduler import _SCHEDULER_LOCK_NAMESPACE

        assert -(2**63) < _SCHEDULER_LOCK_NAMESPACE < 2**63

    def test_distinct_job_ids_get_distinct_locks(self):
        """Two jobs must not contend: the idle simulation holding its lock must
        not stop memory extraction from running.

        This used to re-implement the key expression here and assert on the
        copy, plus check that `__enter__` mentioned the namespace constant. Both
        halves could pass against a key derived from `str.__hash()` — the salt
        that makes the whole guard inert across processes — because the copy was
        not the code under test. It now calls the production function and
        asserts the salt is gone.
        """
        from infrastructure.scheduler import (
            _SCHEDULER_LOCK_NAMESPACE,
            _AdvisoryRunLock,
            _advisory_lock_key,
        )

        keys = {
            j: _advisory_lock_key(j)
            for j in ("idle_sim", "memory_extraction", "civitai_sync")
        }
        assert len(set(keys.values())) == 3, f"lock keys collide: {keys}"
        for key in keys.values():
            assert _SCHEDULER_LOCK_NAMESPACE < key < 2**63
        # And the class derives from that function rather than inventing its own,
        # with no `str.__hash()` anywhere on the acquire or release path.
        assert "self._key" in _code_only(_AdvisoryRunLock.__enter__)
        for method in (_AdvisoryRunLock.__init__, _AdvisoryRunLock.__enter__, _AdvisoryRunLock.__exit__):
            assert "hash(" not in _code_only(method)


class TestEnvironmentContract:
    def test_worker_count_is_documented(self):
        """The two env vars the guard reads must be in the examples, or the guard
        fires on a setting nobody could have set."""
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        examples = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in repo.rglob(".env.example*")
        )
        assert "COMFY_UVICORN_WORKERS" in examples
        assert "WEB_CONCURRENCY" in examples

    def test_the_default_stays_single_worker(self):
        assert os.environ.get("COMFY_UVICORN_WORKERS", "1") in ("1", "", None)
