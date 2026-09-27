"""Item 4: `capture_stall_diagnostics` accepted `diagnostics_timeout` and
`max_chars`, and the local wrapper threaded in both from the environment
(`MODAL_COMFYUI_STALL_DIAGNOSTICS_TIMEOUT_SECONDS`,
`MODAL_COMFYUI_STALL_DIAGNOSTICS_MAX_CHARS`) — and the function body used
neither. A parameter that is accepted and ignored is worse than a missing one,
because the .env example documents the knob as if it worked.

Both are now real bounds, and both matter for the same reason: this runs while
the GPU container is already stalled and about to be restarted. An unbounded
trace written into a volume that is already misbehaving, followed by an
unbounded `vol.commit()` on that same volume, turns a stall into the outage.
"""

from __future__ import annotations

import json
import time

import pytest

import image_worker.engines.modal.modal_app as modal_app


class TestTheDetailsAreBounded:
    def test_a_small_trace_is_written_whole(self, tmp_path, monkeypatch):
        monkeypatch.setattr(modal_app, "Path", _PathFactory(tmp_path))
        path = modal_app.capture_stall_diagnostics(
            8188, "ComfyUIStable", {"reason": "workflow_stalled", "elapsed": 300.0}
        )
        body = json.loads((tmp_path / "diagnostics/comfyui_stalls").joinpath(
            path.split("/")[-1]
        ).read_text())
        assert body["stall_details"] == {"reason": "workflow_stalled", "elapsed": 300.0}
        assert body["label"] == "ComfyUIStable"
        assert body["port"] == 8188

    def test_a_huge_trace_is_truncated_rather_than_dropped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(modal_app, "Path", _PathFactory(tmp_path))
        details = {"frames": [f"frame-{i} " * 40 for i in range(5000)]}
        path = modal_app.capture_stall_diagnostics(
            8188, "ComfyUISnapshot", details, max_chars=2000
        )
        written = (tmp_path / "diagnostics/comfyui_stalls").joinpath(path.split("/")[-1]).read_text()
        body = json.loads(written)

        assert body["stall_details"]["truncated"] is True
        assert body["stall_details"]["original_chars"] > 2000
        assert len(body["stall_details"]["details"]) == 2000
        # The head is kept, because that is where the failing frame is. The
        # truncation point is the serialised document, not the first string in it,
        # so the preview starts at the beginning of the JSON.
        assert "frame-0 frame-0" in body["stall_details"]["details"][:200]
        assert len(written) < 6000, "the cap must bound the file, not just one field"

    def test_a_disabled_capture_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(modal_app, "Path", _PathFactory(tmp_path))
        assert modal_app.capture_stall_diagnostics(8188, "x", {"a": 1}, enabled=False) is None
        assert not (tmp_path / "diagnostics").exists()


class TestTheVolumeCommitIsBounded:
    def test_a_commit_that_returns_is_awaited_normally(self):
        calls = []
        modal_app._commit_within(lambda: calls.append(1), 5.0)
        assert calls == [1]

    def test_a_commit_that_never_returns_is_abandoned(self):
        """The point of the bound: this runs during a restart, so waiting on a
        wedged volume sync would hold the restart — the thing the diagnostics
        exist to diagnose."""
        started = time.monotonic()
        modal_app._commit_within(lambda: time.sleep(30), 0.2)
        assert time.monotonic() - started < 5.0, (
            "_commit_within must return at the deadline, not when the commit does"
        )

    def test_a_raising_commit_does_not_escape(self):
        """A diagnostics write must not be able to fail the run it is diagnosing."""

        def _boom():
            raise RuntimeError("volume is on fire")

        modal_app._commit_within(_boom, 1.0)  # must not raise

    def test_capture_still_reports_the_path_when_the_commit_wedges(self, tmp_path, monkeypatch):
        monkeypatch.setattr(modal_app, "Path", _PathFactory(tmp_path))
        path = modal_app.capture_stall_diagnostics(
            8188, "ComfyUIStable", {"a": 1}, diagnostics_timeout=0.2,
            volume_commit_fn=lambda: time.sleep(30),
        )
        assert path, "the file is written; only its durability is unconfirmed"


class _PathFactory:
    """A `Path` stand-in that roots the diagnostic path inside a tmp dir.

    The real function builds `Path("/mnt/data/diagnostics/...")`, which does not
    exist on a test host, and monkeypatching the module global is simpler — and
    less brittle — than making the function take a base path for one test.
    """

    def __init__(self, root):
        self._root = root

    #: The mount prefix the deployed container uses.
    MOUNT = "/mnt/data"

    def __call__(self, *parts):
        from pathlib import Path

        # Re-root, keeping the sub-path: the real call is a single
        # `Path("/mnt/data/diagnostics/comfyui_stalls")` argument, so dropping
        # everything after the first part would flatten the file to the tmp root.
        text = "/".join(str(part) for part in parts)
        if text.startswith(self.MOUNT):
            text = text[len(self.MOUNT):]
        return Path(self._root).joinpath(text.lstrip("/"))


def test_the_wrapper_threads_both_env_knobs_through():
    """The wrapper is where the .env values enter; if it stops passing them, the
    bounds go back to being defaults that nobody chose."""
    import inspect

    source = inspect.getsource(modal_app._capture_stall_diagnostics)
    assert "diagnostics_timeout=COMFYUI_STALL_DIAGNOSTICS_TIMEOUT_SECONDS" in source
    assert "max_chars=COMFYUI_STALL_DIAGNOSTICS_MAX_CHARS" in source
    assert modal_app.COMFYUI_STALL_DIAGNOSTICS_TIMEOUT_SECONDS == 8.0
    assert modal_app.COMFYUI_STALL_DIAGNOSTICS_MAX_CHARS == 12000


@pytest.mark.parametrize(
    "name,attribute",
    [
        ("MODAL_COMFYUI_STALL_DIAGNOSTICS_TIMEOUT_SECONDS", "COMFYUI_STALL_DIAGNOSTICS_TIMEOUT_SECONDS"),
        ("MODAL_COMFYUI_STALL_DIAGNOSTICS_MAX_CHARS", "COMFYUI_STALL_DIAGNOSTICS_MAX_CHARS"),
    ],
)
def test_each_bound_is_documented_in_the_env_example(name, attribute):
    """The knob was documented and did nothing. This pins the two together."""
    from pathlib import Path

    example = (
        Path(__file__).resolve().parents[2] / ".env.example.provider.engines"
    ).read_text()
    assert f"{name}=" in example, f"{name} is not in .env.example.provider.engines"
    assert hasattr(modal_app, attribute)
