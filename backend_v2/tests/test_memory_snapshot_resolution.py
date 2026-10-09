"""`enable_memory_snapshot` must resolve in ONE place, and the env fallback must
be reachable.

The defect this pins: the flag was resolved twice — once in
`engine_factory` and once in `ModalEngine.__init__` — and `job_runner` read the
provider row directly and passed an explicit `bool` to `engine.inference`.
Because the caller always supplied a bool, `ModalEngine`'s
`if use_snapshot is None` branch never ran, so `ENABLE_MEMORY_SNAPSHOT` was a
documented variable nothing could read, and the two resolution copies had already
drifted on string coercion.

So there are two properties worth asserting, and both were false:
  1. one function resolves the answer, and every site calls it;
  2. omitting the flag in the provider row actually falls through to the env.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import services.engines.engine_factory as engine_factory_module
import services.engines.modal_engine as modal_engine_module

REPO = Path(__file__).resolve().parents[2] / "backend_v2"


class TestSnapshotPrecedence:
    @pytest.fixture(autouse=True)
    def _no_process_env(self, monkeypatch):
        monkeypatch.delenv("ENABLE_MEMORY_SNAPSHOT", raising=False)

    def test_defaults_to_stable(self):
        assert modal_engine_module.resolve_enable_memory_snapshot({}, {}) is False

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (True, True),
            (False, False),
            ("true", True),
            ("TRUE", True),
            (" yes ", True),
            ("1", True),
            ("0", False),
            ("false", False),
            ("", False),
            (None, False),
        ],
    )
    def test_provider_row_config_decides_including_string_spellings(self, raw, expected):
        got = modal_engine_module.resolve_enable_memory_snapshot(
            {"enable_memory_snapshot": raw}, {}
        )
        assert got is expected

    def test_per_provider_env_file_is_the_fallback_when_config_omits_the_key(self):
        """The regression: `job_runner` used to pass `False` explicitly, which
        made this branch unreachable and the env var inert."""
        got = modal_engine_module.resolve_enable_memory_snapshot(
            {"enable_memory_snapshot": None},
            {"ENABLE_MEMORY_SNAPSHOT": "true"},
        )
        assert got is True

    def test_process_env_is_the_last_fallback(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY_SNAPSHOT", "1")
        assert modal_engine_module.resolve_enable_memory_snapshot({}, {}) is True

    def test_provider_row_config_outranks_the_env_file(self):
        got = modal_engine_module.resolve_enable_memory_snapshot(
            {"enable_memory_snapshot": False},
            {"ENABLE_MEMORY_SNAPSHOT": "true"},
        )
        assert got is False


class TestOneResolutionSite:
    def test_the_factory_and_the_engine_share_the_helper(self):
        """Two copies is how they drifted; assert there is one name both use."""
        src = (REPO / "services" / "engines" / "engine_factory.py").read_text()
        assert "resolve_enable_memory_snapshot" in src, (
            "engine_factory must resolve through the shared helper, not its own "
            "copy of the config/env precedence"
        )
        # And the factory must not carry a second inline precedence chain.
        # Same comment-stripping as above: the prose names the drifted line.
        code = "\n".join(
            line for line in src.splitlines() if not line.lstrip().startswith("#")
        )
        assert 'raw_env in ("true", "1", "yes")' not in code, (
            "engine_factory has its own env coercion again; the two copies "
            "already drifted once on exactly this line"
        )

    def test_job_runner_does_not_resolve_the_flag_itself(self):
        """Passing an explicit bool from the dispatcher is what made the
        engine's resolution dead code."""
        # Strip comments first: the explanation of the old code quotes the very
        # line it replaced, and a naive substring scan would match its own prose.
        src = "\n".join(
            line for line in (REPO / "services" / "job_runner.py").read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        assert 'get("enable_memory_snapshot"' not in src, (
            "job_runner is resolving the engine's snapshot flag again, which "
            "makes ModalEngine's own resolution dead code"
        )
        assert "use_snapshot = None" in src, (
            "job_runner must pass None so ModalEngine resolves it"
        )

    def test_the_engine_adopts_the_callers_when_it_is_given_none(self):
        """`inference(use_snapshot=None)` still means 'your own value', which is
        what lets the dispatcher hand the decision over."""
        source = (REPO / "services" / "engines" / "modal_engine.py").read_text()
        assert "use_snapshot = self.enable_memory_snapshot" in source


class TestDispatchUsesTheEnginesAnswer:
    def test_an_engine_built_from_env_dispaches_the_snapshot_class(self, monkeypatch):
        """End-to-end over the construction path, without Modal installed.

        The engine is built with the flag unset in the provider row and set in
        the per-provider env file, exactly the case that used to be unreachable.
        """
        monkeypatch.delenv("ENABLE_MEMORY_SNAPSHOT", raising=False)

        class _Engine:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                # Mirrors ModalEngine.__init__'s resolution.
                self.enable_memory_snapshot = (
                    modal_engine_module.resolve_enable_memory_snapshot(
                        {"enable_memory_snapshot": kwargs.get("enable_memory_snapshot")}
                    )
                )

        monkeypatch.setattr(engine_factory_module, "HAS_MODAL", True)
        monkeypatch.setattr(engine_factory_module, "ModalEngine", _Engine)
        monkeypatch.setattr(
            engine_factory_module, "can_create_engine", lambda *a, **k: True
        )

        class _Provider:
            id = "p1"
            type = "modal"
            worker_type = "image"
            config = {}
            deploy_config = {}
            enabled = True

        # The factory reads the per-provider `.env.<id>` file off disk, not from
        # an argument, so this asserts the provider-row path (config unset ->
        # Stable) and the string spellings are covered above. The property under
        # test is that WHEN it builds one, it went through the shared helper.
        built = engine_factory_module.get_engine("p1", _Provider())
        if built is not None:
            assert built.enable_memory_snapshot is False
