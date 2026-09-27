"""Findings 8 and 9: the download pipeline's own artifacts were treated as models,
and a crash-interrupted download could never be reclaimed.

Finding 8 — `pending_download_paths` (provider_core/downloads.py:132-138) exists
precisely to name every temp file of an in-flight or abandoned attempt at a path:
the per-attempt temp is `<path>.<pid>.<hex>.downloading` and a parked resume slot
is `<path>.resume.<identity>.downloading`. Two places probed the old, pre-rename
fixed name `<path>.downloading` instead, which matches neither:

  * remote_agent/server.py `/delete-model` — so on the remote-comfy path a
    crash-interrupted 7 GB download survived forever. `_validate_dir` reports every
    `.downloading` as `partial` and deliberately does not delete one, so
    `total_partial` in `/validate-all-models` — exactly what reconciliation step 0
    calls, with delete_invalid=True — was permanently non-zero.
  * llm_worker/engines/modal/modal_app.py `FileStorage.delete_file` — same.

Finding 9 — the vLLM Modal listing and validation filtered with a hardcoded
`('.json', '.preview.png', '.sha256')` tuple, while the download pipeline owns
`.lock` and `.downloading` (utils.py TRANSIENT_SUFFIXES). So on the vLLM volume
`foo.safetensors.lock` and `foo.safetensors.<pid>.<hex>.downloading` were emitted
as model files, fed to `register_discovered_files`, and turned into backend model
rows. The lock is held for the whole transfer, so the entry appeared mid-download.
The image twin had been converted to the shared `is_model_file` predicate; this
was a regression of an already-fixed bug.
"""

from __future__ import annotations

import os
import pathlib
import uuid

import pytest

from provider_core.downloads import pending_download_paths
from provider_core.utils import (
    DOWNLOADING_SUFFIX, LOCK_SUFFIX, is_model_file, is_transient_artifact,
)

# `remote_agent`'s sys.path entry and its import-time token requirement are handled
# once, in tests/conftest.py.


def _module_source(dotted: str) -> str:
    """Source text of a module, by path.

    `inspect.getsource` cannot be pointed at a `@app.function` /
    `@modal.method` decorated object — those are `modal.functions.Function`
    instances, not functions — so every assertion here is made against the module
    file. Reading the file is also the honest check here: what matters is what the
    deployed module does, not what a particular wrapper object exposes.
    """
    import importlib.util

    spec = importlib.util.find_spec(dotted)
    assert spec is not None and spec.origin, f"cannot locate {dotted}"
    return pathlib.Path(spec.origin).read_text()


def _import_agent_server():
    import remote_agent.server as server

    return server


# Names the pipeline itself creates, none of which is a model.
PIPELINE_ARTIFACTS = [
    "model.safetensors.lock",
    "model.safetensors.1234.deadbeef.downloading",
    "model.safetensors.resume.0123456789ab.downloading",
]

REAL_MODELS = [
    "model.safetensors",
    "model.ckpt",
    "model.gguf",
    "model.pth",
    "upscaler.pth",
]


