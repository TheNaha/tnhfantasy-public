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


class TestTheImageWorkerIsImageOnly:
    """A regression guard on an error, not a description of a design.

    The image worker's Modal client was briefly taught to route `task_type="tts"`
    to a second app, on the theory that TTS could be a second Modal app behind
    the same provider. That is wrong on the codebase's own model — one provider
    is one container, each with its own Dockerfile and its own health — and it
    put a speech app in the deploy path of every image provider. TTS is now
    `tts_worker/`, its own container. If the routing creeps back, the image
    provider will again start building an app it never registered to serve."""

    @staticmethod
    def _image_client_source() -> str:
        import os

        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(
            os.path.join(here, "image_worker", "engines", "modal", "client.py"),
            encoding="utf-8",
        ) as fh:
            return fh.read()

    def test_it_mentions_no_tts_app(self):
        src = self._image_client_source()
        assert "MODAL_TTS_APP_NAME" not in src
        assert "_APP_FOR_TASK_TYPE" not in src
        assert "TTSWorker" not in src

    def test_it_still_resolves_the_image_app_unconditionally(self):
        src = self._image_client_source()
        assert "modal.Cls.from_name(MODAL_APP_NAME, class_name)" in src


class TestTheTTSWorkerIsItsOwnProvider:
    @staticmethod
    def _import(name: str):
        import importlib
        import sys
        from unittest.mock import MagicMock

        # `modal` is not installed in the provider venv; neither module needs it
        # at import beyond the symbol they call, so stub it.
        if "modal" not in sys.modules:
            fake = MagicMock()
            fake.Cls.from_name = MagicMock()
            sys.modules["modal"] = fake
        return importlib.import_module(name)

    def test_the_engine_registry_points_at_the_tts_client(self):
        from provider_core.worker_bootstrap import TTS_ENGINES

        assert "modal" in TTS_ENGINES
        entry = TTS_ENGINES["modal"]
        assert entry["module"] == "tts_worker.engines.modal.client"
        assert entry["class_name"] == "ModalTTSProviderClient"

    def test_the_tts_client_resolves_a_different_app_than_the_image_one(self):
        """A different app AND a different class. Getting either wrong sends
        speech to an image container."""
        tts = self._import("tts_worker.engines.modal.client")
        image = self._import("image_worker.engines.modal.client")

        assert tts.MODAL_TTS_APP_NAME != image.MODAL_APP_NAME
        assert tts.TTS_CLASS_NAME == "TTSWorker"
        assert tts.TTS_CLASS_NAME != "ComfyUISnapshot"

    def test_the_tts_worker_declares_only_the_tts_capability(self):
        """Not `["image", "tts"]`. `Provider.serves()` is additive, so a provider
        always serves its own `worker_type` — which is how a TTS container avoids
        being offered checkpoint jobs it cannot run."""
        worker = self._import("tts_worker.worker")
        assert worker.WORKER_TYPE == "tts"
        assert worker.CAPABILITIES == ["tts"]

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
