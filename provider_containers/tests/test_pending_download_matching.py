"""`pending_download_paths` must match the pipeline's own temp names, structurally.

This helper is the **authorisation gate** on the delete routes. All four of them
do the same thing:

    remote_agent/server.py            if not os.path.exists(full_path) and not list(pending_download_paths(full_path)):
    llm_worker/engines/modal/...      ...
    image_worker/engines/beam/...     ...

So a false positive is not a stray entry in a listing. It converts "this model does
not exist" into "delete what we found" — and what it found belongs to a different
model's in-flight download.

It matched by prefix, `basename + "."`, over a filename namespace that contains
other legal model names. For `foo.safetensors` it also swept

    foo.safetensors.fp16.safetensors.999.00112233.downloading

and `is_model_file("foo.safetensors.fp16.safetensors")` is `True`, so that is a
perfectly ordinary filename for a different model.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from provider_core.downloads import (
    _resume_slot_path,
    _unique_temp_path,
    pending_download_paths,
    pipeline_artifacts,
)
from provider_core.utils import is_model_file


def _found(tmp_path, model_name: str):
    target = tmp_path / "models" / "checkpoints" / model_name
    return sorted(os.path.basename(p) for p in pending_download_paths(str(target)))


class TestItMatchesExactlyWhatThePipelineGenerates:
    """Derived from the generators, not transcribed.

    A test that hardcoded `<pid>.<hex>` would pass unchanged if `_unique_temp_path`
    were changed to emit something else — and the sweeper would then quietly match
    nothing, which is the original bug in the opposite direction. These call the
    two naming functions and assert the sweeper finds what they produce.
    """

    def test_an_attempt_temp_is_found(self, tmp_path):
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        target = directory / "model.safetensors"
        temp = pathlib.Path(_unique_temp_path(str(target)))
        temp.write_bytes(b"")

        assert _found(tmp_path, "model.safetensors") == [os.path.basename(temp)]

    def test_a_parked_resume_slot_is_found(self, tmp_path):
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        target = directory / "model.safetensors"
        slot = pathlib.Path(_resume_slot_path(str(target), "0123456789ab"))
        slot.write_bytes(b"")

        assert _found(tmp_path, "model.safetensors") == [os.path.basename(slot)]

    def test_both_kinds_are_found_together(self, tmp_path):
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        target = directory / "model.safetensors"
        pathlib.Path(_unique_temp_path(str(target))).write_bytes(b"")
        pathlib.Path(_resume_slot_path(str(target), "0123456789ab")).write_bytes(b"")

        assert len(_found(tmp_path, "model.safetensors")) == 2

    def test_an_already_published_model_has_no_pending_paths(self, tmp_path):
        """The control: an ordinary file beside it must not be reported."""
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        (directory / "model.safetensors").write_bytes(b"x")
        (directory / "model.safetensors.json").write_bytes(b"{}")

        assert _found(tmp_path, "model.safetensors") == []


class TestItDoesNotMatchAnotherModelsTempFile:
    """The audit's demonstration, as a test."""

    @pytest.mark.parametrize(
        "other",
        [
            "model.safetensors.fp16.safetensors",
            "model.safetensors.fp8",
            "model.safetensors.preview",
            "model.safetensors2",
            "model.safetensors_v2",
            "model.safetensors.a",
        ],
    )
    def test_another_models_temp_is_not_swept(self, tmp_path, other):
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        # Exactly what `_unique_temp_path` produces for the *other* model.
        other_temp = pathlib.Path(_unique_temp_path(str(directory / other)))
        other_temp.write_bytes(b"x" * 1024)

        assert is_model_file(other), "precondition: that is a legal model name"
        assert _found(tmp_path, "model.safetensors") == [], (
            f"{os.path.basename(other_temp)} belongs to {other}, not to model.safetensors"
        )

    def test_the_authorisation_gate_does_not_open_on_another_models_temp(self, tmp_path):
        """Stated as the delete route reads it, because that is what it decides."""
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        target = directory / "model.safetensors"
        other_temp = pathlib.Path(
            _unique_temp_path(str(directory / "model.safetensors.fp16.safetensors"))
        )
        other_temp.write_bytes(b"x" * 1024)

        exists = target.exists()
        pending = list(pending_download_paths(str(target)))

        assert not exists, "precondition: the model itself is gone"
        assert pending == [], "the delete would be authorised, and would remove the wrong file"
        # ...and the file that must survive still is there.
        assert other_temp.exists()


class TestOnlyTheTwoRealShapesMatch:
    @pytest.mark.parametrize(
        "entry",
        [
            "model.safetensors.999.00112233.downloading",     # the real attempt temp
            "model.safetensors.resume.0123456789ab.downloading",  # the real slot
        ],
    )
    def test_ours(self, tmp_path, entry):
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        (directory / entry).write_bytes(b"")

        assert _found(tmp_path, "model.safetensors") == [entry]

    @pytest.mark.parametrize(
        "entry",
        [
            "model.safetensors.fp16.safetensors.999.00112233.downloading",
            "model.safetensors.fp8.999.00112233.downloading",
            "model.safetensors.notapid.00112233.downloading",
            "model.safetensors.999.00112233.downloading.extra",
            "model.safetensors.999.00112233.donwloading",
            "model.safetensors.999.00112233",
            "model.safetensors.999.0011223.downloading",
            "model.safetensors.abc.00112233.downloading",
            "model.safetensors.999.00112233.downloading.",
            "model.safetensors.resume..downloading",
            "model.safetensors.notresume.0123456789ab.downloading",
        ],
    )
    def test_not_ours(self, tmp_path, entry):
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        (directory / entry).write_bytes(b"")

        assert _found(tmp_path, "model.safetensors") == [], (
            f"{entry} is not a name this pipeline writes"
        )


class TestPipelineArtifactsNarrowsWithIt:
    """`pipeline_artifacts` is built on the same helper, so a delete that did sweep
    another's temp also swept the other's `.lock` — unlinking a flock another
    downloader holds is the split-inode race the lock exists to prevent."""

    def test_a_foreign_lock_is_not_swept(self, tmp_path):
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        other = "model.safetensors.fp16.safetensors"
        foreign_lock = directory / f"{other}.lock"
        foreign_lock.write_bytes(b"")
        foreign_temp = pathlib.Path(_unique_temp_path(str(directory / other)))
        foreign_temp.write_bytes(b"")

        swept = {os.path.basename(p) for p in pipeline_artifacts(str(directory / "model.safetensors"))}

        # `pipeline_artifacts` *names* the requested path's own `.lock` rather than
        # discovering it, so that entry is expected; the other model's two files are
        # not, and unlinking a foreign lock is the split-inode race the lock exists
        # to prevent.
        assert foreign_lock.name not in swept, f"the delete would reach {sorted(swept)}"
        assert foreign_temp.name not in swept, f"the delete would reach {sorted(swept)}"

    def test_our_own_lock_and_temp_are_still_swept(self, tmp_path):
        """The control: the fix must not stop a real delete reclaiming its files."""
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        target = directory / "model.safetensors"
        attempt = pathlib.Path(_unique_temp_path(str(target)))
        attempt.write_bytes(b"")
        (directory / "model.safetensors.lock").write_bytes(b"")

        swept = {os.path.basename(p) for p in pipeline_artifacts(str(target))}

        assert swept == {attempt.name, "model.safetensors.lock"}
