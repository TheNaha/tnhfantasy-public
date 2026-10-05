"""The remote agent must not block its own event loop, and must not wait forever.

Two halves, both about the same file:

* **Unbounded synchronous work inside `async def`.** The agent is a single-process
  uvicorn, so one blocking call stops it answering *anything* — `/health`
  included, which is what Docker's healthcheck reads. `/upload-file` decoded
  base64 and wrote the bytes in the coroutine, at a 512 MiB ceiling: a ~384 MiB
  allocation, a large memcpy, and a multi-hundred-megabyte synchronous write to the
  models mount, all on the event loop. `/delete-model` ran `shutil.rmtree` on the
  same mount, which is the volume the Modal and Beam engines are also reading.

* **No deadline on the off-thread calls.** `_bounded_to_thread` bounded concurrency
  and nothing else, so a thread whose peer never answered held its slot, and
  eventually all 32 of them, with no error anywhere — the agent simply stopped.

The event-loop assertions are made by measuring loop responsiveness, not by reading
the source: a test that greps for `to_thread` passes while the next line blocks.
"""

from __future__ import annotations

import asyncio
import os
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AGENT_SERVER = REPO_ROOT / "remote_agent" / "server.py"
AGENT_DOCKERFILE = REPO_ROOT / "remote_agent" / "Dockerfile"


@pytest.fixture
def server(monkeypatch, tmp_path):
    import remote_agent.server as module

    monkeypatch.setattr(module, "DATA_DIR", str(tmp_path))
    return module


class TestUploadFileDoesNotBlockTheLoop:
    @pytest.mark.asyncio
    async def test_a_large_upload_leaves_the_loop_responsive(self, server, monkeypatch):
        payload = os.urandom(6 * 1024 * 1024)
        import base64

        encoded = base64.b64encode(payload).decode()

        # The measurement: a ticker that must keep turning while the upload runs.
        # One turn means the event loop was blocked for the whole upload.
        ticks = 0
        stop = False

        async def _tick():
            nonlocal ticks
            while not stop:
                ticks += 1
                await asyncio.sleep(0)

        ticker = asyncio.ensure_future(_tick())
        try:
            result = await server.upload_file(
                server.UploadFileRequest(
                    filename="input.png", content_base64=encoded, directory="input"
                ),
                _FakeRequest(),
            )
        finally:
            stop = True
            await ticker

        assert result["status"] == "success", result
        assert ticks > 50, (
            f"the event loop only turned {ticks} times during a 6 MB upload; the "
            f"decode and the write are running in the coroutine"
        )
        written = pathlib.Path(server.DATA_DIR) / "input" / "input.png"
        assert written.read_bytes() == payload

    @pytest.mark.asyncio
    async def test_the_write_happens_off_the_loop(self, server):
        """The loop-thread identity, stated directly.

        `asyncio.to_thread` runs the function with no running loop on a worker
        thread; the coroutine runs on the loop thread. Recording
        `threading.get_ident()` from inside the writing function is a precise,
        non-timing statement of where the work ran.
        """
        import base64
        import threading

        encoded = base64.b64encode(b"x" * 4096).decode()
        loop_thread = threading.get_ident()
        seen = {}

        real_open = open

        class _RecordingOpen:
            def __call__(self, path, mode, *args, **kwargs):
                if "wb" in mode:
                    seen["thread"] = threading.get_ident()
                return real_open(path, mode, *args, **kwargs)

        import builtins

        builtins.open = _RecordingOpen()
        try:
            await server.upload_file(
                server.UploadFileRequest(
                    filename="input.png", content_base64=encoded, directory="input"
                ),
                _FakeRequest(),
            )
        finally:
            builtins.open = real_open

        assert seen.get("thread") not in (None, loop_thread), (
            "the write ran on the event loop thread, not on a worker"
        )


class TestDeleteModelDoesNotBlockTheLoop:
    @pytest.mark.asyncio
    async def test_an_rmtree_leaves_the_loop_responsive(self, server, tmp_path):
        tree = tmp_path / "loras"
        tree.mkdir()
        for index in range(300):
            (tree / f"lora-{index:04d}.safetensors").write_bytes(b"x" * 4096)

        ticks = 0
        stop = False

        async def _tick():
            nonlocal ticks
            while not stop:
                ticks += 1
                await asyncio.sleep(0)

        ticker = asyncio.ensure_future(_tick())
        try:
            result = await server.delete_model(
                server.DeleteModelRequest(path="loras")
            )
        finally:
            stop = True
            await ticker

        assert result["status"] == "success", result
        assert not tree.exists()
        assert ticks > 20, (
            f"the event loop only turned {ticks} times during an rmtree of 300 files"
        )


