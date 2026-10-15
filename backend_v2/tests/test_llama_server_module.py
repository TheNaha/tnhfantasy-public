"""The sidecar's llama.cpp worker, and why it is shaped like the Modal app.

`WORKER_MODE=llm` used to be a proxy and nothing else. The backend's
`RemoteLLMEngine` therefore managed a models tree it did not serve, while
`ModalLlamaCPPEngine` served from the tree it managed — so a `remote_llm` provider
could show a populated models directory while generation read from somewhere else
entirely.

The worker now launches llama-server itself, driven by the SAME
`backend_v2/modal_llm/models.json` the Modal app reads. These tests pin the two
properties that make it equivalent rather than merely similar: it parses the real
registry, and it launches by DISTINCT model so the shared-model setting does not
start the same GGUF twice.

No test downloads a weight or launches a real llama-server; the launch path is
exercised through a fake, and the registry assertions run against the actual file.
"""

import json
import sys
import pytest

from repo_paths import require_repo_root

# `llama_server` lives in `remote_agent/`, which is a deliberately standalone tree:
# it imports nothing from backend_v2, and backend_v2 imports nothing from it. So
# a test that exercises it has to bridge the path itself — and a missing entry
# would otherwise surface as an unimportable test module that looks like a broken
# test rather than a missing path entry.
_REPO_ROOT = require_repo_root("remote_agent/")
_SIDECAR = _REPO_ROOT / "remote_agent"
if str(_SIDECAR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR))

import llama_server as ls
from llama_server import LlamaStack, load

REGISTRY_FILE = _REPO_ROOT / "backend_v2" / "modal_llm" / "models.json"


def _registry(tmp_path=None):
    """The real registry, or a fixture written to a temp path."""
    if tmp_path is None:
        return load(REGISTRY_FILE)
    path = tmp_path / "models.json"
    return load(path)


@pytest.fixture
def fixture_registry(tmp_path):
    """A small registry, written where `load` will find it."""
    path = tmp_path / "models.json"
    path.write_text(json.dumps({
        "roles": {
            "rp": {"fallback": ["a_rp", "b_rp"]},
            "util": {"fallback": ["a_shared", "c_util"]},
        },
        "models": {
            "a_rp": {"role": "rp", "repo": "r/a", "gguf": "a.gguf", "ctx": 4096,
                     "kv": "q8_0", "mmproj": "a.mmproj", "mmproj_repo": "r/proj"},
            "b_rp": {"role": "rp", "repo": "r/b", "gguf": "b.gguf"},
            "a_shared": {"role": "util", "repo": "r/a", "gguf": "a.gguf",
                         "dir": "a_rp"},
            "c_util": {"role": "util", "repo": "r/c", "gguf": "c.gguf",
                       "extra_args": ["--foo"]},
        },
    }), encoding="utf-8")
    return load(path)


# ── the real registry parses ─────────────────────────────────────────────────