class TestPendingDownloadPathsNamesWhatThePipelineOwns:
    def test_it_finds_the_per_attempt_temp(self, tmp_path):
        target = tmp_path / "model.safetensors"
        target.write_bytes(b"x")
        temp = tmp_path / f"model.safetensors.{os.getpid()}.{uuid.uuid4().hex[:8]}{DOWNLOADING_SUFFIX}"
        temp.write_bytes(b"partial")

        found = list(pending_download_paths(str(target)))
        assert [os.path.basename(p) for p in found] == [temp.name]

    def test_it_finds_a_parked_resume_slot(self, tmp_path):
        target = tmp_path / "model.safetensors"
        target.write_bytes(b"x")
        slot = tmp_path / f"model.safetensors.resume.0123456789ab{DOWNLOADING_SUFFIX}"
        slot.write_bytes(b"partial")

        found = list(pending_download_paths(str(target)))
        assert [os.path.basename(p) for p in found] == [slot.name]

    def test_it_finds_the_post_rename_temp_not_just_the_old_fixed_name(self, tmp_path):
        """The regression this fixes.

        `<path>.downloading` is not the temp name any more — `_unique_temp_path`
        adds pid and hex — so a fixed-name probe finds nothing and the partial
        survives every delete forever. (The helper also matches the old fixed name,
        since `model.safetensors.downloading` is prefix+suffix; that is harmless
        and is not what is being asserted.)
        """
        target = tmp_path / "model.safetensors"
        target.write_bytes(b"x")
        (tmp_path / f"model.safetensors{DOWNLOADING_SUFFIX}").write_bytes(b"stale")

        real_temp = tmp_path / f"model.safetensors.99.abcdef01{DOWNLOADING_SUFFIX}"
        real_temp.write_bytes(b"partial")

        found = [os.path.basename(p) for p in pending_download_paths(str(target))]
        assert real_temp.name in found, (
            "a probe of the pre-rename fixed name misses this entirely"
        )

    def test_it_does_not_match_a_sibling_model(self, tmp_path):
        """Prefix matching must not spill: `model.safetensors.bak` is another model."""
        (tmp_path / "model.safetensors").write_bytes(b"x")
        (tmp_path / "model.safetensors.bak").write_bytes(b"x")

        assert list(pending_download_paths(str(tmp_path / "model.safetensors"))) == []

    def test_it_yields_nothing_for_a_path_with_no_partials(self, tmp_path):
        target = tmp_path / "model.safetensors"
        target.write_bytes(b"x")
        assert list(pending_download_paths(str(target))) == []


class TestTheAgentSweepsThem:
    """`remote_agent` /delete-model and /delete-file."""

    @pytest.fixture
    def data_dir(self, tmp_path, monkeypatch):
        server = _import_agent_server()
        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        return server, tmp_path

    def test_a_model_with_a_parked_resume_slot_is_reclaimed(self, data_dir):
        server, root = data_dir
        model = root / "models" / "checkpoints" / "big.safetensors"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"weights")
        slot = model.parent / f"big.safetensors.resume.0123456789ab{DOWNLOADING_SUFFIX}"
        slot.write_bytes(b"7GB of partial")

        import asyncio

        payload = asyncio.run(
            server.delete_model(server.DeleteModelRequest(path="models/checkpoints/big.safetensors"))
        )

        # The envelope, not the bare `{"success": True}` this used to return:
        # `remote_agent` is one of the two server-side files whose dialect was
        # never unified, and the worker adopts the body verbatim.
        assert payload["status"] == "success"
        assert payload["success"] is True
        assert not model.exists(), "the model itself must be gone"
        assert not slot.exists(), (
            "the parked resume slot is the multi-GB file: it is what "
            "pending_download_paths exists to name"
        )

    def test_a_model_with_a_per_attempt_temp_is_reclaimed(self, data_dir):
        server, root = data_dir
        model = root / "models" / "checkpoints" / "big.safetensors"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"weights")
        temp = model.parent / f"big.safetensors.4242.abcdef01{DOWNLOADING_SUFFIX}"
        temp.write_bytes(b"partial")

        import asyncio

        asyncio.run(
            server.delete_model(server.DeleteModelRequest(path="models/checkpoints/big.safetensors"))
        )
        assert not temp.exists()

    def test_a_lone_partial_with_no_model_is_still_swept(self, data_dir):
        """The download crashed before publishing, so there is no model at all."""
        server, root = data_dir
        orphan_slot = root / "models" / "checkpoints" / f"gone.safetensors.resume.abc123{DOWNLOADING_SUFFIX}"
        orphan_slot.parent.mkdir(parents=True)
        orphan_slot.write_bytes(b"7GB of partial")

        import asyncio

        payload = asyncio.run(
            server.delete_model(server.DeleteModelRequest(path="models/checkpoints/gone.safetensors"))
        )

        assert payload["status"] == "success"
        assert payload["success"] is True
        assert not orphan_slot.exists()

    def test_deleting_a_directory_does_not_500(self, data_dir):
        """Finding 21: `_do_remove` called `os.remove` on a directory.

        `IsADirectoryError` escaped with no `try`, so a DELETE of a directory was
        a 500 while Modal and Beam both rmtree the same request and answer 200.
        """
        server, root = data_dir
        directory = root / "models" / "loras" / "collection"
        (directory / "nested").mkdir(parents=True)
        (directory / "nested" / "a.safetensors").write_bytes(b"x")

        import asyncio

        payload = asyncio.run(
            server.delete_model(server.DeleteModelRequest(path="models/loras/collection"))
        )

        assert payload["status"] == "success"
        assert payload["success"] is True
        assert not directory.exists()

    def test_a_missing_file_is_still_reported_as_a_refusal(self, data_dir):
        server, root = data_dir
        import asyncio

        payload = asyncio.run(
            server.delete_model(server.DeleteModelRequest(path="models/checkpoints/nope.safetensors"))
        )
        assert payload["success"] is False