class TestBoundedToThreadHasADeadline:
    """The deadlocked-thread hazard is also a test hazard.

    `threading.Event().wait()` with no timeout models "the peer never answers"
    perfectly, and then blocks interpreter shutdown forever, because the loop's
    `shutdown_default_executor` waits for every worker thread. So the thread here
    waits on an event the *test* releases once the deadline has been observed: the
    deadline fires at 0.1s while the thread cannot finish before the test sets the
    event, which makes the assertion deterministic rather than a race.
    """

    @pytest.mark.asyncio
    async def test_a_call_that_does_not_return_raises(self, server):
        import threading

        release = threading.Event()

        def _never():
            release.wait(30)

        try:
            with pytest.raises(server.ThreadCallTimeout):
                await server._bounded_to_thread(_never, timeout_seconds=0.1)
        finally:
            release.set()

    @pytest.mark.asyncio
    async def test_the_message_names_the_call_and_the_limit(self, server):
        import threading

        release = threading.Event()

        def _never():
            release.wait(30)

        try:
            with pytest.raises(server.ThreadCallTimeout) as raised:
                await server._bounded_to_thread(_never, timeout_seconds=0.1)
        finally:
            release.set()

        message = str(raised.value)
        assert "_never" in message, message
        assert "0.1" in message, message

    @pytest.mark.asyncio
    async def test_a_call_that_finishes_returns_its_value(self, server):
        """The control: a deadline must not turn every call into a failure."""
        assert await server._bounded_to_thread(lambda: 42, timeout_seconds=5) == 42

    @pytest.mark.asyncio
    async def test_a_call_that_finishes_late_still_returns(self, server):
        import time as _time

        def _slow():
            _time.sleep(0.15)
            return "done"

        assert await server._bounded_to_thread(_slow, timeout_seconds=5) == "done"

    @pytest.mark.asyncio
    async def test_the_gate_is_released_after_a_timeout(self, server):
        """Otherwise the abandoned thread's slot is lost as well, and the pool
        shrinks by one on every timeout."""
        import threading

        release = threading.Event()

        def _never():
            release.wait(30)

        try:
            for _ in range(3):
                with pytest.raises(server.ThreadCallTimeout):
                    await server._bounded_to_thread(_never, timeout_seconds=0.1)
            assert await server._bounded_to_thread(lambda: "alive", timeout_seconds=5) == "alive"
        finally:
            release.set()

    @pytest.mark.asyncio
    async def test_a_zero_timeout_disables_the_deadline(self, server):
        def _quick():
            return "unbounded"

        assert await server._bounded_to_thread(_quick, timeout_seconds=0) == "unbounded"

    def test_the_default_deadline_exceeds_the_longest_legitimate_call(self):
        """A download is the longest thing the agent does, and its own budget is
        `DOWNLOAD_TIMEOUT`. A default below that would abort real transfers."""
        import remote_agent.server as module

        assert module.THREAD_CALL_TIMEOUT_SECONDS > module.DOWNLOAD_TIMEOUT


class TestTheHealthcheckReadsThePortTheAppListensOn:
    """`server.py` reads `os.getenv("PORT", "8001")`; a literal `8001` in the
    healthcheck reports a container unhealthy forever when they disagree."""

    def test_the_healthcheck_expands_port(self):
        source = AGENT_DOCKERFILE.read_text()
        healthcheck = [
            line for line in source.splitlines() if "urlopen" in line or "HEALTHCHECK" in line
        ]
        assert healthcheck, "the agent Dockerfile has no healthcheck any more"

        probe = " ".join(healthcheck)
        assert "localhost:8001" not in probe, (
            f"the agent healthcheck still hardcodes 8001: {probe}"
        )
        assert "PORT" in probe, (
            f"the agent healthcheck does not read $PORT: {probe}"
        )

    @pytest.mark.parametrize(
        "dockerfile",
        [
            "provider_containers/image_worker/Dockerfile",
            "provider_containers/llm_worker/Dockerfile",
            "provider_containers/tts_worker/Dockerfile",
        ],
    )
    def test_every_container_in_the_tier_agrees(self, dockerfile):
        """The agent was the only one of four. This is what makes the fourth copy
        of the bug impossible to reintroduce silently."""
        source = (REPO_ROOT / dockerfile).read_text()
        probe = " ".join(
            line for line in source.splitlines() if "urlopen" in line or "HEALTHCHECK" in line
        )
        assert "localhost:%s" in probe or "os.environ" in probe, probe


class _FakeRequest:
    """The `http_request` argument `/upload-file` reads Content-Length from."""

    class _Headers(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    def __init__(self):
        self.headers = self._Headers()