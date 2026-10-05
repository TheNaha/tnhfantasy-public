"""A failed directory scan must not read as "this directory holds no models".

Step 3 of reconciliation (`provider_core/reconciliation.py`) computes

    missing_files = all_expected_paths - existing_files

and re-downloads every entry. So "the scan failed" and "the directory is empty"
are not the same answer — the first re-fetches every multi-GB checkpoint in the
directory, on the volume whose failure triggered it.

All three listing implementations caught `os.scandir` failures and returned an
empty result; the remote agent's did not. Two copies of one function disagreeing
about the one error that must not be swallowed is the whole defect, so the tests
below assert the shared rule rather than any one module's shape.
"""

from __future__ import annotations

import os

import pytest

MODULES = ("models_utils", "image_modal", "llm_modal")


@pytest.fixture
def checkpoints(tmp_path):
    directory = tmp_path / "models" / "checkpoints"
    directory.mkdir(parents=True)
    for name in ("a.ckpt", "b.ckpt"):
        (directory / name).write_bytes(b"PK" + b"\x00" * 20000)
    return directory


def _fail_scandir_for(path):
    """An `os.scandir` that raises EIO for `path` and works everywhere else.

    The real fault is a gcsfuse `EIO` on a Modal volume mount, or a hiccup on a
    network volume — the same fault the validation twin-parity suite injects.
    """
    real = os.scandir

    def _fake(target):
        if os.path.abspath(str(target)) == os.path.abspath(str(path)):
            raise OSError(5, "Input/output error")
        return real(target)

    return _fake


class _EntryWithFailingStat:
    """A `DirEntry` proxy whose `stat()` raises for one name."""

    def __init__(self, entry, fail_name):
        self._entry = entry
        self._fail_name = fail_name

    @property
    def name(self):
        return self._entry.name

    def is_file(self, *a, **kw):
        return self._entry.is_file(*a, **kw)

    def stat(self, *a, **kw):
        if self.name == self._fail_name:
            raise OSError(5, "Input/output error")
        return self._entry.stat(*a, **kw)


def _fail_entry_stat_for(directory, fail_name):
    real = os.scandir

    class _Iter:
        def __init__(self, it):
            self._it = it

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._it.close()
            return False

        def __iter__(self):
            return self

        def __next__(self):
            return _EntryWithFailingStat(next(self._it), fail_name)

    def _fake(target):
        it = real(target)
        if os.path.abspath(str(target)) != os.path.abspath(str(directory)):
            return it
        return _Iter(it)

    return _fake


def _listing_module(which):
    import image_worker.comfy.models_utils as models_utils
    import image_worker.engines.modal.modal_app as image_modal
    import llm_worker.engines.modal.modal_app as llm_modal

    return {
        "models_utils": models_utils,
        "image_modal": image_modal,
        "llm_modal": llm_modal,
    }[which]


class TestTheSharedScanRaises:
    def test_scandir_failure_propagates(self, checkpoints, monkeypatch):
        from provider_core.model_scan import scan_model_directory

        monkeypatch.setattr(os, "scandir", _fail_scandir_for(checkpoints))

        with pytest.raises(OSError):
            scan_model_directory(str(checkpoints))

    def test_a_failed_stat_propagates_rather_than_returning_a_short_list(
        self, checkpoints, monkeypatch
    ):
        """A stat that fails mid-scan must not yield a partial result.

        A partial result is the exact shape of the bug: reconciliation cannot tell
        "one file's stat failed" from "that file does not exist", and both mean
        the model is missing, so both get re-downloaded.
        """
        from provider_core.model_scan import scan_model_directory

        monkeypatch.setattr(os, "scandir", _fail_entry_stat_for(checkpoints, "a.ckpt"))

        with pytest.raises(OSError):
            scan_model_directory(str(checkpoints))

    def test_a_genuinely_empty_directory_still_returns_empty(self, tmp_path):
        """The control: empty must stay empty, or the fix is satisfied by raising
        at everything and step 3 learns nothing."""
        from provider_core.model_scan import scan_model_directory

        empty = tmp_path / "loras"
        empty.mkdir()

        assert scan_model_directory(str(empty)) == ([], set())

    def test_the_scan_reports_a_populated_directory(self, checkpoints):
        from provider_core.model_scan import scan_model_directory

        entries, names = scan_model_directory(str(checkpoints))
        assert sorted(name for name, _size in entries) == ["a.ckpt", "b.ckpt"]
        assert "a.ckpt" in names and "b.ckpt" in names


class TestTheThreeListingImplementationsAgree:
    """`image_worker/comfy/models_utils.py` and the two Modal twins.

    Written as agreement across all three, because that is the failure mode: each
    looked correct on its own and two of the three silently answered "no models".
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("which", MODULES)
    async def test_a_failed_scan_raises_in_every_implementation(
        self, checkpoints, monkeypatch, which
    ):
        module = _listing_module(which)
        monkeypatch.setattr(
            module, "get_safe_path", lambda _base, requested: str(checkpoints)
        )
        monkeypatch.setattr(os, "scandir", _fail_scandir_for(checkpoints))

        with pytest.raises(OSError):
            await module.list_models_with_metadata_internal(
                "/mnt/data", "models/checkpoints"
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("which", MODULES)
    async def test_the_same_populated_directory_still_lists(
        self, checkpoints, monkeypatch, which
    ):
        """The control, so the raise cannot be satisfied by breaking listing."""
        module = _listing_module(which)
        monkeypatch.setattr(
            module, "get_safe_path", lambda _base, requested: str(checkpoints)
        )

        listed = await module.list_models_with_metadata_internal(
            "/mnt/data", "models/checkpoints"
        )
        assert sorted(f["name"] for f in listed) == ["a.ckpt", "b.ckpt"]


class TestTheRemoteAgentAlreadyFailedLoud:
    """`remote_agent/server.py`'s `/list-models` is the reference implementation.

    Its `_walk` has never had a catch, which is what made the divergence visible:
    it aborted step 3 while Modal and Beam answered "no models" and re-downloaded.
    Pinned so the next copy of this sweep has a rule to follow.
    """

    @pytest.mark.asyncio
    async def test_a_failed_stat_raises_through_list_models(
        self, checkpoints, monkeypatch, tmp_path
    ):
        import remote_agent.server as server

        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))

        real = os.path.getsize

        def _fake(path):
            if os.path.basename(str(path)) == "a.ckpt":
                raise OSError(5, "Input/output error")
            return real(path)

        monkeypatch.setattr(os.path, "getsize", _fake)

        with pytest.raises(OSError):
            await server.list_models(server.ListModelsRequest(directory="models/checkpoints"))

    @pytest.mark.asyncio
    async def test_a_readable_directory_still_lists_on_the_agent(
        self, checkpoints, monkeypatch, tmp_path
    ):
        import remote_agent.server as server

        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))

        result = await server.list_models(
            server.ListModelsRequest(directory="models/checkpoints")
        )
        assert sorted(f["name"] for f in result["files"]) == ["a.ckpt", "b.ckpt"]