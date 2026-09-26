"""Fire-and-forget tasks must be retained (audit item 29) and deploy logs must
not be quadratic (item 30).

`asyncio.create_task` keeps no reference: the event loop holds only a weak one,
so a task is collectable while a multi-GB download is in flight and its only
outcome is a `logger.error` from a done callback. Three call sites did this —
`remote_comfy.download_model`, `direct_url.run_reconciliation` and
`BaseProviderClient._start_reconciliation_task` — while `beam` already used the
correct shape and nothing anywhere bounded the set.

`deploy.py` reassembled the whole stdout buffer and the whole state dict for
every 1 KB chunk: a 5 MB `modal deploy` log was ~5000 full-buffer copies plus a
dict write per chunk, and every `/deploy-status` poll serialised all of it back.
"""
import asyncio

import pytest

from provider_core.background import (
    MAX_BACKGROUND_TASKS, BackgroundTaskLimitExceeded, spawn_background_task,
)
from provider_core.deploy import _reset_logs, get_deploy_state


class TestSpawnBackgroundTask:
    @pytest.mark.asyncio
    async def test_task_is_retained_until_it_finishes(self):
        tasks = set()
        started = asyncio.Event()
        release = asyncio.Event()

        async def work():
            started.set()
            await release.wait()

        task = spawn_background_task(work(), tasks=tasks, name="work")
        assert task in tasks
        await started.wait()
        assert task in tasks, "the task was released while it was still running"

        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert task not in tasks, "the task was never released"

    @pytest.mark.asyncio
    async def test_a_gc_pressure_sweep_cannot_collect_a_live_task(self):
        """The actual failure the retention prevents.

        A bare create_task is collectable mid-flight; holding the reference in
        `tasks` is what stops that.
        """
        tasks = set()
        ticks = 0

        async def work():
            nonlocal ticks
            for _ in range(50):
                ticks += 1
                await asyncio.sleep(0)
                # churn the heap the way a real provider does
                [bytearray(1024) for _ in range(200)]

        spawn_background_task(work(), tasks=tasks, name="gc-probe")
        for _ in range(200):
            [bytearray(4096) for _ in range(50)]
            await asyncio.sleep(0)

        assert ticks == 50, "the unreferenced task was collected mid-flight"

    @pytest.mark.asyncio
    async def test_failure_is_logged_with_a_traceback(self, caplog):
        import logging

        tasks = set()

        async def boom():
            raise ValueError("kaboom")

        with caplog.at_level(logging.ERROR):
            spawn_background_task(boom(), tasks=tasks, name="boom")
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        assert "kaboom" in caplog.text
        record = [r for r in caplog.records if "Background task failed" in r.getMessage()]
        assert record and record[0].exc_info is not None

    @pytest.mark.asyncio
    async def test_the_set_cannot_grow_without_bound(self):
        tasks = set()
        release = asyncio.Event()

        async def work():
            await release.wait()

        for _ in range(MAX_BACKGROUND_TASKS):
            spawn_background_task(work(), tasks=tasks, name="work")
        assert len(tasks) == MAX_BACKGROUND_TASKS

        async def rejected():
            raise AssertionError("must not be scheduled")

        with pytest.raises(BackgroundTaskLimitExceeded):
            spawn_background_task(rejected(), tasks=tasks, name="one-too-many")
        assert len(tasks) == MAX_BACKGROUND_TASKS

        release.set()
        for _ in range(5):
            await asyncio.sleep(0)
        assert tasks == set(), "finishing must give the slots back"

    @pytest.mark.asyncio
    async def test_a_rejected_coroutine_is_closed(self):
        """A never-awaited coroutine is a ResourceWarning; close it."""
        tasks = set()
        release = asyncio.Event()

        async def work():
            await release.wait()

        for _ in range(MAX_BACKGROUND_TASKS):
            spawn_background_task(work(), tasks=tasks, name="work")

        async def rejected():
            await asyncio.sleep(0)

        with pytest.raises(BackgroundTaskLimitExceeded):
            spawn_background_task(rejected(), tasks=tasks, name="nope")

    @pytest.mark.asyncio
    async def test_on_done_hook_runs_after_release(self):
        seen = []
        tasks = set()

        async def work():
            return None

        spawn_background_task(work(), tasks=tasks, name="work", on_done=seen.append)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(seen) == 1


