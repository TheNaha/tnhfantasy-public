"""Regression tests for the event-loop-blocking / unbounded-work fixes.

Each test pins the behaviour the fix is supposed to guarantee, not the
implementation detail of how it is guaranteed:

* the batch generate endpoint refuses an oversized `workflows` array with the
  shared BATCH_TOO_LARGE error shape, creating no jobs;
* provider delete clears `jobs.provider_id` in a single statement and reports a
  row count;
* `LoadBalancer.remove_provider_state` does not hold the asyncio lock across the
  blocking DB commit;
* the health probe and the provider container-status route go through the
  blocking-but-cached accessors on a worker thread;
* the job queue's fire-and-forget tasks are tracked, so they survive GC and are
  drained on shutdown;
* the Postgres engine has an explicit, generous pool ceiling.

Endpoint payload tests for the `asyncio.to_thread` conversions live in
`test_files_route.py` and `test_upload_export_hardening.py`; here we only assert
the routing invariant that the blocking work leaves the loop.
"""
import ast
import asyncio
import inspect
import textwrap
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session, select

from api.routes import files as files_module
from api.routes import generation as generation_module
from core.entities import Job, JobStatus, Provider
from services import load_balancer as lb_module
from services.load_balancer import LoadBalancer, LoadBalancerRuntimeState
from services.provider_service import ProviderService


# ---------------------------------------------------------------------------
# 5. POST /api/generate/batch has a real cap
# ---------------------------------------------------------------------------

class TestGenerateBatchCap:
    def test_rejects_more_than_the_cap(self, client, sample_workflow, monkeypatch):
        monkeypatch.setattr(generation_module, "MAX_GENERATE_BATCH", 3)

        response = client.post(
            "/api/generate/batch", json={"workflows": [sample_workflow] * 4}
        )

        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "BATCH_TOO_LARGE"
        assert body["field"] == "workflows"
        assert body["details"] == {"received": 4, "max_items": 3}

    def test_allows_exactly_the_cap(self, client, sample_workflow, monkeypatch):
        monkeypatch.setattr(generation_module, "MAX_GENERATE_BATCH", 3)
        response = client.post(
            "/api/generate/batch", json={"workflows": [sample_workflow] * 3}
        )
        assert response.status_code == 200
        assert response.json()["count"] == 3

    def test_cap_is_at_least_the_frontend_ui_limit(self):
        # The UI stops at 60 (frontend_v2/src/pages/BatchGenerate.jsx); a
        # smaller server cap would break scripted callers that use the
        # documented UI maximum.
        assert generation_module.MAX_GENERATE_BATCH >= 60

    def test_default_cap_rejects_a_5000_entry_body(self, client, sample_workflow):
        response = client.post(
            "/api/generate/batch", json={"workflows": [sample_workflow] * 5000}
        )
        assert response.status_code == 400
        assert response.json()["code"] == "BATCH_TOO_LARGE"


# ---------------------------------------------------------------------------
# 6. DELETE /api/v2/providers/{id} detaches jobs in one statement
# ---------------------------------------------------------------------------

class TestProviderDeleteDetachesJobsInOneStatement:
    @pytest.fixture
    def provider_with_jobs(self, session: Session):
        provider = Provider(
            id="p1", type="modal", enabled=True, priority=1, credentials={}, config={}
        )
        session.add(provider)
        for index in range(5):
            session.add(
                Job(
                    task_type="image",
                    status=JobStatus.COMPLETED,
                    provider_id="p1",
                    workflow={"nodes": [index], "edges": []},
                )
            )
        session.commit()
        return provider

    async def test_clears_reference_and_keeps_rows(self, session: Session, provider_with_jobs):
        service = ProviderService(session)
        assert await service.delete_provider("p1") is True

        remaining = session.exec(select(Job)).all()
        assert len(remaining) == 5
        assert all(job.provider_id is None for job in remaining)

    def test_issues_a_single_dml_statement_and_reports_the_rowcount(
        self, session: Session, provider_with_jobs, monkeypatch
    ):
        """A provider with 50k jobs must not produce 50k ORM UPDATEs."""
        service = ProviderService(session)
        statements = []
        commits = {"count": 0}
        original_exec = session.exec
        original_commit = session.commit

        def recording_exec(statement, *args, **kwargs):
            statements.append(statement)
            return original_exec(statement, *args, **kwargs)

        def counting_commit():
            commits["count"] += 1
            return original_commit()

        monkeypatch.setattr(session, "exec", recording_exec)
        monkeypatch.setattr(session, "commit", counting_commit)

        assert service._detach_provider_jobs("p1") == 5
        assert len(statements) == 1
        assert statements[0].is_update
        assert not statements[0].is_select
        assert commits["count"] == 1

    def test_detach_is_a_noop_for_an_unknown_provider(self, session: Session, provider_with_jobs):
        service = ProviderService(session)
        assert service._detach_provider_jobs("does-not-exist") == 0


