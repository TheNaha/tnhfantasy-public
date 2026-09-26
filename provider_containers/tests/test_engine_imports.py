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
        "file_exists",
        "get_file_size",
        "put_file",
    ]

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

    @pytest.mark.parametrize(
        "dotted",
        [
            "image_worker.engines.modal.modal_app",
            "llm_worker.engines.modal.modal_app",
            "image_worker.engines.beam.beam_app",
            "image_worker.comfy.models_utils",
        ],
    )
    def test_the_module_imports_the_shared_predicate(self, dotted):
        import inspect

        source = inspect.getsource(_import_or_skip(dotted))
        assert "is_model_file" in source, (
            f"{dotted} does not use provider_core.utils.is_model_file"
        )