class TestTheVLLMModalListingUsesTheSharedPredicate:
    """Finding 9. The predicate is the assertion; the module is the subject."""

    @pytest.mark.parametrize("name", PIPELINE_ARTIFACTS)
    def test_pipeline_artifacts_are_not_models(self, name):
        assert is_transient_artifact(name), f"{name} is pipeline-owned"
        assert not is_model_file(name), (
            f"{name} was listed as a model, registered by "
            "register_discovered_files, and turned into a backend model row"
        )

    @pytest.mark.parametrize("name", REAL_MODELS)
    def test_real_models_are_still_models(self, name):
        assert is_model_file(name), f"{name} must keep being listed"

    def test_the_vllm_listing_uses_the_predicate_not_a_suffix_tuple(self):
        source = _module_source("llm_worker.engines.modal.modal_app")
        assert "is_model_file" in source
        assert "'.preview.png'" not in source, (
            "the hardcoded suffix tuple is back in the listing scan"
        )

    def test_the_vllm_validation_uses_the_predicate_too(self):
        assert "is_model_file" in _module_source("llm_worker.engines.modal.modal_app")

    def test_the_vllm_list_directory_uses_the_predicate(self):
        assert "is_model_file" in _module_source("llm_worker.engines.modal.modal_app")

    def test_the_image_twin_still_uses_the_predicate(self):
        """The control: the twin that was fixed first must stay fixed."""
        assert "is_model_file" in _module_source("image_worker.engines.modal.modal_app")

    def test_the_vllm_delete_file_sweeps_with_the_helper(self):
        source = _module_source("llm_worker.engines.modal.modal_app")
        assert "pending_download_paths" in source
        assert f'"{DOWNLOADING_SUFFIX}"' not in source, (
            "the fixed-name probe is back"
        )

    def test_the_image_twin_delete_file_still_sweeps_with_the_helper(self):
        assert "pending_download_paths" in _module_source(
            "image_worker.engines.modal.modal_app"
        )


class TestTheRemoteAgentReportsPartialsNotAsModels:
    """A `.lock` is 0 bytes and fails the size check.

    If it were treated as a model, reconciliation — which runs with
    `delete_invalid=True` — would `os.remove` it, and because
    `os.path.splitext("x.safetensors.lock")[0]` is `"x.safetensors"` it would take
    `x.safetensors.json` and `x.safetensors.preview.png` with it, destroying the
    metadata and preview of every model ever downloaded.
    """

    def test_the_agent_uses_the_shared_transient_predicate(self):
        assert "is_transient_artifact" in _module_source("remote_agent.server")
        assert 'endswith(".downloading")' not in _module_source("remote_agent.server")

    def test_a_lock_is_reported_as_partial_not_invalid(self, tmp_path, monkeypatch):
        server = _import_agent_server()
        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        # A genuinely valid model: a zip/ckpt body, over MIN_MODEL_SIZE (10 KiB)
        # and starting with a recognised header, so the invalid sweep leaves it
        # alone. (The point of the test is the lock, not the model's validity —
        # a real safetensors file has to be internally consistent to pass.)
        (directory / "real.ckpt").write_bytes(b"PK" + b"\x00" * 20000)
        (directory / f"real.ckpt{LOCK_SUFFIX}").write_bytes(b"")

        result = server._validate_dir(str(directory), delete_invalid=True)

        names = {entry["name"] for entry in result["partial"]}
        assert "real.ckpt.lock" in names
        # And neither the lock nor the model it belongs to was deleted. If the
        # lock were swept as an invalid model, splitext("real.ckpt.lock")[0] is
        # "real.ckpt" and the model's own metadata and preview go with it.
        assert (directory / f"real.ckpt{LOCK_SUFFIX}").exists()
        assert (directory / "real.ckpt").exists()
        assert result["total_invalid"] == 0