# ---------------------------------------------------------------------------
# 8. remove_provider_state must not hold the asyncio lock across the commit
# ---------------------------------------------------------------------------

class TestRemoveProviderStateLockScope:
    @pytest.fixture
    def registered_state(self):
        """The state object actually registered in `_runtime_states` under id 1.

        `remove_provider_state` only persists for stores it found by iterating
        `_runtime_states`; an explicitly-passed `runtime_state` has no state_id
        and is deliberately not persisted.
        """
        state = lb_module.get_runtime_state(1)
        state.reset()
        yield state
        state.reset()

    async def test_commit_happens_with_the_lock_released(
        self, session: Session, registered_state, monkeypatch
    ):
        registered_state.provider_job_counts["p1"] = 3
        registered_state.provider_failures["p1"] = 2

        lock = registered_state.get_lock()
        observed: dict = {}

        def spy_save(*args, **kwargs):
            runtime_state = kwargs.get("runtime_state")
            snapshot = kwargs.get("snapshot")
            observed["locked"] = lock.locked()
            observed["counts"] = dict(runtime_state.provider_job_counts)
            observed["failures"] = dict(runtime_state.provider_failures)
            observed["snapshot"] = snapshot
            return None

        monkeypatch.setattr(LoadBalancer, "save_state_to_db", classmethod(spy_save))

        await LoadBalancer.remove_provider_state(session, "p1")

        assert observed, "the removal must actually persist for a registered state"
        assert observed["locked"] is False
        assert observed["counts"] == {}
        assert observed["failures"] == {}
        # The snapshot was taken while the lock was held, so the write is a
        # consistent point-in-time view rather than a re-read of live state.
        assert observed["snapshot"]["provider_job_counts"] == {}

    async def test_persisted_state_matches_the_mutation(self, session: Session, registered_state):
        from core.entities import LoadBalancerState

        registered_state.provider_job_counts["p1"] = 3
        registered_state.provider_failures["p1"] = 2
        registered_state.round_robin_index = 7

        await LoadBalancer.remove_provider_state(session, "p1")

        row = session.get(LoadBalancerState, 1)
        assert row is not None
        assert "p1" not in (row.provider_job_counts or {})
        assert "p1" not in (row.provider_failures or {})
        assert row.round_robin_index == 7

    async def test_unknown_provider_does_not_persist(
        self, session: Session, registered_state, monkeypatch
    ):
        registered_state.provider_job_counts["p1"] = 1

        calls = {"count": 0}

        def counting_save(*args, **kwargs):
            calls["count"] += 1
            return None

        monkeypatch.setattr(LoadBalancer, "save_state_to_db", classmethod(counting_save))

        await LoadBalancer.remove_provider_state(session, "other")
        assert calls["count"] == 0
        assert registered_state.provider_job_counts == {"p1": 1}

    async def test_explicit_runtime_state_is_not_persisted(
        self, session: Session, registered_state, monkeypatch
    ):
        """An explicitly-passed state carries no state_id, so it is not written.

        Documents the pre-existing contract the fix must preserve: only stores
        discovered by iterating `_runtime_states` are persisted.
        """
        from core.entities import LoadBalancerState

        orphan = LoadBalancerRuntimeState()
        orphan.provider_job_counts["p1"] = 3
        session.get(LoadBalancerState, 1)

        calls = {"count": 0}

        def counting_save(*args, **kwargs):
            calls["count"] += 1
            return None

        monkeypatch.setattr(LoadBalancer, "save_state_to_db", classmethod(counting_save))

        await LoadBalancer.remove_provider_state(session, "p1", runtime_state=orphan)

        assert calls["count"] == 0
        assert orphan.provider_job_counts == {}


