"""Reconciliation must never touch files the download pipeline owns.

`exclusive_path_lock` creates `<model>.lock` and `_unique_temp_path` creates
`<model>.<pid>.<hex>.downloading`. Reconciliation runs with `delete_invalid`
unconditionally true, and both are 0 bytes, so validation used to treat them as
corrupt models: it `os.remove`d the lock, then — because
`os.path.splitext("x.safetensors.lock")[0]` is `"x.safetensors"` — removed
`x.safetensors.json` and `x.safetensors.preview.png` with it. That silently
destroyed the metadata and preview of every model that had ever been downloaded.

Deleting an in-flight `.downloading` was worse: the writer kept its descriptor,
transferred the whole file, and then failed at `os.replace`, which
reconciliation reported as a failed download. Unlinking the lock also defeats
it — a second downloader `O_CREAT`s a new inode and takes a different flock.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from provider_core.downloads import _unique_temp_path, pending_download_paths
from provider_core.utils import (
    LOCK_SUFFIX,
    is_model_file,
    is_transient_artifact,
)


def test_lock_is_not_a_model():
    assert is_transient_artifact("m.safetensors.lock")
    assert not is_model_file("m.safetensors.lock")
    assert LOCK_SUFFIX == ".lock"


def test_sidecars_are_not_models():
    for sidecar in ("m.safetensors.json", "m.safetensors.preview.png", "m.safetensors.sha256"):
        assert not is_model_file(sidecar), sidecar


def test_real_models_are_models():
    assert is_model_file("m.safetensors")
    assert is_model_file("m.ckpt")
    assert is_model_file("m.gguf")


def test_in_flight_download_is_not_a_model():
    assert is_transient_artifact("m.safetensors.1234.deadbeef.downloading")
    assert not is_model_file("m.safetensors.1234.deadbeef.downloading")


def test_splitext_would_have_matched_the_sidecar():
    """The mechanism of the original bug, pinned so the guard stays necessary."""
    assert os.path.splitext("m.safetensors.lock")[0] == "m.safetensors"


def test_pending_download_paths_finds_every_attempt(tmp_path):
    target = tmp_path / "m.safetensors"
    first = _unique_temp_path(str(target))
    second = _unique_temp_path(str(target))
    for path in (first, second):
        with open(path, "w"):
            pass
    unrelated = tmp_path / "other.safetensors.1.aa.downloading"
    with open(unrelated, "w"):
        pass

    found = {os.path.basename(p) for p in pending_download_paths(str(target))}
    assert found == {os.path.basename(first), os.path.basename(second)}


def test_pending_download_paths_is_empty_when_dir_is_gone(tmp_path):
    assert list(pending_download_paths(str(tmp_path / "nope" / "m.safetensors"))) == []


@pytest.mark.parametrize(
    "name",
    [
        "m.safetensors.lock",
        "m.safetensors.1234.deadbeef.downloading",
        "m.safetensors.json",
        "m.safetensors.preview.png",
    ],
)
def test_validate_dir_leaves_pipeline_files_alone(name):
    """The engine validation helpers must return `None`/skip for these names.

    `modal_app._validate_file` and `beam_app._validate_dir` are the functions
    that were deleting them. They are exercised through the shared predicate
    they now branch on, which is what keeps the two engines from drifting again.
    """
    from provider_core.utils import is_model_file

    assert not is_model_file(name)
