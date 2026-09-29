"""The three things that make a ComfyUI container survive a run — and the TTS
app's divergence from both image apps in all three.

`image_worker` and `llm_worker` each had their own copy of these. `tts_worker`
had none of the first two and a `_restart` that called `/free`, logged
"requesting container recycle", and recycled nothing — so a function whose
comment described behaviour it did not implement, under a class attribute
(`_completed_runs`) that only ever reached it.

They now live in `provider_core/comfy_lifecycle.py`, which imports no provider
SDK. That is the point: the image app's copies could not be tested here, so the
TTS app could not have reused them (it documents that it must not import the
image worker's module graph — a shared import drags the image stack into the
speech container, which is the cost the separation exists to avoid) and did not.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from provider_core import comfy_lifecycle

PROVIDER_ROOT = pathlib.Path(__file__).resolve().parents[1]
TTS_APP = PROVIDER_ROOT / "tts_worker" / "engines" / "modal" / "modal_app.py"
IMAGE_APP = PROVIDER_ROOT / "image_worker" / "engines" / "modal" / "modal_app.py"
LLM_APP = PROVIDER_ROOT / "llm_worker" / "engines" / "modal" / "modal_app.py"

_run_source = None


def _tts_module():
    import importlib

    return importlib.import_module("tts_worker.engines.modal.modal_app")


def _tts_worker_class():
    return _tts_module().TTSWorker._get_user_cls()


# ------------------------------------------------------------------ the helpers


@pytest.fixture
def fake_psutil(monkeypatch):
    """`psutil` is a Modal-image dependency, not a provider-venv one. The probe
    is worth testing anyway — it is the step whose failure mode ("found nothing,
    skipped the kill, called it a restart") is invisible in the logs."""
    import sys
    import types

    module = types.ModuleType("psutil")
    module.net_connections = lambda kind: []
    monkeypatch.setitem(sys.modules, "psutil", module)
    return module


class TestFreeComfyVram:
    def test_it_asks_the_subprocess_rather_than_its_own_cuda_context(self, monkeypatch):
        """The failure this shape exists to prevent: ComfyUI runs in a separate
        OS process, so a `torch.cuda.*` call in the Modal function empties the
        wrong context and the model's VRAM is never given back."""
        calls = {}

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

        def fake_post(url, json=None, timeout=None):
            calls["url"] = url
            calls["json"] = json
            calls["timeout"] = timeout
            return _Resp()

        monkeypatch.setattr("requests.post", fake_post)

        comfy_lifecycle.free_comfy_vram(8199, "TTSWorker")

        assert calls["url"] == "http://127.0.0.1:8199/free"
        assert calls["json"] == {"unload_models": True, "free_memory": True}

    def test_a_failed_free_is_logged_not_raised(self, monkeypatch):
        """A `/free` that times out must not fail the run that just succeeded."""
        def boom(*a, **k):
            raise OSError("connection refused")

        monkeypatch.setattr("requests.post", boom)
        lines = []

        comfy_lifecycle.free_comfy_vram(8199, "TTSWorker", log=lines.append)

        assert any("/free call failed" in line for line in lines)


class TestRestartKillsTheProcessItFinds:
    def test_it_kills_by_pid_and_confirms_death_before_starting(self, monkeypatch):
        """The bug the confirmed-dead wait exists to prevent: SIGTERM then an
        immediate respawn, whose readiness probe regularly catches the OLD
        still-dying process answering 200. The "restart" then keeps the process
        it was meant to replace, and the new one dies on "port in use"."""
        import signal as signal_mod

        killed: list[tuple[int, int]] = []
        started: list[str] = []

        monkeypatch.setattr(
            comfy_lifecycle, "find_pids_on_port", lambda port, label, log=None: [11, 22]
        )
        # `wait_for_pids_gone` returns True when they are gone. The first call
        # says they are NOT gone, which is what forces the SIGKILL branch.
        gone = iter([False, True])
        monkeypatch.setattr(
            comfy_lifecycle, "wait_for_pids_gone",
            lambda pids, timeout_seconds=0: next(gone),
        )
        monkeypatch.setattr(comfy_lifecycle, "wait_for_port_closed", lambda *a, **k: True)
        monkeypatch.setattr(
            comfy_lifecycle.os, "kill", lambda pid, sig: killed.append((pid, sig))
        )
        monkeypatch.setattr(comfy_lifecycle.os.path, "exists", lambda p: True)

        comfy_lifecycle.restart_comfy_process(
            8199,
            "TTSWorker",
            start=lambda: started.append("start"),
            wait_for_ready=lambda: started.append("ready"),
        )

        assert killed == [(11, signal_mod.SIGTERM), (22, signal_mod.SIGTERM),
                          (11, signal_mod.SIGKILL), (22, signal_mod.SIGKILL)]
        # Nothing is started until the kills have been issued and waited out.
        assert started == ["start", "ready"]

    def test_a_pid_that_is_already_gone_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(comfy_lifecycle, "find_pids_on_port", lambda *a, **k: [33])
        monkeypatch.setattr(comfy_lifecycle, "wait_for_pids_gone", lambda *a, **k: True)
        monkeypatch.setattr(comfy_lifecycle, "wait_for_port_closed", lambda *a, **k: True)

        def gone(pid, sig):
            raise ProcessLookupError(pid)

        monkeypatch.setattr(comfy_lifecycle.os, "kill", gone)
        started = []
        comfy_lifecycle.restart_comfy_process(
            8199, "T", start=lambda: started.append(1), wait_for_ready=lambda: None
        )
        assert started == [1]

    def test_a_port_still_bound_is_reported_rather_than_silently_ignored(self, monkeypatch):
        """A restart that collides is the failure this whole function is for, so
        it has to be visible in the log rather than swallowed."""
        lines = []
        monkeypatch.setattr(comfy_lifecycle, "find_pids_on_port", lambda *a, **k: [])
        monkeypatch.setattr(comfy_lifecycle, "wait_for_pids_gone", lambda *a, **k: True)
        monkeypatch.setattr(comfy_lifecycle, "wait_for_port_closed", lambda *a, **k: False)

        comfy_lifecycle.restart_comfy_process(
            8199, "TTSWorker", start=lambda: None, wait_for_ready=lambda: None,
            log=lines.append,
        )

        assert any("still bound" in line for line in lines), lines

    def test_find_pids_reads_the_socket_table(self, monkeypatch, fake_psutil):
        """Not cmdline matching: `comfy-cli` daemonizes under a cmdline with no
        "ComfyUI/main.py" in it, so `pgrep -f` matched nothing and every restart
        skipped the kill entirely."""
        class _Conn:
            def __init__(self, port, pid):
                self.laddr = type("A", (), {"port": port})()
                self.pid = pid

        monkeypatch.setattr(
            fake_psutil, "net_connections",
            lambda kind: [_Conn(8199, 5), _Conn(443, 6), _Conn(8199, 7)],
        )

        assert comfy_lifecycle.find_pids_on_port(8199) == [5, 7]

    def test_a_probe_that_cannot_answer_finds_nothing_rather_than_raising(self, monkeypatch, fake_psutil):
        def boom(kind):
            raise PermissionError("net_connections needs root in this container")

        monkeypatch.setattr(fake_psutil, "net_connections", boom)
        lines = []

        assert comfy_lifecycle.find_pids_on_port(8199, "T", log=lines.append) == []
        assert any("psutil.net_connections failed" in line for line in lines)


# ------------------------------------------------------------------- the wiring


class TestTheTTSAppRunsTheFullLifecycle:
    def _run_source(self) -> str:
        return TTS_APP.read_text(encoding="utf-8")

    def test_it_reloads_the_volume_before_each_run(self):
        src = self._run_source()
        run = src[src.index("async def run(self, workflow_json"):]
        run = run[: run.index("async def _execute")]
        assert "safe_vol_reload_aio" in run, (
            "a file another container uploaded after this one started is "
            "invisible without it, so a cloned voice fails on a file that is there"
        )
        # First statement, before the graph is submitted.
        assert run.index("safe_vol_reload_aio") < run.index("self._execute")

    def test_it_frees_vram_after_each_run(self):
        src = self._run_source()
        run = src[src.index("async def run(self, workflow_json"):]
        run = run[: run.index("async def _execute")]
        assert "free_comfy_vram" in run
        assert run.index("self._completed_runs += 1") < run.index("free_comfy_vram")

    def test_the_restart_actually_replaces_the_process(self):
        src = self._run_source()
        restart = src[src.index("    def _restart(self)"):]
        restart = restart[: restart.index("\n# ---")]
        assert "restart_comfy_process" in restart
        assert "_start_comfy(self.port)" in restart, (
            "a restart that does not start a replacement is the exact shape it "
            "replaced: a /free call and a log line"
        )
        src_all = TTS_APP.read_text(encoding="utf-8")
        assert 'logger.info("[tts] requesting container recycle")' not in src_all, (
            "the log line claimed a Modal container recycle. `MAX_CONTAINERS` is "
            "1, so there is no second container to evict and nothing to wait for"
        )
        code = restart[restart.index('"""', restart.index('"""') + 3) + 3:]
        assert "/free" not in code, (
            "the old restart's only real action was a /free call, which is now "
            "done after every run"
        )

    def test_the_restart_threshold_is_a_named_knob_not_a_literal(self):
        assert "MAX_RUNS_BEFORE_RESTART" in self._run_source()
        assert _tts_module().MAX_RUNS_BEFORE_RESTART > 0

    @pytest.mark.asyncio
    async def test_running_n_times_replaces_the_process_exactly_once(self, monkeypatch):
        """The behaviour, not the source: N successful runs, one restart, and a
        VRAM free after each."""
        cls = _tts_worker_class()
        worker = object.__new__(cls)
        worker.port = 8199
        worker._completed_runs = 0

        restarts: list[int] = []
        frees: list[int] = []
        reloads: list[int] = []

        def fake_restart():
            # `run` calls this through `asyncio.to_thread`, so it must be sync.
            restarts.append(worker._completed_runs)

        async def fake_execute(workflow):
            for _ in range(2):
                yield {"status": "running", "prompt_id": "p"}

        monkeypatch.setattr(cls, "_restart", staticmethod(fake_restart))
        monkeypatch.setattr(cls, "_execute", staticmethod(fake_execute))
        monkeypatch.setattr(
            _tts_module(), "safe_vol_reload_aio", lambda: _noop(reloads.append(1))
        )
        monkeypatch.setattr(
            _tts_module(), "free_comfy_vram", lambda *a, **k: frees.append(1)
        )
        monkeypatch.setattr(_tts_module(), "MAX_RUNS_BEFORE_RESTART", 3)

        for _ in range(3):
            async for _event in worker.run({"prompt": {}}):
                pass

        assert restarts == [], "restarted before the threshold"
        assert len(frees) == 3, "one VRAM free per run"
        assert len(reloads) == 3, "one volume reload per run"

        async for _event in worker.run({"prompt": {}}):
            pass

        assert restarts == [3], restarts
        assert len(frees) == 4

    @pytest.mark.asyncio
    async def test_a_failing_run_still_frees_vram(self, monkeypatch):
        """A graph ComfyUI rejects still leaves whatever it loaded behind, and
        the next job runs in the same process."""
        cls = _tts_worker_class()
        worker = object.__new__(cls)
        worker.port = 8199
        worker._completed_runs = 0

        frees: list[int] = []
        monkeypatch.setattr(
            cls, "_execute",
            staticmethod(lambda workflow: _agen([{"status": "error", "message": "no", "retryable": False}])),
        )
        monkeypatch.setattr(_tts_module(), "safe_vol_reload_aio", lambda: _noop(None))
        monkeypatch.setattr(_tts_module(), "free_comfy_vram", lambda *a, **k: frees.append(1))
        monkeypatch.setattr(_tts_module(), "MAX_RUNS_BEFORE_RESTART", 99)

        async for _event in worker.run({"prompt": {}}):
            pass

        assert frees == [1]


def _noop(result):
    async def _run():
        return result

    return _run()


async def _agen(items):
    for item in items:
        yield item


class TestTheImageAppUsesTheSameHelpers:
    """Not a cosmetic refactor: the TTS app cannot import the image app, so the
    only way both could behave identically was for the behaviour to have one
    owner."""

    def test_it_delegates_instead_of_reimplementing(self):
        src = IMAGE_APP.read_text(encoding="utf-8")
        for name in ("find_pids_on_port", "free_comfy_vram", "restart_comfy_process",
                     "wait_for_pids_gone", "wait_for_port_closed"):
            assert f"{name}(" in src, f"image app does not use the shared {name}"
            assert f"def {name}(" not in src, (
                f"image app has its own {name}; the TTS app cannot import this "
                "module, so a second implementation is how they drift"
            )

    @pytest.mark.parametrize("app", [TTS_APP, IMAGE_APP], ids=["tts", "image"])
    def test_neither_app_ships_its_own_pid_finder(self, app):
        """One implementation of the socket-table probe, not three."""
        src = app.read_text(encoding="utf-8")
        assert "psutil.net_connections" not in src, (
            f"{app.name} has a second copy of the PID probe; they will drift"
        )

    def test_the_llm_app_never_ran_comfyui(self):
        """Context for the reader: the LLM app has a `safe_vol_reload` but no
        ComfyUI process, so it is not a third copy to reconcile."""
        src = LLM_APP.read_text(encoding="utf-8")
        assert "psutil.net_connections" not in src
        assert "/free" not in src


class TestTheSharedHelpersImportNothingFromAProvider:
    def test_no_provider_sdk_is_imported(self):
        """This is what makes the logic testable in the provider venv at all."""
        src = (PROVIDER_ROOT / "provider_core" / "comfy_lifecycle.py").read_text()
        for forbidden in ("import modal", "import beta9", "from provider_core"):
            assert forbidden not in src, f"comfy_lifecycle must stay SDK-free: {forbidden}"

    def test_psutil_is_a_lazy_import(self):
        """It is absent from the image app's TTS-sibling dependency sets, and a
        top-level import would make this module unimportable without it."""
        src = (PROVIDER_ROOT / "provider_core" / "comfy_lifecycle.py").read_text()
        assert "    import psutil" in src
        assert not src.startswith("import psutil")
        assert os.path.basename(str(comfy_lifecycle.__file__)) == "comfy_lifecycle.py"