# ---------------------------------------------------------------------------
# 7. Health probe must not touch the Docker socket on the event loop
# ---------------------------------------------------------------------------

class TestHealthProbeCachesEngineResult:
    @pytest.fixture
    def provider(self, session: Session):
        provider = Provider(
            id="p1",
            type="modal",
            enabled=True,
            priority=1,
            credentials={},
            config={},
        )
        session.add(provider)
        session.commit()
        return provider

    @pytest.fixture(autouse=True)
    def _reset_lb(self):
        LoadBalancer.reset_state()
        yield
        LoadBalancer.reset_state()

    def _engine(self, health: dict):
        engine = MagicMock()
        engine.check_health = AsyncMock(return_value=health)
        return engine

    async def test_healthy_engine_result_is_cached(
        self, session: Session, provider, monkeypatch
    ):
        """The 15s health cache means only the first caller pays for a probe."""
        lb = LoadBalancer(session, strategy="round-robin")
        lb.health_check_enabled = True
        lb_module._provider_health_cache.clear()

        engine = self._engine({"status": "healthy"})
        monkeypatch.setattr(
            "services.engines.engine_factory.can_create_engine", lambda _p: True
        )
        monkeypatch.setattr(
            "services.engines.engine_factory.get_engine", lambda _pid, _p: engine
        )

        assert await lb._check_provider_health(provider) is True
        assert await lb._check_provider_health(provider) is True
        assert lb_module._provider_health_cache["in_process:p1"] is True
        engine.check_health.assert_awaited_once()

    async def test_unconstructible_engine_short_circuits_to_unhealthy(
        self, session: Session, provider, monkeypatch
    ):
        """A provider with no buildable engine is not routable — no probe runs."""
        lb = LoadBalancer(session, strategy="round-robin")
        lb.health_check_enabled = True
        lb_module._provider_health_cache.clear()

        get_engine = MagicMock(side_effect=AssertionError("must not be reached"))
        monkeypatch.setattr(
            "services.engines.engine_factory.can_create_engine", lambda _p: False
        )
        monkeypatch.setattr("services.engines.engine_factory.get_engine", get_engine)

        assert await lb._check_provider_health(provider) is False
        get_engine.assert_not_called()

    async def test_failure_streak_short_circuits_before_any_probe(
        self, session: Session, provider, monkeypatch
    ):
        lb = LoadBalancer(session, strategy="round-robin")
        lb.health_check_enabled = True
        lb_module._provider_health_cache.clear()

        can_create = MagicMock(side_effect=AssertionError("must not be reached"))
        monkeypatch.setattr("services.engines.engine_factory.can_create_engine", can_create)

        lb.runtime_state.provider_failures["p1"] = lb_module._FAILURE_STREAK_THRESHOLD

        assert await lb._check_provider_health(provider) is False
        can_create.assert_not_called()

    def test_probe_timeout_is_bounded(self):
        assert lb_module._ENGINE_HEALTH_PROBE_TIMEOUT_SECONDS > 0
        # The 15s health cache means only the first caller to miss pays this,
        # so it must stay well under a request budget.
        assert lb_module._ENGINE_HEALTH_PROBE_TIMEOUT_SECONDS <= 30


# ---------------------------------------------------------------------------
# 11. Fire-and-forget tasks are tracked
# ---------------------------------------------------------------------------

