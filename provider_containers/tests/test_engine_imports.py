"""Finding 28: CI could not see this class of defect.

`.github/workflows/provider-tests.yml` ran `python -m compileall -q provider_core
image_worker llm_worker` and then `pytest tests`, and nothing in the suite
imported `llm_worker/engines/modal/modal_app.py` or
`image_worker/engines/modal/modal_app.py`. `compileall` only checks that a file
parses; it does not execute it, so it cannot see:

  * finding 1 — a `class FileStorage:` with no `@app.cls(...)` decorator is valid
    Python. Nothing raised. The provider's every file operation 500'd.
  * finding 9 — a hardcoded `('.json', '.preview.png', '.sha256')` tuple is valid
    Python. The listing quietly diverged from the shared `is_model_file`.

Both are invisible until a job is dispatched. So this module imports every engine
module and asserts the things that make a silent divergence impossible to miss.

`provider_containers` must stay importable standalone: neither Dockerfile copies
`backend_v2`, and `modal_app.py` only imports `provider_core`, so this is also
the guard that keeps that true.
"""

from __future__ import annotations

import importlib

import pytest

# Every engine module in both workers. `beam_app.py` and the two `modal_app.py`
# files are the ones `compileall` could not check.
ENGINE_MODULES = [
    "provider_core.base_client",
    "provider_core.background",
    "provider_core.deploy",
    "provider_core.downloads",
    "provider_core.http_client",
    "provider_core.logging",
    "provider_core.models",
    "provider_core.reconciliation",
    "provider_core.responses",
    "provider_core.router",
    "provider_core.state",
    "provider_core.utils",
    "provider_core.validation",
    "image_worker.worker",
    "image_worker.comfy.models_utils",
    "image_worker.comfy.workflow_executor",
    "image_worker.engines.beam.client",
    "image_worker.engines.beam.beam_app",
    "image_worker.engines.direct_url.client",
    "image_worker.engines.modal.client",
    "image_worker.engines.modal.modal_app",
    "image_worker.engines.remote_comfy.client",
    "llm_worker.worker",
    "llm_worker.engines.anthropic.client",
    "llm_worker.engines.google.client",
    "llm_worker.engines.modal.client",
    "llm_worker.engines.modal.modal_app",
    "llm_worker.engines.openai_compat.client",
]


# Modules that only a `deploy` target ever imports, and which need a third-party
# SDK at import time. `beam_app.py` imports `beta9`'s `rest_api`, which the
# requirements-test.txt environment does not provide a new enough version of (and
# CI does not install beta9 at all), so it cannot be imported here.
#
# That is stated rather than papered over: the guard below SKIPS these, so
# `beam_app.py` has no import coverage in CI. It is still covered by
# `compileall` for syntax, and by the source-text assertions in this file.
DEPLOY_TIME_ONLY = {
    "image_worker.engines.beam.beam_app": "beta9 (not installed by requirements-test.txt)",
}


def _import_or_skip(dotted: str):
    """Import a module, or skip when the ONLY obstacle is an absent deploy SDK.

    A `SyntaxError` — which is what `compileall` does catch — always propagates.
    So does any non-`ImportError` failure. Only a missing third-party module is
    tolerated, and only for the modules listed above.
    """
    try:
        return importlib.import_module(dotted)
    except ImportError as exc:
        missing = getattr(exc, "name", None) or str(exc)
        if dotted in DEPLOY_TIME_ONLY and missing.split(".")[0] in missing:
            pytest.skip(f"{dotted} needs {DEPLOY_TIME_ONLY[dotted]}: {exc}")
        raise


@pytest.mark.parametrize("dotted", ENGINE_MODULES)
def test_the_engine_module_imports(dotted):
    """A syntax error, a bad import, or a decorator that needs a real Modal
    account fails here rather than at `modal deploy` time."""
    assert _import_or_skip(dotted) is not None


@pytest.mark.parametrize("dotted", ENGINE_MODULES)
def test_the_engine_module_has_a_source_file(dotted):
    """`compileall` walks the tree; this asserts the tree and the import graph
    agree, so a file that exists but is unreachable is noticed."""
    module = _import_or_skip(dotted)
    assert module.__file__, f"{dotted} imported but has no source file"