class TestTheSharedRegistry:
    def test_the_real_models_json_loads(self):
        registry = _registry()
        assert registry is not None
        # The same file the Modal app and llm_router read, so these are the same
        # roles those sides see.
        assert set(registry.roles) == {"rp", "util"}

    def test_both_roles_primary_to_the_same_model(self):
        """The shared-model setting, which is what makes `distinct_primaries` matter."""
        registry = _registry()
        rp = registry.primary("rp")
        util = registry.primary("util")
        assert rp.id == util.id, (
            "expected the shared-model setting; if it changes, the one-server "
            "assertion below has to be revisited"
        )

    def test_one_model_is_launched_where_two_roles_share_weights(self):
        """Starting the same GGUF twice doubles the VRAM for nothing."""
        registry = _registry()
        assert [m.id for m in registry.distinct_primaries()] == [registry.primary("rp").id]

    def test_llama_args_match_what_the_launcher_and_modal_app_agree_on(self):
        registry = _registry()
        args = registry.get(registry.primary("rp").id).llama_args("/models")
        # `-m` first, alias for routing, all layers on GPU, per-slot context.
        assert args[0] == "-m"
        assert "--alias" in args
        assert "-ngl" in args and "99" in args
        assert "-c" in args
        assert "--jinja" in args

    def test_a_model_with_no_registry_loads_as_none_not_an_error(self, tmp_path):
        """A worker fronting an external upstream has nothing to serve."""
        assert load(tmp_path / "absent.json") is None

    def test_an_empty_registry_raises_rather_than_serving_nothing(self, tmp_path):
        path = tmp_path / "models.json"
        path.write_text(json.dumps({"models": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match="declares no models"):
            load(path)

    def test_a_model_with_no_role_is_rejected(self, tmp_path):
        path = tmp_path / "models.json"
        path.write_text(json.dumps({
            "roles": {"rp": {"fallback": ["x"]}},
            "models": {"x": {"repo": "r/x", "gguf": "x.gguf"}},
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="declares no role"):
            load(path)

    def test_a_shared_dir_resolves_to_the_twin_weights(self, fixture_registry):
        """One download serving two servers, which is the point of `dir`."""
        shared = fixture_registry.get("a_shared")
        assert shared.volume_dir == "a_rp"
        assert "/a_rp/" in shared.llama_args("/models")[1]


# ── the stack routes and reports ─────────────────────────────────────────────

class TestLlamaStackRouting:
    def _stack(self, monkeypatch, models_dir="/weights", present=True):
        stack = LlamaStack(models_dir=models_dir)
        monkeypatch.setattr(stack, "_weights_present", lambda model: present)
        monkeypatch.setattr(stack, "_spawn", lambda model, port: stack.servers.__setitem__(
            model.id, ls.LaunchedServer(FakeProc(), port, model.id)
        ))
        return stack

    def test_a_model_with_no_weights_is_recorded_not_crashed(self, monkeypatch):
        """The same rule `ChatLLM.start` documents.

        Raising makes the caller retry and recreate forever, so a missing
        download becomes an infinite crash-loop burning GPU on something that can
        never succeed.
        """
        stack = self._stack(monkeypatch, present=False)
        registry = _fixture_registry()
        started = stack.launch(registry)
        assert started == {}
        assert "a_rp" in stack.unavailable
        assert "no weights" in stack.unavailable["a_rp"]

    def test_resolving_an_unserved_model_is_not_retryable(self, monkeypatch):
        from llama_server import LlamaStack

        stack = LlamaStack(models_dir="/w")
        with pytest.raises(RuntimeError, match="not served by this worker"):
            stack.resolve("nope")

    def test_health_reports_not_downloaded_rather_than_raising(self, monkeypatch):
        stack = self._stack(monkeypatch, present=False)
        registry = _fixture_registry()
        # Launch must run first: it is what records WHY a role has nothing, and
        # `health` reads that reason. A stack that never launched answers
        # `unknown`, which is the honest answer for "never tried" and not the
        # state this test is about.
        stack.launch(registry)
        health = stack.health(registry)
        # A role whose weights are missing is an actionable state on either
        # transport, not a crash-loop to infer from retries.
        assert health["roles"]["rp"]["status"] == "not_downloaded"
        assert "reason" in health["roles"]["rp"]

    def test_a_dead_server_is_not_routed_to(self, monkeypatch):
        from llama_server import LlamaStack

        stack = LlamaStack(models_dir="/w")
        dead = ls.LaunchedServer(FakeProc(exit_code=1), 8081, "a_rp")
        stack.servers["a_rp"] = dead
        with pytest.raises(RuntimeError):
            stack.resolve("a_rp")


class FakeProc:
    def __init__(self, exit_code=None):
        self._exit = exit_code

    def poll(self):
        return self._exit


def _fixture_registry():
    return load(_write_fixture())


def _write_fixture():
    import tempfile

    from pathlib import Path as _Path

    path = _Path(tempfile.mkdtemp()) / "models.json"
    path.write_text(json.dumps({
        "roles": {"rp": {"fallback": ["a_rp"]}, "util": {"fallback": ["a_util"]}},
        "models": {
            "a_rp": {"role": "rp", "repo": "r/a", "gguf": "a.gguf"},
            "a_util": {"role": "util", "repo": "r/u", "gguf": "u.gguf"},
        },
    }), encoding="utf-8")
    return path