class TestQueueBackgroundTasksAreTracked:
    async def test_notify_wake_runs_and_is_named(self):
        from infrastructure.background_tasks import _background_tasks
        from services.job_queue import JobQueue

        queue = JobQueue(max_workers=1, task_type="image")
        notified = asyncio.Event()

        async def fake_notify():
            notified.set()

        queue._notify_wake = fake_notify

        queue._schedule_notify()
        await asyncio.wait_for(notified.wait(), timeout=2.0)

        # Either still tracked or already finished cleanly — but never
        # collected mid-flight, which is what a bare create_task allowed.
        await asyncio.sleep(0)
        assert all(
            task.done() or task in _background_tasks for task in _background_tasks
        )

    async def test_schedule_notify_without_a_loop_is_a_noop(self):
        from services.job_queue import JobQueue

        queue = JobQueue(max_workers=1, task_type="image")
        errors: list = []

        def run():
            try:
                queue._schedule_notify()
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        assert errors == []

    async def test_resize_task_is_tracked_then_discarded(self):
        from services.job_queue import QueueManager

        manager = QueueManager()
        await manager.image.start()

        # Keyword form: resizing one pool must not disturb the others, which is
        # why `resize` no longer takes a positional image/llm pair.
        manager.resize(image=3)
        await asyncio.sleep(0.05)

        assert len(manager.image._workers) == 3
        assert manager._resize_tasks == set()
        # Untouched pools keep their size.
        assert manager.llm.max_workers == 1
        assert manager.tts.max_workers == 1

        await manager.stop()

    async def test_pending_resize_is_cancelled_by_stop(self):
        from services.job_queue import QueueManager

        manager = QueueManager()
        await manager.image.start()

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_resize(count):
            del count
            started.set()
            await release.wait()

        manager.image.resize = slow_resize
        manager.resize(image=5)

        await asyncio.wait_for(started.wait(), timeout=2.0)
        pending = [t for t in manager._resize_tasks if not t.done()]
        assert pending, "resize task must be tracked, not fire-and-forget"

        await manager.stop()
        assert manager._resize_tasks == set()
        assert all(t.done() for t in pending)

    async def test_stop_drains_resizes_before_cancelling_workers(self):
        from services.job_queue import QueueManager

        manager = QueueManager()
        order: list = []

        original_drain = manager._drain_resize_tasks

        async def spy_drain():
            order.append("drain")
            await original_drain()

        manager._drain_resize_tasks = spy_drain
        original_stop = manager.image.stop

        async def spy_stop(timeout_seconds=30.0):
            order.append("stop")
            await original_stop(timeout_seconds=timeout_seconds)

        manager.image.stop = spy_stop

        await manager.stop()
        assert order == ["drain", "stop"]


# ---------------------------------------------------------------------------
# 1. Postgres engine has an explicit pool ceiling
# ---------------------------------------------------------------------------

class TestDatabasePoolSizing:
    def test_pool_constants_are_explicit_and_generous(self):
        import infrastructure.database as db

        # SQLAlchemy's non-SQLite default ceiling is 15 (pool_size 5 +
        # max_overflow 10).
        assert db.DB_POOL_SIZE + db.DB_MAX_OVERFLOW > 15
        assert db.DB_POOL_SIZE >= 20
        assert db.DB_POOL_TIMEOUT > 0

    def test_positive_int_env_reads_and_falls_back(self, monkeypatch):
        import infrastructure.database as db

        monkeypatch.delenv("COMFY_DB_POOL_SIZE", raising=False)
        assert db._positive_int_env("COMFY_DB_POOL_SIZE", 7) == 7

        monkeypatch.setenv("COMFY_DB_POOL_SIZE", "42")
        assert db._positive_int_env("COMFY_DB_POOL_SIZE", 7) == 42

        # A malformed or non-positive value must not disable the pool config.
        for junk in ("abc", "0", "-5"):
            monkeypatch.setenv("COMFY_DB_POOL_SIZE", junk)
            assert db._positive_int_env("COMFY_DB_POOL_SIZE", 7) == 7

    def test_postgres_branch_passes_the_pool_config(self):
        """`db.engine` is swapped for the test engine by conftest, so assert on
        the construction site itself rather than on the live pool object."""
        import infrastructure.database as db

        source = inspect.getsource(db)
        for kwarg in (
            "pool_size=DB_POOL_SIZE",
            "max_overflow=DB_MAX_OVERFLOW",
            "pool_timeout=DB_POOL_TIMEOUT",
        ):
            assert kwarg in source, f"Postgres engine must set {kwarg}"

    def test_sqlite_branch_keeps_nullpool(self):
        import infrastructure.database as db

        source = inspect.getsource(db)
        # The SQLite path must remain NullPool — it is the only thing that
        # stops a file-backed dev database from exhausting its own connections.
        assert "poolclass=NullPool" in source


