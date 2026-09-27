"""The Modal engine reported `total_partial: 0` forever.

`image_worker/engines/modal/modal_app.py` `validate_models` filtered directory
entries with `is_model_file` and returned `None` for anything it excluded — which
is every name the download pipeline owns, `.lock` and `.downloading` among them.
The `.downloading` branch further down was therefore unreachable, and
`total_partial` was permanently 0 for this engine while remote_comfy and the
remote agent both reported real counts. Step 0 of reconciliation reads that
number (`provider_core/reconciliation.py`), so on Modal it could never converge.

This calls the deployed function rather than grepping it: the grep that used to
stand in for this (`tests/test_pipeline_artifacts.py`) only asserted that the
string `is_model_file` appears in the file, which is exactly what a *correct*
implementation also contains — the filter being in the wrong place is invisible
to it.
"""

from __future__ import annotations

import pytest

from provider_core.utils import DOWNLOADING_SUFFIX, LOCK_SUFFIX


@pytest.fixture
def modal_app(monkeypatch, tmp_path):
    """`image_worker.engines.modal.modal_app`, rooted at a temp directory.

    The module is importable (modal is a test dependency) and `@app.function`
    exposes `.local(...)`, which calls the undecorated coroutine. Only two
    things are bound to Modal infrastructure — `vol` and the `/mnt/data` prefix
    `get_safe_path` resolves against — and both are redirected.
    """
    import image_worker.engines.modal.modal_app as app

    async def _no_reload():
        return None

    class _Commit:
        async def aio(self):
            return None

    class _Vol:
        commit = _Commit()

    monkeypatch.setattr(app, "safe_vol_reload_aio", _no_reload)
    monkeypatch.setattr(app, "vol", _Vol())
    monkeypatch.setattr(
        app, "get_safe_path", lambda base, requested: str(tmp_path / requested)
    )
    return app


def _valid_ckpt(directory, name="real.ckpt"):
    """A file that passes `validate_downloaded_file`: a zip body, over MIN_MODEL_SIZE."""
    path = directory / name
    path.write_bytes(b"PK" + b"\x00" * 20000)
    return path


class TestTheModalEngineSeesPartials:
    @pytest.mark.asyncio
    async def test_an_in_flight_download_temp_is_reported_as_partial(self, modal_app, tmp_path):
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        temp = directory / f"real.ckpt.4242.abcdef01{DOWNLOADING_SUFFIX}"
        temp.write_bytes(b"7GB of partial")

        result = await modal_app.validate_models.local(["models/checkpoints"], False)

        assert result["total_partial"] == 1, (
            "total_partial was permanently 0 for the Modal engine, so "
            "reconciliation step 0 could never reach zero here"
        )
        entry = result["by_directory"]["models/checkpoints"]["partial_files"][0]
        assert entry["name"] == temp.name
        assert entry["size"] == len(b"7GB of partial")

    @pytest.mark.asyncio
    async def test_a_lock_is_reported_as_partial_too(self, modal_app, tmp_path):
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        _valid_ckpt(directory)
        (directory / f"real.ckpt{LOCK_SUFFIX}").write_bytes(b"")

        result = await modal_app.validate_models.local(["models/checkpoints"], False)

        assert result["total_partial"] == 1
        names = {e["name"] for e in result["by_directory"]["models/checkpoints"]["partial_files"]}
        assert f"real.ckpt{LOCK_SUFFIX}" in names

    @pytest.mark.asyncio
    async def test_delete_invalid_does_not_unlink_a_pipeline_artifact(
        self, modal_app, tmp_path
    ):
        """The one place the audit's suggested fix had to be overridden.

        Reconciliation calls this with `delete_invalid=True`. Removing an
        in-flight temp leaves its writer holding a live descriptor — it finishes
        the transfer and then fails at `os.replace`, which reconciliation reports
        as a failed download. Removing the `.lock` additionally unlinks a held
        flock, and because `splitext("x.safetensors.lock")[0] == "x.safetensors"`
        it takes the model's own metadata and preview with it. That is not
        hypothetical: `provider_core/utils.py` (TRANSIENT_SUFFIXES) records it
        happening. Abandoned partials are reclaimed by `FileStorage.delete_file`
        through `pending_download_paths`, which is the only place that can tell
        an in-flight attempt from a dead one — the same rule
        `remote_agent/server.py` `_validate_dir` already follows.
        """
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        model = _valid_ckpt(directory)
        (model.parent / "real.ckpt.json").write_bytes(b'{"name": "real"}')
        temp = directory / f"real.ckpt.4242.abcdef01{DOWNLOADING_SUFFIX}"
        temp.write_bytes(b"7GB of partial")
        lock = directory / f"real.ckpt{LOCK_SUFFIX}"
        lock.write_bytes(b"")

        result = await modal_app.validate_models.local(["models/checkpoints"], True)

        assert result["total_partial"] == 2
        assert temp.exists(), "an in-flight download was unlinked mid-transfer"
        assert lock.exists(), "a held flock was unlinked"
        assert model.exists()
        assert (model.parent / "real.ckpt.json").exists()

    @pytest.mark.asyncio
    async def test_a_real_model_is_still_validated_and_invalid_swept(
        self, modal_app, tmp_path
    ):
        """The control: classification must not change the model path."""
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        _valid_ckpt(directory, "good.ckpt")
        # Under MIN_MODEL_SIZE (10 KiB), so `validate_downloaded_file` rejects it
        # on size. An unknown *header* over the size floor is only warned about,
        # which is deliberate: it is the same path a legitimately new model
        # format takes.
        broken = directory / "truncated.ckpt"
        broken.write_bytes(b"PK" + b"\x00" * 4096)

        result = await modal_app.validate_models.local(["models/checkpoints"], True)

        assert result["total_valid"] == 1
        assert result["total_invalid"] == 1
        assert not broken.exists(), "delete_invalid must still sweep a broken model"
