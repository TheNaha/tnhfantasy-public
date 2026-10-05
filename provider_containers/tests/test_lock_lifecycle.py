"""`.lock` files: what may remove one, and what may not.

`exclusive_path_lock` creates `<model>.lock` and nothing unlinked it. A `.lock` is
a 0-byte transient artifact, so every validator counted it as `partial` — which
means `total_partial` grew by one for every model ever downloaded and stopped
meaning "a transfer is in flight", the only thing reconciliation step 0 reads it
for.

Two ends, and they are not symmetric:

* An **operator-initiated delete** (`/delete-model`, `/delete-file`,
  `FileStorage.delete_file`) may sweep the lock. The user asked for that model to
  go, so a lock beside it belongs to it, and `pipeline_artifacts` is the single
  helper that names all three kinds.

* A **validator** may not. Validation runs unattended with `delete_invalid=True`,
  and `provider_core/utils.py` records what happens when it did: the lock was
  `os.remove`d, and because `os.path.splitext("x.safetensors.lock")[0]` is
  `"x.safetensors"`, the model's own `.json` and `.preview.png` went with it.
  Unlinking a *held* lock also defeats it — a second downloader `O_CREAT`s a new
  inode, takes a different flock, and the interleaving corruption the lock
  exists to prevent happens again.

* A **completed download** may remove its own lock, because it has published the
  model and left no resume slot. A *failed* one must not, so the resuming
  attempt flocks the same inode — which is why the release is a separate,
  explicit call and not a side effect of leaving the `with` block.
"""

from __future__ import annotations

import importlib
import os
import pathlib

import pytest
from requests.structures import CaseInsensitiveDict

from provider_core.downloads import (
    download_model_to_path,
    pending_download_paths,
    pipeline_artifacts,
)
from provider_core.utils import LOCK_SUFFIX

PROVIDER_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = PROVIDER_ROOT.parent