def test_comfy_server_is_gone():
    """Finding 27: `image_worker/comfy/comfy_server.py` was 189 lines of dead code.

    Nothing imported it, and its `_restart_comfy_server` pkill'd
    `ComfyUI/main.py` — a process that image never starts. Deleted.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("image_worker.comfy.comfy_server")


class TestTheEngineRegistriesAreTheOnlyCopy:
    """Finding: this file used to keep a fourth hand-maintained copy of the engine
    lists, and the workers each had their own `if ENGINE ==` ladder on top of
    that. Four copies of an engine list is four chances to forget an engine.

    The registries are now in `provider_core.worker_bootstrap`, and the two
    workers call `select_client`. This file checks them against the modules that
    actually exist, so a new engine is a registry entry and nothing else.
    """

    @pytest.mark.parametrize("registry", ["IMAGE_ENGINES", "LLM_ENGINES"])
    def test_every_registered_engine_resolves(self, registry):
        from provider_core import worker_bootstrap

        engines = getattr(worker_bootstrap, registry)
        assert engines, f"{registry} is empty"

        for name, entry in engines.items():
            module = _import_or_skip(entry["module"])
            assert hasattr(module, entry["class_name"]), (
                f"{registry}[{name!r}] points at {entry['module']}."
                f"{entry['class_name']}, which does not exist"
            )
            assert getattr(module, entry["class_name"]) is not None

    @pytest.mark.parametrize("registry", ["IMAGE_ENGINES", "LLM_ENGINES"])
    def test_the_module_and_class_are_the_only_thing_a_new_engine_needs(self, registry):
        """A registry entry must not silently grow a third shape; the constructor
        difference is the one documented flag."""
        from provider_core import worker_bootstrap

        for name, entry in getattr(worker_bootstrap, registry).items():
            assert set(entry) <= {"module", "class_name", "pass_provider_id"}, (
                f"{registry}[{name!r}] has unexpected keys {sorted(entry)}"
            )

    @pytest.mark.parametrize("registry", ["IMAGE_ENGINES", "LLM_ENGINES"])
    def test_an_unknown_engine_names_every_valid_value(self, registry):
        from provider_core import worker_bootstrap

        engines = getattr(worker_bootstrap, registry)
        with pytest.raises(ValueError) as exc:
            worker_bootstrap.select_client(engines, "nope", {})
        for name in engines:
            assert name in str(exc.value)

    @pytest.mark.parametrize(
        "dotted", ["image_worker.worker", "llm_worker.worker"]
    )
    def test_the_worker_builds_its_client_from_the_registry(self, dotted):
        import inspect

        source = inspect.getsource(_import_or_skip(dotted))
        assert "select_client(" in source
        assert "elif ENGINE ==" not in source, (
            f"{dotted} still has a hand-rolled engine ladder; the registry is the "
            "only list"
        )


class TestBothWorkersEmitTheSameRuntimeConfigKeys:
    """The drift this replaced: the two `runtime_config` dicts declared different
    keys, so `max_concurrent_downloads` never reached the LLM worker and
    `provider_core/base_client.py` silently fell back to its default of 2 for
    every LLM reconciliation. A missing key is a default, not an error, which is
    why nothing caught it.
    """

    RUNTIME_CONFIG_KEYS = {
        "provider_id",
        "backend_url",
        "storage_dir",
        "max_concurrent_downloads",
        "validation_timeout_seconds",
        "reconciliation_list_timeout_seconds",
        "inference_timeout_seconds",
    }

    @staticmethod
    def _worker(dotted: str):
        module = _import_or_skip(dotted)
        return module, set(module.runtime_config)

    def test_the_seven_keys_are_declared_once(self):
        from provider_core.worker_bootstrap import RUNTIME_CONFIG_KEYS

        assert set(RUNTIME_CONFIG_KEYS) == self.RUNTIME_CONFIG_KEYS

    def test_both_workers_emit_exactly_those_keys(self):
        for dotted in ("image_worker.worker", "llm_worker.worker"):
            _, keys = self._worker(dotted)
            assert keys == self.RUNTIME_CONFIG_KEYS, (
                f"{dotted} runtime_config has {sorted(keys)}; the two workers must "
                "agree, because a key that is present on one side and absent on the "
                "other is a silent default, not an error"
            )

    def test_the_llm_worker_really_does_pass_max_concurrent_downloads(self):
        """The concrete consequence of the drift, stated so the number is a
        number rather than an assumption."""
        module, _ = self._worker("llm_worker.worker")
        assert module.runtime_config["max_concurrent_downloads"] == 5, (
            "the LLM worker is configured for 5; base_client's default is 2, and it "
            "is what was in effect before"
        )
        assert module.runtime_config["max_concurrent_downloads"] == 5

    @pytest.mark.parametrize("dotted", ["image_worker.worker", "llm_worker.worker"])
    def test_the_value_reaches_the_reconciliation_sync(self, dotted):
        """End to end, at the line that matters.

        `max_concurrent_downloads` is not stored on the client; it is read at
        `base_client.py`'s `start_reconciliation` and handed to `synchronize`. So
        the assertion is on the value that call site would pass, not on an
        attribute that does not exist.
        """
        from provider_core import worker_bootstrap

        module, _ = self._worker(dotted)
        engines = (
            worker_bootstrap.IMAGE_ENGINES
            if dotted.startswith("image")
            else worker_bootstrap.LLM_ENGINES
        )
        client = worker_bootstrap.select_client(engines, module.ENGINE, module.runtime_config)

        # Exactly base_client.py's expression.
        assert (
            client.runtime_config.get("max_concurrent_downloads", 2) == 5
        ), "base_client's default is 2 — that is what was silently in effect for the LLM worker"


class TestTheSharedLifespanIsOneCopy:
    @staticmethod
    def _called_names(path) -> set:
        """Every `x.y(...)` call target in a file, so a docstring that *mentions*
        `client.close()` is not mistaken for a call."""
        import ast

        tree = ast.parse(path.read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                value = node.func.value
                if isinstance(value, ast.Name):
                    names.add(f"{value.id}.{node.func.attr}")
        return names

    def test_neither_worker_defines_its_own(self):
        from pathlib import Path

        provider_root = Path(__file__).resolve().parents[1]
        for dotted in ("image_worker/worker.py", "llm_worker/worker.py"):
            path = provider_root / dotted
            assert "asynccontextmanager" not in path.read_text(), (
                f"{dotted} defines its own lifespan; provider_core.worker_bootstrap."
                "build_lifespan owns it"
            )
            assert "client.close" not in self._called_names(path), (
                f"{dotted} has its own teardown. The LLM copy was the one missing "
                "`except Exception: pass`, so a raising close() skipped the rest"
            )
            assert "build_lifespan(" in path.read_text()

    def test_the_shared_teardown_swallows_a_raising_close(self):
        import ast
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[1] / "provider_core/worker_bootstrap.py"
        )
        source = path.read_text()
        tree = ast.parse(source)
        # The `await client.close()` must be inside a `try` whose handler is a bare
        # `except Exception`, and `close_http_client()` must come after it.
        close_stmt = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Await)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "close"
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "client"
        )
        try_stmt = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.Try) and close_stmt in set(ast.walk(node))
        )
        assert any(
            isinstance(handler.type, ast.Name) and handler.type.id == "Exception"
            for handler in try_stmt.handlers
        ), "a raising close() must not skip the steps after it"
        assert source.index("close_http_client()", source.index("await client.close()")) > source.index(
            "await client.close()"
        ), "the shared pool must be released even when the client complains"


class TestProviderCoreStaysImportableStandalone:
    """Neither Dockerfile copies `backend_v2`, so a provider module that reaches
    into the backend breaks the deployed image while every local test passes."""

    @pytest.mark.parametrize(
        "dotted",
        [
            "image_worker.engines.modal.modal_app",
            "llm_worker.engines.modal.modal_app",
            "image_worker.engines.beam.beam_app",
        ],
    )
    def test_no_backend_imports(self, dotted):
        import inspect

        source = inspect.getsource(_import_or_skip(dotted))
        for forbidden in ("backend_v2", "api.routes", "core.entities", "infrastructure."):
            assert forbidden not in source, (
                f"{dotted} imports {forbidden!r}; the provider images do not "
                "contain backend_v2"
            )


class TestTheModalAppsExposeTheSameSurface:
    """The image/vLLM twins are near-identical by design. Anything one has and the
    other lacks is a fix that was applied to one and not the sibling — the single
    biggest theme in this round."""

    SHARED_FUNCTIONS = [
        "download_model",
        "list_models_with_metadata",
        "validate_models",
        "setup_models",
    ]
    STORAGE_METHODS = [
        "read_file",
        "file_size",
        "read_file_range",
        "delete_file",
        "list_directory",
        "put_file",
    ]
    # Zero callers repo-wide (only the twin's copy and a test that asserted the
    # pair existed). `file_size` is the one the clients actually use; the other
    # two were a size and an existence check nobody ever asked for across the RPC
    # boundary, and `read_file_range` answers both in the same call.
    DEAD_STORAGE_METHODS = ["file_exists", "get_file_size"]

    @pytest.mark.parametrize("name", DEAD_STORAGE_METHODS)
    def test_neither_app_declares_a_dead_storage_method(self, name):
        import image_worker.engines.modal.modal_app as image_app
        import llm_worker.engines.modal.modal_app as llm_app

        for app in (image_app, llm_app):
            assert not hasattr(app.FileStorage, name), (
                f"{app.FileStorage.__module__} still declares {name}, which nothing "
                "calls — an RPC surface nobody reaches is still a surface"
            )

    @pytest.mark.parametrize("name", SHARED_FUNCTIONS)
    def test_both_apps_declare_the_function(self, name):
        import image_worker.engines.modal.modal_app as image_app
        import llm_worker.engines.modal.modal_app as llm_app

        assert hasattr(image_app, name), f"image app lost {name}"
        assert hasattr(llm_app, name), f"vLLM app lost {name}"
        assert name in image_app.app.registered_functions
        assert name in llm_app.app.registered_functions, (
            f"{name} is declared but not registered with the vLLM app, so "
            f"modal.Function.from_name(app, {name!r}) raises"
        )

    @pytest.mark.parametrize("name", STORAGE_METHODS)
    def test_both_storage_classes_declare_the_method(self, name):
        import image_worker.engines.modal.modal_app as image_app
        import llm_worker.engines.modal.modal_app as llm_app

        assert hasattr(image_app.FileStorage, name), f"image FileStorage lost {name}"
        assert hasattr(llm_app.FileStorage, name), (
            f"vLLM FileStorage lost {name} — this is the finding 1 / 10 shape: the "
            "image twin has it, the LLM twin does not"
        )


class TestTheEnginesShareTheListingPredicate:
    """Finding 9. One predicate, so a new pipeline-owned suffix is excluded
    everywhere at once instead of being added to a per-engine tuple that drifts."""

    MODULES = (
        "image_worker.engines.modal.modal_app",
        "llm_worker.engines.modal.modal_app",
        "image_worker.engines.beam.beam_app",
        "image_worker.comfy.models_utils",
    )

    @pytest.mark.parametrize("dotted", MODULES)
    def test_the_module_reaches_the_shared_predicate(self, dotted):
        """Either it calls `is_model_file`, or it delegates to the shared scan.

        Asserting the name appears in the source would be satisfied by a comment,
        and asserting the *import* would forbid the delegation that removed the
        three-way drift: `provider_core/model_scan.scan_model_directory` is now
        the single implementation of "which names in this directory are models",
        and `image_worker/comfy/models_utils.py` reaches it that way. The property
        worth pinning is that no module carries a local suffix list of its own.
        """
        import inspect

        source = inspect.getsource(_import_or_skip(dotted))
        assert "is_model_file" in source or "scan_model_directory" in source, (
            f"{dotted} classifies model files without the shared predicate"
        )

    def test_the_shared_scan_is_the_one_that_calls_the_predicate(self):
        """And the scan is not a fourth copy of the rule."""
        import inspect

        from provider_core.model_scan import scan_model_directory

        assert "is_model_file" in inspect.getsource(scan_model_directory)

    @pytest.mark.parametrize("dotted", MODULES)
    def test_no_module_hardcodes_a_model_suffix_list(self, dotted):
        """The drift finding 9 describes: a local tuple of model suffixes."""
        import inspect
        import re

        source = inspect.getsource(_import_or_skip(dotted))
        # `.safetensors"` inside a tuple/list, e.g. `(".safetensors", ".ckpt")`.
        assert not re.search(r"\(\s*[\"']\.safetensors[\"']\s*,", source), (
            f"{dotted} carries its own model-suffix tuple; use provider_core.utils"
        )