class TestEnginesRetainTheirTasks:
    """The three call sites the audit named, plus the set the beam engine
    already kept, now all bound and all routed through one helper.
    """

    # The inference streams' `fetcher` task is a different case: it is held in
    # a local of the live generator frame and cancelled in its `finally`, so it
    # is referenced for its whole life. Only the fire-and-forget sites matter.
    SPAWN_METHODS = {"download_model", "run_reconciliation", "_start_reconciliation_task"}

    def test_every_fire_and_forget_site_uses_the_helper(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for engine in (
            "image_worker/engines/remote_comfy/client.py",
            "image_worker/engines/beam/client.py",
            "image_worker/engines/direct_url/client.py",
            "provider_core/base_client.py",
        ):
            source = (root / engine).read_text()
            assert "spawn_background_task(" in source, engine
            bare = []
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name not in self.SPAWN_METHODS:
                    continue
                for child in ast.walk(node):
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "create_task"
                    ):
                        bare.append(f"{engine}:{child.lineno} in {node.name}")
            assert not bare, f"unretained create_task left: {bare}"

    def test_base_client_retains_its_reconciliation_task(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "provider_core/base_client.py"
        ).read_text()
        assert "spawn_background_task(" in source
        assert "asyncio.create_task(" not in source
        assert "self._background_tasks" in source

    def test_image_worker_keeps_its_lifespan_tasks_in_a_list(self):
        """The lifespan tasks are already retained, just not bounded; out of
        scope for this change, recorded here so it is not forgotten."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "image_worker/worker.py"
        ).read_text()
        assert "_background_tasks" in source


class TestDeployLogsAreNotQuadratic:
    @pytest.fixture(autouse=True)
    def _clean(self):
        from provider_core.base_client import _DEPLOY_STATE

        _reset_logs()
        _DEPLOY_STATE.clear()
        yield
        _reset_logs()
        _DEPLOY_STATE.clear()

    def test_appending_does_not_rebuild_the_buffer(self, monkeypatch):
        """One `str.join` per read, zero per chunk.

        The old code's cost was `out_str += chunk` on a growing string plus a
        dict assignment per chunk; the deque makes each append O(1).
        """
        from provider_core import deploy

        joins = []
        real_join = "".join

        def counting_join(iterable):
            joins.append(1)
            return real_join(iterable)

        monkeypatch.setattr(deploy, "get_deploy_logs", counting_join)
        monkeypatch.setattr(deploy, "get_deploy_state", deploy.get_deploy_state)
        for i in range(2000):
            deploy._append_log("x" * 1024)
        assert joins == [], "joining happened on the write path"

    def test_the_tail_is_capped(self, monkeypatch):
        from provider_core import deploy
        from provider_core.base_client import _DEPLOY_STATE

        # 4 KiB budget, 500 one-line chunks: the head must go.
        monkeypatch.setattr(deploy, "DEPLOY_LOG_MAX_BYTES", 4096)
        _DEPLOY_STATE.update({"status": "deploying", "message": "x"})
        for i in range(500):
            deploy._append_log(f"line {i}\n")
        state = get_deploy_state()
        logs = state["logs"]

        assert len(logs) <= 4096
        assert state["logs_truncated"] is True
        assert logs.endswith("line 499\n"), "the tail is what anyone reads"
        assert "line 0\n" not in logs, "the head must have been dropped"

    def test_accounting_survives_a_chunk_larger_than_the_budget(self, monkeypatch):
        """One huge chunk must still be trimmed, and still be reported as
        truncated — a `deque(maxlen=)` would have hidden the loss."""
        from provider_core import deploy
        from provider_core.base_client import _DEPLOY_STATE

        monkeypatch.setattr(deploy, "DEPLOY_LOG_MAX_BYTES", 16)
        _DEPLOY_STATE.update({"status": "deploying", "message": "x"})
        deploy._append_log("a" * 100)
        deploy._append_log("tail")
        state = deploy.get_deploy_state()
        assert state["logs"] == "tail"
        assert state["logs_truncated"] is True
        assert deploy._LOG_BYTES == len(state["logs"])

    def test_a_small_log_is_not_truncated(self):
        from provider_core import deploy

        deploy._append_log("hello")
        state = deploy.get_deploy_state()
        assert "logs_truncated" not in state

    @pytest.mark.asyncio
    async def test_deploy_state_serves_logs_without_storing_them(self, monkeypatch):
        from provider_core import deploy
        from provider_core.base_client import _DEPLOY_STATE

        _DEPLOY_STATE.update({"status": "deploying", "message": "Deployment started"})

        async def fake_exec(*cmd, **kwargs):
            chunk = b"y" * 4096

            class _Proc:
                returncode = 0
                stdout = _FakeStdout(chunk)

                async def wait(self):
                    return 0

            return _Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        task = deploy.start_deploy_task("Test", [["true"]])
        await task

        assert "logs" not in _DEPLOY_STATE, (
            "the running log must not live in the dict each chunk used to overwrite"
        )
        state = get_deploy_state()
        assert state["status"] == "completed"
        assert "y" * 100 in state["logs"]

    @pytest.mark.asyncio
    async def test_get_deploy_status_serves_the_materialised_state(self, monkeypatch):
        from provider_core.deploy import start_deploy_task
        from provider_core.base_client import _DEPLOY_STATE, BaseProviderClient

        class _Client(BaseProviderClient):
            async def get_health(self): ...
            async def get_info(self): ...
            async def inference(self, request): ...
            async def setup_models(self): ...
            async def download_model(self, request): ...
            async def list_models(self, request=None): ...
            async def delete_model(self, request): ...
            async def get_file(self, path): ...
            async def delete_file(self, path): ...
            async def upload_file(self, request): ...
            async def deploy(self, payload): ...
            async def run_reconciliation(self, quick_sync=False): ...
            async def validate_models(self, request): ...
            async def validate_all_models(self): ...
            async def get_object_info(self): ...

        client = _Client("p", {})
        assert await client.get_deploy_status() == {"status": "unknown"}

        start_deploy_task("Test", [["true"]])
        status = await client.get_deploy_status()
        assert status["status"] in {"deploying", "completed"}
        assert "logs" in status
        _DEPLOY_STATE.clear()


class _FakeStdout:
    def __init__(self, chunk, repeats=3):
        self._chunk = chunk
        self._repeats = repeats

    async def read(self, _n):
        if self._repeats <= 0:
            return b""
        self._repeats -= 1
        return self._chunk