_BEAM_APP = PROVIDER_ROOT / "image_worker" / "engines" / "beam" / "beam_app.py"
_IMAGE_MODAL_APP = PROVIDER_ROOT / "image_worker" / "engines" / "modal" / "modal_app.py"
_LLM_MODAL_APP = PROVIDER_ROOT / "llm_worker" / "engines" / "modal" / "modal_app.py"
_AGENT_SERVER = REPO_ROOT / "remote_agent" / "server.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class _Origin:
    """A stand-in for `requests.get` that can drop the connection mid-body."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.drop_after: int | None = None
        self.drop_requests = 0
        self.requests: list[dict] = []

    def __call__(self, url, **kwargs):
        headers = kwargs.get("headers") or {}
        self.requests.append({"url": url, "range": headers.get("Range"), **kwargs})
        # `requests.structures.CaseInsensitiveDict`, because that is exactly what
        # `requests.get(...).headers` is. A plain `dict` made `headers.get
        # ("content-length")` miss the `"Content-Length"` this fixture writes, so
        # `total_size` came out 0 for every response and *no size check ran at
        # all* — which is how a truncated chunked download could publish
        # (`provider_core/downloads.py`, `_attempt_download`). The double has to
        # honour the real header semantics or it cannot see those checks.
        response_headers = CaseInsensitiveDict(
            {
                "Content-Length": str(len(self.body)),
                "ETag": '"v1"',
            }
        )
        if headers.get("Range"):
            response_headers["Content-Range"] = f"bytes 0-{len(self.body) - 1}/{len(self.body)}"

        self.drop_requests -= 1
        if self.drop_requests <= 0:
            self.drop_requests = 0
            if self.drop_after is not None:
                self.drop_after = None
                return _Truncated(response_headers)
        return _Body(self.body, response_headers)


class _Body:
    def __init__(self, body: bytes, headers: dict) -> None:
        self._body = body
        self.status_code = 200
        self.headers = headers

    def iter_content(self, chunk_size=1):
        for offset in range(0, len(self._body), chunk_size):
            yield self._body[offset: offset + chunk_size]

    def close(self):
        pass


class _Truncated(_Body):
    """200 with a body that dies partway — the resume case."""

    def __init__(self, headers: dict) -> None:
        super().__init__(b"", headers)
        self._sent = 0

    def iter_content(self, chunk_size=1):
        yield b"x" * 1024
        raise OSError("connection reset by peer")


@pytest.fixture
def origin(monkeypatch):
    def _factory(body: bytes):
        server = _Origin(body)
        monkeypatch.setattr("provider_core.downloads.requests.get", server)
        return server

    return _factory


def _model_bytes(size: int = 128 * 1024) -> bytes:
    import json
    import struct

    header = json.dumps({"__metadata__": {}, "w0": {}, "w1": {}}).encode()
    blob = struct.pack("<Q", len(header)) + header
    return blob + b"\x00" * (size - len(blob))


def _download(url, dest, **kwargs):
    return download_model_to_path(
        url=url,
        full_path=str(dest),
        path=os.path.basename(str(dest)),
        **kwargs,
    )


# ------------------------------------------------------------------ lifecycle


class TestASuccessfulDownloadLeavesNothingBehind:
    def test_the_lock_is_gone_afterwards(self, origin, tmp_path):
        """The whole point: a 0-byte lock beside a published model is counted as
        a `partial` by every validator, forever, and means nothing."""
        origin(_model_bytes())
        dest = tmp_path / "model.safetensors"

        result = _download("http://origin/m", dest)

        assert result["status"] == "success"
        assert dest.exists()
        assert not (tmp_path / f"model.safetensors{LOCK_SUFFIX}").exists()
        assert list(pending_download_paths(str(dest))) == []

    def test_the_model_is_actually_intact_when_the_lock_is_removed(self, origin, tmp_path):
        """Removing the lock must not become a reason to remove anything else."""
        body = _model_bytes()
        origin(body)
        dest = tmp_path / "model.safetensors"

        _download("http://origin/m", dest, metadata={"name": "m"}, preview_url=None)

        assert dest.read_bytes() == body
        # `splitext("model.safetensors")` is `("model", ".safetensors")`, so the
        # sidecar is `model.json` — the same reason `splitext` puts a `.lock`
        # back onto the model name.
        assert (tmp_path / "model.json").exists()

    def test_a_failed_download_keeps_its_lock(self, origin, tmp_path):
        """So the resuming attempt flocks the SAME inode.

        `test_download_resume.py::test_lock_is_still_held_across_a_resume` pins
        this against the real flock; here it is the contract stated on its own,
        because unlinking on failure is the obvious "simplification" that
        reintroduces the split-inode race.
        """
        server = origin(_model_bytes())
        server.drop_after = 1024
        server.drop_requests = 1
        dest = tmp_path / "model.safetensors"

        result = _download("http://origin/m", dest, max_attempts=1)

        assert result["status"] == "error"
        assert (tmp_path / f"model.safetensors{LOCK_SUFFIX}").exists()

    def test_a_download_that_raises_keeps_its_lock(self, origin, tmp_path):
        origin(_model_bytes())
        dest = tmp_path / "model.safetensors"

        with pytest.raises(ValueError):
            download_model_to_path(url="", full_path=str(dest), path="m")

        assert (tmp_path / f"model.safetensors{LOCK_SUFFIX}").exists()


# ------------------------------------------------------------- the sweep


class TestPipelineArtifactsNamesTheLock:
    def test_it_includes_the_lock_and_every_pending_download(self, tmp_path):
        dest = tmp_path / "model.safetensors"
        dest.write_bytes(b"x")
        lock = tmp_path / f"model.safetensors{LOCK_SUFFIX}"
        lock.write_bytes(b"")
        temp = tmp_path / "model.safetensors.4242.deadbeef.downloading"
        temp.write_bytes(b"partial")
        slot = tmp_path / "model.safetensors.resume.0123456789ab.downloading"
        slot.write_bytes(b"partial")

        found = {os.path.basename(p) for p in pipeline_artifacts(str(dest))}

        assert found == {lock.name, temp.name, slot.name}

    def test_pending_download_paths_alone_does_not_name_the_lock(self, tmp_path):
        """It is the "is a transfer in flight?" probe. A lock exists for a
        *waiting* downloader as much as a running one, so including it would make
        `delete-model` claim a model exists when only an abandoned lock does."""
        dest = tmp_path / "model.safetensors"
        dest.write_bytes(b"x")
        (tmp_path / f"model.safetensors{LOCK_SUFFIX}").write_bytes(b"")

        assert list(pending_download_paths(str(dest))) == []

    def test_it_is_empty_for_a_path_in_a_directory_that_does_not_exist(self, tmp_path):
        assert list(pipeline_artifacts(str(tmp_path / "nope" / "m.safetensors"))) == [
            str(tmp_path / "nope" / f"m.safetensors{LOCK_SUFFIX}")
        ]


class TestTheDeleteRoutesSweepTheLock:
    @pytest.mark.asyncio
    async def test_the_remote_agent_delete_removes_the_lock(self, tmp_path, monkeypatch):
        import remote_agent.server as server
        from provider_core.downloads import _HeldPathLock  # noqa: F401  (documents the pair)

        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        models = tmp_path / "models" / "checkpoints"
        models.mkdir(parents=True)
        model = models / "big.safetensors"
        model.write_bytes(b"x" * 100)
        lock = models / f"big.safetensors{LOCK_SUFFIX}"
        lock.write_bytes(b"")
        temp = models / "big.safetensors.4242.deadbeef.downloading"
        temp.write_bytes(b"7GB of partial")

        result = await server.delete_model(server.DeleteModelRequest(path="models/checkpoints/big.safetensors"))

        assert result["status"] == "success", result
        assert not model.exists()
        assert not lock.exists(), "the lock survived a delete of the model it belongs to"
        assert not temp.exists()

    @pytest.mark.asyncio
    async def test_a_lone_lock_is_not_mistaken_for_a_model(self, tmp_path, monkeypatch):
        """The reason `pipeline_artifacts` is not what gates the 'not found'
        answer: only an abandoned lock must not make a delete claim success."""
        import remote_agent.server as server

        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        models = tmp_path / "models"
        models.mkdir(parents=True)
        (models / f"ghost.safetensors{LOCK_SUFFIX}").write_bytes(b"")

        result = await server.delete_model(server.DeleteModelRequest(path="models/ghost.safetensors"))

        assert result["status"] == "error"
        assert result["code"] == 404

    @pytest.mark.parametrize(
        "path",
        [_BEAM_APP, _IMAGE_MODAL_APP, _LLM_MODAL_APP],
        ids=["beam", "image-modal", "llm-modal"],
    )
    def test_every_volume_delete_route_sweeps_pipeline_artifacts(self, path):
        """`beam_app.py` cannot be imported in this venv (the pinned `beta9` has
        no `rest_api`), so that one is pinned by source — the same escape hatch
        that let the Beam auth gate ship unaudited, which is why this names the
        helper rather than trusting a call count.

        The Beam file has two delete routes that had already drifted apart, so
        "the helper is imported" is not the assertion: every `for stale in` must
        have been rewritten to the helper that includes the lock.
        """
        src = _read(path)
        sweeps = src.count("for stale in pending_download_paths(")
        assert sweeps == 0, (
            f"{path.name} still sweeps only the .downloading family in {sweeps} "
            "place(s), so the model's lock outlives the model"
        )
        assert "pipeline_artifacts" in src, f"{path.name} never sweeps the lock"
        assert src.count("for stale in pipeline_artifacts(") >= 1
        # And each sweep must actually unlink, not merely enumerate.
        for block in src.split("for stale in pipeline_artifacts(")[1:]:
            body = block.split(")", 1)[1][:200]
            assert "remove" in body, f"{path.name} enumerates a pipeline artifact and drops it"

    def test_the_validators_still_refuse_to_delete_a_lock(self):
        """The other half, pinned so the sweep cannot spread. `utils.py` records
        the incident: the lock was removed, and because
        `splitext("x.safetensors.lock")[0] == "x.safetensors"` the model's `.json`
        and `.preview.png` went with it."""
        from provider_core.utils import is_model_file, is_transient_artifact

        assert is_transient_artifact("m.safetensors.lock")
        assert not is_model_file("m.safetensors.lock")

        for path in (_IMAGE_MODAL_APP, _LLM_MODAL_APP):
            src = _read(path)
            validate = src[src.index("def validate"):]
            assert "os.remove" not in validate.split("def ")[1], (
                f"{path.name}'s validator removes a file it only classified"
            )


def _neutralise_volume(modal_app, tmp_path, monkeypatch):
    """Point the app at `tmp_path` and take the real Modal volume out of it.

    `vol.reload()` and `vol.commit()` only work inside a running Modal function,
    and `get_safe_path` confines to `/mnt/data`, so without this the method under
    test is exercising Modal's plumbing rather than its sweep.
    """
    monkeypatch.setattr(modal_app, "get_safe_path", lambda base, path: str(tmp_path / path))
    monkeypatch.setattr(modal_app.vol, "reload", lambda: None)
    monkeypatch.setattr(modal_app.vol, "commit", lambda: None)


class TestTheModalDeleteRouteBehaviourally:
    """`image_worker.engines.modal.modal_app` DOES import in this venv, so its
    `FileStorage.delete_file` is exercised rather than pattern-matched."""

    def test_it_removes_the_lock_alongside_the_model(self, tmp_path, monkeypatch):
        import image_worker.engines.modal.modal_app as modal_app

        _neutralise_volume(modal_app, tmp_path, monkeypatch)
        storage = object.__new__(modal_app.FileStorage._get_user_cls())

        (tmp_path / "m.safetensors").write_bytes(b"x" * 100)
        (tmp_path / f"m.safetensors{LOCK_SUFFIX}").write_bytes(b"")
        (tmp_path / "m.safetensors.4242.deadbeef.downloading").write_bytes(b"partial")
        # `splitext("m.safetensors")` is `("m", ".safetensors")`, so the
        # sidecar is `m.json`.
        (tmp_path / "m.json").write_text("{}")

        import asyncio

        assert asyncio.run(storage.delete_file("m.safetensors")) is True

        assert not (tmp_path / "m.safetensors").exists()
        assert not (tmp_path / f"m.safetensors{LOCK_SUFFIX}").exists()
        assert not (tmp_path / "m.safetensors.4242.deadbeef.downloading").exists()
        assert not (tmp_path / "m.json").exists()

    def test_a_lock_released_before_the_sweep_does_not_fail_the_delete(self, tmp_path, monkeypatch):
        """Artifacts are enumerated first and unlinked second, so the download
        that finished between the two has already removed its own lock. An
        unlink that raised here would abort the delete — model included — over a
        0-byte file nobody asked to keep."""
        import asyncio

        import image_worker.engines.modal.modal_app as modal_app

        _neutralise_volume(modal_app, tmp_path, monkeypatch)
        (tmp_path / "m.safetensors").write_bytes(b"x" * 100)

        real_exists = os.path.exists
        lock = tmp_path / f"m.safetensors{LOCK_SUFFIX}"
        lock.write_bytes(b"")

        def exists_then_vanish(path):
            if str(path) == str(lock):
                lock.unlink()
                return True
            return real_exists(path)

        monkeypatch.setattr(modal_app.os.path, "exists", exists_then_vanish)

        storage = object.__new__(modal_app.FileStorage._get_user_cls())
        assert asyncio.run(storage.delete_file("m.safetensors")) is True


def test_the_helpers_are_importable_on_their_own():
    for name in ("exclusive_path_lock", "pipeline_artifacts", "_HeldPathLock"):
        assert hasattr(importlib.import_module("provider_core.downloads"), name)