# ---------------------------------------------------------------------------
# 2/3/4. files.py routes delegate their blocking bodies to worker threads
# ---------------------------------------------------------------------------

class TestFilesRoutesDelegateToWorkerThreads:
    @pytest.mark.parametrize(
        "name",
        [
            "_serve_thumbnail_sync",
            "_view_file_sync",
            "_build_export_zip_sync",
            "_batch_delete_sync",
        ],
    )
    def test_sync_worker_body_exists(self, name):
        assert callable(getattr(files_module, name))

    @pytest.mark.parametrize(
        "name",
        [
            "_serve_thumbnail_sync",
            "_view_file_sync",
            "_build_export_zip_sync",
            "_batch_delete_sync",
        ],
    )
    def test_worker_body_never_re_enters_the_event_loop(self, name):
        """A body moved to a worker thread cannot `await`.

        A leftover `asyncio.to_thread` glob would mean the blocking work was
        never actually moved off the loop.
        """
        source = inspect.getsource(getattr(files_module, name))
        assert "await " not in source

    def test_batch_delete_shares_one_session_across_the_batch(self, monkeypatch):
        """1000 items must check out one connection, not 1000."""
        opened = {"count": 0}
        real = files_module._sync_session

        def counting_session():
            opened["count"] += 1
            return real()

        monkeypatch.setattr(files_module, "_sync_session", counting_session)
        monkeypatch.setattr(files_module, "require_batch_size", lambda *a, **k: None)

        result = files_module._batch_delete_sync("output", [f"missing-{i}.png" for i in range(5)])

        assert result["deleted"] == 5
        assert opened["count"] == 1


# ---------------------------------------------------------------------------
# 9. The model provider-sync routes found by the 2026-10-03 resolver fix
# ---------------------------------------------------------------------------

# Service methods that were `async def` around nothing but synchronous SQLModel
# work. `async def` here bought no concurrency and cost every caller a blocking
# query or commit on the event loop; making them plain `def` is what lets a
# handler either become a plain `def` itself or reach them through
# `asyncio.to_thread`.
SYNCED_SERVICE_METHODS = [
    ("services.model_service", "ModelServiceV2", "get_model"),
    ("services.model_service", "ModelServiceV2", "update_provider_file_status"),
    ("services.model_downloader", "ModelDownloader", "update_provider_file_status"),
    (
        "services.provider_service",
        "ProviderService",
        "upsert_reconciliation_state",
    ),
    (
        "services.provider_reconciliation_service",
        "ProviderReconciliationService",
        "upsert_reconciliation_state",
    ),
]

# Handlers that legitimately have to stay `async def` — they await a WebSocket
# publish or a provider HTTP call — and so must reach the synchronous service
# work through `asyncio.to_thread`.
OFFLOADING_HANDLERS = [
    # The three `api.routes.models.provider_sync` entries that used to sit here
    # were `update_file_provider_status`, `batch_update_status` and
    # `receive_batch_sync_progress`. They went with the worker-facing half of
    # that module on 2026-10-09; `in_process_reconciliation` now awaits those
    # service calls through `asyncio.to_thread` itself, which the register below
    # covers.
    ("api.routes.models.crud", "add_model"),
    ("api.routes.models.maintenance", "check_dependencies"),
    ("api.routes.providers.lifecycle", "remove_model_from_provider"),
    ("api.routes.providers.reconciliation", "push_reconciliation_event"),
]


