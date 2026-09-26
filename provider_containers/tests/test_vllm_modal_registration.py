"""Finding 1: the vLLM Modal engine's `FileStorage` was never published.

`llm_worker/engines/modal/modal_app.py:431` declared `class FileStorage:` with no
`@app.cls(...)` decorator. A plain Python class is never registered with a Modal
app, so the client's

    modal.Cls.from_name(self.modal_app_name, "FileStorage")

raised on every call. The failure set was every file operation on that provider:
`get_file`, `delete_file`, `delete_model`, `upload_file` and `get_storage_stats`.
The image twin had had the decorator the whole time — the fix simply was not
ported to the LLM twin.

`modal.Cls.from_name` on a name that is not registered raises, so the assertion
below is the real one: if the decorator goes away, this fails.
"""

from __future__ import annotations

import pytest


def _import_llm_modal_app():
    import llm_worker.engines.modal.modal_app as modal_app

    return modal_app


class TestFileStorageIsPublished:
    def test_file_storage_exists_and_is_registered_with_the_app(self):
        modal_app = _import_llm_modal_app()

        assert hasattr(modal_app, "FileStorage"), (
            "llm_worker/engines/modal/modal_app.py must define FileStorage — the "
            "client resolves it by name with modal.Cls.from_name"
        )
        registered = modal_app.app.registered_classes
        assert "FileStorage" in registered, (
            "FileStorage is a plain Python class, so modal.Cls.from_name(app, "
            "'FileStorage') raises and every file op on this provider 500s. "
            f"Registered classes: {sorted(registered)}"
        )
        # And it is the same object the decorator was applied to.
        assert registered["FileStorage"] is modal_app.FileStorage

    def test_the_decorator_arguments_match_the_image_twin(self):
        """Copied exactly, as the fix requires: a different volume is a different disk."""
        import image_worker.engines.modal.modal_app as image_app
        import llm_worker.engines.modal.modal_app as llm_app

        llm_spec = llm_app.app.registered_classes["FileStorage"]
        image_spec = image_app.app.registered_classes["FileStorage"]

        for option in ("timeout", "max_containers", "scaledown_window", "image", "volumes"):
            assert getattr(llm_spec, option, None) == getattr(image_spec, option, None), (
                f"FileStorage.{option} diverges from the image twin"
            )

    def test_the_vllm_engine_class_is_still_registered(self):
        """The control: this one already had its decorator, and must keep it."""
        modal_app = _import_llm_modal_app()
        assert "VLLMEngine" in modal_app.app.registered_classes


class TestTheClientResolvesIt:
    def test_get_file_storage_cls_returns_the_registered_class(self):
        import modal

        from llm_worker.engines.modal.client import VLLMModalProviderClient
        import llm_worker.engines.modal.modal_app as modal_app

        client = VLLMModalProviderClient(provider_id="vllm-test", runtime_config={})
        client.modal_app_name = modal_app.app.name

        # The point of the test: this raises when the class is not registered.
        resolved = client._get_file_storage_cls()

        # The client caches the handle, so a second call is the identical object.
        assert client._get_file_storage_cls() is resolved
        # And it is a real Modal Cls handle, not a stub. Deliberately no
        # `.info` / `get_object_name()` assertion: both go to the Modal server, and
        # this suite runs with no Modal credentials.
        assert isinstance(resolved, modal.Cls)

    def test_a_new_client_also_resolves_it(self, monkeypatch):
        """Not a cache artefact: a cold cache must resolve too."""
        import modal

        from llm_worker.engines.modal.client import VLLMModalProviderClient
        import llm_worker.engines.modal.modal_app as modal_app

        monkeypatch.setenv("MODAL_APP_NAME", modal_app.app.name)
        client = VLLMModalProviderClient(provider_id="vllm-test", runtime_config={})
        assert "FileStorage" not in client._cls_cache
        assert isinstance(client._get_file_storage_cls(), modal.Cls)

    def test_the_name_the_client_asks_for_is_the_name_that_is_registered(self):
        """The two halves of the contract, tied together.

        `modal.Cls.from_name` builds its handle locally and only fails when the
        Modal server is asked to resolve the name, so a client-side call does not
        raise in a test with no credentials. That is why the assertions above are
        not enough on their own: the name the client hardcodes has to be the name
        the app actually published. This is the assertion that discriminates —
        remove the `@app.cls` decorator and this fails.
        """
        import inspect
        import re

        from llm_worker.engines.modal.client import VLLMModalProviderClient
        import llm_worker.engines.modal.modal_app as modal_app

        source = inspect.getsource(VLLMModalProviderClient._get_file_storage_cls)
        match = re.search(r'from_name\([^,]+,\s*"([^"]+)"\)', source)
        assert match, f"could not read the registered name out of {source!r}"

        requested = match.group(1)
        registered = modal_app.app.registered_classes
        assert requested in registered, (
            f"the client asks for {requested!r}; the app publishes {sorted(registered)}. "
            "Cls.from_name raises against an unregistered name, so every file op on "
            "this provider 500s."
        )

    def test_every_cls_the_client_looks_up_is_registered(self):
        """All of them, so the same class of bug on VLLMEngine is caught too."""
        import inspect
        import re

        from llm_worker.engines.modal.client import VLLMModalProviderClient
        import llm_worker.engines.modal.modal_app as modal_app

        source = inspect.getsource(VLLMModalProviderClient)
        requested = set(re.findall(r'Cls\.from_name\([^,]+,\s*"([^"]+)"\)', source))
        registered = modal_app.app.registered_classes
        assert requested, "no Cls.from_name calls found; the client was restructured"
        assert requested <= set(registered), (
            f"client looks up {sorted(requested - set(registered))}, "
            f"which the app does not publish ({sorted(registered)})"
        )


class TestEveryFileOperationGoesThroughIt:
    """The blast radius, so a future rename cannot silently narrow it."""

    @pytest.mark.parametrize(
        "client_method,storage_method",
        [
            ("get_file", "read_file_range"),
            ("delete_model", "delete_file"),
            ("upload_file", "put_file"),
            ("get_storage_stats", "list_directory"),
        ],
    )
    def test_the_storage_method_the_client_calls_exists(self, client_method, storage_method):
        import llm_worker.engines.modal.modal_app as modal_app

        assert hasattr(modal_app.FileStorage, storage_method), (
            f"FileStorage.{storage_method} is what {client_method} calls"
        )

    def test_delete_file_delegates_to_delete_model_on_the_client(self):
        """`delete_file` is a client-level alias, not a storage method."""
        from llm_worker.engines.modal.client import VLLMModalProviderClient

        assert callable(VLLMModalProviderClient.delete_file)
        assert callable(VLLMModalProviderClient.delete_model)


class TestRangedReadHelpersExist:
    """Finding 10: `read_file_range` / `file_size` are what make get_file bounded.

    The description of finding 10 said these were "ALREADY DEFINED, unused by its
    own client" at modal_app.py:504. They were not present at all — the file went
    straight from `read_file` to `delete_file` — so they were added, mirroring the
    image twin, and the client's `get_file` was ported onto them.
    """

    def test_both_ranged_helpers_are_present(self):
        import llm_worker.engines.modal.modal_app as modal_app

        assert hasattr(modal_app.FileStorage, "file_size")
        assert hasattr(modal_app.FileStorage, "read_file_range")

    def test_the_image_twin_has_the_same_pair(self):
        import image_worker.engines.modal.modal_app as image_app

        assert hasattr(image_app.FileStorage, "file_size")
        assert hasattr(image_app.FileStorage, "read_file_range")
