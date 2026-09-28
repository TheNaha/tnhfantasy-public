"""A provider can host more than one Modal app, and the request has to say which.

TTS is a separate Modal app from the image worker, with a separate image, because
the image worker's cold start is 57.66s of which ~44s is in-container and ~42s of
that is ComfyUI's own boot — the heavy `ultralytics` import and the enumeration
of 531 model files on the /mnt/data volume. A TTS image has neither.

Which means a TTS job must not go to the image app. `workflow` alone cannot say
which app to use: an image job and a TTS job are both a ComfyUI graph, differing
only in node types. Before this, a TTS job would have been routed to the image
worker and failed inside a container on a graph naming nodes that image does not
have — which is the exact state TTS was in before any of this.

`InferenceRequest.task_type` is that signal, optional so a provider hosting one
app is unaffected.
"""


from provider_core.models import InferenceRequest


class TestRequestCarriesTheTaskType:
    def test_it_defaults_to_none(self):
        """Optional, so an older backend or any other caller of the schema keeps
        working unchanged."""
        req = InferenceRequest(workflow={"1": {}})
        assert req.task_type is None

    def test_it_survives_the_round_trip(self):
        req = InferenceRequest(workflow={"1": {}}, task_type="tts")
        assert InferenceRequest.model_validate(req.model_dump()).task_type == "tts"

    def test_a_workflow_alone_does_not_imply_a_task_type(self):
        """The reason the field exists: image and TTS payloads are the same shape,
        so nothing else in the request distinguishes them."""
        assert InferenceRequest(workflow={"1": {}}).task_type is None


class TestModalClientRouting:
    def _client_module(self):
        import importlib
        import os
        import sys
        from unittest.mock import MagicMock

        # `modal` is not installed in the provider venv; the routing table is
        # module-level and does not need it, so stub it.
        if "modal" not in sys.modules:
            fake = MagicMock()
            fake.Cls.from_name = MagicMock()
            sys.modules["modal"] = fake
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return importlib.import_module("image_worker.engines.modal.client")

    def test_tts_routes_to_the_tts_app(self):
        mod = self._client_module()
        app, cls = mod._APP_FOR_TASK_TYPE["tts"]
        assert app == mod.MODAL_TTS_APP_NAME
        assert cls == "TTSWorker"
        # A different app AND a different class from the image path. Getting
        # either wrong sends TTS to an image container.
        assert app != mod.MODAL_APP_NAME
        assert cls != "ComfyUISnapshot"

    def test_image_and_anything_else_stay_on_the_image_app(self):
        mod = self._client_module()
        # Only `tts` is remapped. An image job, and a request from a backend
        # that does not send the field, must be completely unaffected.
        assert set(mod._APP_FOR_TASK_TYPE) == {"tts"}

    def test_the_tts_class_satisfies_the_call_contract(self):
        """The client calls `.run.remote_gen.aio(workflow)`. If the TTS class
        did not expose `run` as a generator, routing to it would fail at the
        first call rather than at build time."""
        import ast
        import os

        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(
            os.path.join(here, "tts_worker", "engines", "modal", "modal_app.py"),
            encoding="utf-8",
        ).read()
        tree = ast.parse(src)
        classes = {
            n.name: n
            for n in tree.body
            if isinstance(n, ast.ClassDef)
        }
        assert "TTSWorker" in classes, "the app must expose TTSWorker"
        runs = [
            n
            for n in ast.walk(classes["TTSWorker"])
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "run"
        ]
        assert len(runs) == 1
        # A generator, not a coroutine: `remote_gen` on a plain coroutine raises
        # `InvalidError`, which is a confusing way to learn the contract differs.
        assert isinstance(runs[0], ast.AsyncFunctionDef)
        assert any(
            isinstance(n, (ast.AsyncFor, ast.Yield)) for n in ast.walk(runs[0])
        ), "run must be an async generator to work with .remote_gen()"