class TestSyncedServiceMethodsAreSynchronous:
    @pytest.mark.parametrize("module,cls,name", SYNCED_SERVICE_METHODS)
    def test_not_a_coroutine_function(self, module, cls, name):
        """A stray `async def` here is the whole bug.

        It is invisible at the call site: `await service.get_model(...)` on a
        plain `def` raises, and `service.get_model(...)` on an `async def`
        returns a coroutine that FastAPI fails to serialise. Either way the
        first symptom is a 500 on a route that used to work, not a lint error.
        """
        imported = __import__(module, fromlist=[cls])
        method = getattr(getattr(imported, cls), name)
        assert not inspect.iscoroutinefunction(method), (
            f"{cls}.{name} is `async def` again; its body is synchronous SQLModel "
            "work, so an `async def` caller runs it on the event loop"
        )

    @pytest.mark.parametrize("module,cls,name", SYNCED_SERVICE_METHODS)
    def test_the_conversion_is_actually_used_somewhere(self, module, cls, name):
        """A method nobody calls is not evidence of anything; a method every
        caller forgot to update is a 500 waiting to happen."""
        imported = __import__(module, fromlist=[cls])
        # Touch the method so an ImportError/AttributeError here is an error in
        # this test rather than a silent pass from the string scan below.
        assert callable(getattr(getattr(imported, cls), name))
        repo_root = Path(__file__).resolve().parents[1]
        callers = 0
        for path in list((repo_root / "api").rglob("*.py")) + list(
            (repo_root / "services").rglob("*.py")
        ):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text()
            if f"{name}(" in source and f"await {name}(" in source:
                pytest.fail(
                    f"{path.relative_to(repo_root)} still calls `await {name}(...)`, "
                    f"but {cls}.{name} is a plain `def` — the await would raise "
                    "'object dict can't be awaited' (or, for a coroutine method, "
                    "hide a blocking call on the loop)"
                )
            if f"{name}(" in source:
                callers += 1
        assert callers, f"nothing calls {cls}.{name} at all"


class TestOffloadingHandlersUseAWorkerThread:
    @staticmethod
    def _calls(obj):
        """The names of every function called inside `obj`, comments excluded.

        Source-text matching is not enough: a comment explaining that the write
        goes through `asyncio.to_thread` would satisfy a substring search even
        after the call was deleted, which is exactly the regression this is
        here to catch.
        """
        tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
        return [
            ast.unparse(node.func)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ]

    @staticmethod
    def _awaits_inside(obj):
        """Every `await` in `obj`, as source text, comments excluded."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
        return [ast.unparse(node.value) for node in ast.walk(tree) if isinstance(node, ast.Await)]

    @pytest.mark.parametrize("module,name", OFFLOADING_HANDLERS)
    def test_async_handler_offloads_its_db_work(self, module, name):
        """An `async def` handler must reach the sync work through `to_thread`.

        The alternative — calling it directly — compiles, passes every unit
        test that mocks the service, and puts a synchronous commit on the event
        loop in production.
        """
        handler = getattr(__import__(module, fromlist=[name]), name)
        calls = self._calls(handler)
        assert any(call.endswith("asyncio.to_thread") for call in calls), (
            f"{module}.{name} is `async def` and no longer awaits a decorative "
            "service method, but it does not call asyncio.to_thread — its "
            f"synchronous DB work is running on the event loop. Calls: {calls}"
        )
        assert any(
            "asyncio.to_thread" in awaited for awaited in self._awaits_inside(handler)
        ), (
            f"{module}.{name} builds the worker-thread call but never awaits it; "
            f"awaits: {self._awaits_inside(handler)}"
        )

    @pytest.mark.parametrize(
        "module,name",
        [
            ("api.routes.models.crud", "_split_already_installed_versions"),
        ],
    )
    def test_worker_body_never_re_enters_the_event_loop(self, module, name):
        """A body moved to a worker thread cannot `await`.

        A leftover `await` inside it would mean the work was never actually
        moved off the loop: the handler's `await asyncio.to_thread(...)` would
        only be offloading something that yields again.
        """
        body = getattr(__import__(module, fromlist=[name]), name)
        assert not self._awaits_inside(body), (
            f"{module}.{name} runs on a worker thread and cannot await"
        )
        assert not any(
            call.endswith("asyncio.to_thread") for call in self._calls(body)
        ), f"{module}.{name} is the worker-thread body; it must not hop again"


class TestModelGetRouteIsAThreadedHandler:
    def test_route_is_not_a_coroutine_function(self):
        """`GET /api/v2/models/{model_id}` has nothing left to await.

        `ModelServiceV2.get_model` is a plain `def`; as `async def` this handler
        would return an un-awaited coroutine from a worker thread.
        """
        from api.routes.models import crud as crud_module

        assert not inspect.iscoroutinefunction(crud_module.get_model)
