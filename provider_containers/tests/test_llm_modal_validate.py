"""The LLM Modal engine classified every model as invalid and deleted it.

`llm_worker/engines/modal/modal_app.py` `validate_models` re-implemented the
magic-byte check that `provider_core/validation.py` already owns, and unpacked
the table backwards. `VALID_FILE_HEADERS` maps *magic bytes* to a *format
name* (`{b"PK": "zip/ckpt", b"GGUF": "gguf", ...}`), but the loop bound the
format name to `expected` and compared it against a bytes slice:

    for header_sig, expected in VALID_HEADERS.items():
        if header[:len(expected)] == expected:   # bytes slice == str -> always False

`bytes != str` in Python 3, so the branch was never taken. Every file over
`MIN_MODEL_SIZE` fell through to `{"status": "invalid", "reason": "Unknown file
format"}`, and `validate_directory` then removed it when `delete_invalid` was
set. Reconciliation hardcodes `validate_existing(True)`
(`provider_core/reconciliation.py`), so step 0 of the two-hourly loop deleted
every model on the volume.

The image engine's twin calls the shared `validate_downloaded_file` and is
covered by `tests/test_modal_validate_partials.py`. This is the third copy, and
it was the only one that did not.
"""

from __future__ import annotations

import pytest

from provider_core.utils import DOWNLOADING_SUFFIX, LOCK_SUFFIX


@pytest.fixture
def llm_modal_app(monkeypatch, tmp_path):
    """`llm_worker.engines.modal.modal_app`, rooted at a temp directory.

    Mirrors the image-engine fixture in `test_modal_validate_partials.py`:
    `@app.function` exposes `.local(...)`, which calls the undecorated
    coroutine, so this exercises the real deployed function rather than a grep
    for a string that a correct implementation also contains.
    """
    import llm_worker.engines.modal.modal_app as app

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


def _write(directory, name, body):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(body)
    return path


def _gguf():
    """A GGUF body: the magic is what `VALID_FILE_HEADERS` keys on, so this is
    the exact file shape the inverted comparison failed to recognise."""
    return b"GGUF" + b"\x00" * 20000


def _safetensors():
    """A real safetensors prefix: 8-byte little-endian header length, then the
    JSON header. `validate_downloaded_file` parses this, so a made-up blob with
    the right magic in front of it is correctly rejected as corrupt."""
    header = b'{"__metadata__":{"format":"pt"},"tensors":{}}'
    return len(header).to_bytes(8, "little") + header + b"\x00" * 20000


def _corrupt_safetensors():
    """Right magic, impossible header length — a truncated transfer of a real
    `.safetensors`, which the deep header parse is there to catch."""
    return b'{"__metadata__' + (2**62).to_bytes(8, "little") + b"\x00" * 20000


# Both formats the LLM engines actually ship, so the test would have failed on
# the real bug whichever one the volume happened to hold.
_GGUF = _gguf()
_SAFETENSORS = _safetensors()


class TestTheLLMModalEngineRecognisesItsOwnModels:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "name,body",
        [("model.gguf", _GGUF), ("model.safetensors", _SAFETENSORS)],
    )
    async def test_a_real_model_is_valid(self, llm_modal_app, tmp_path, name, body):
        _write(tmp_path / "models", name, body)

        result = await llm_modal_app.validate_models.local(["models"], False)

        assert result["total_valid"] == 1, (
            "every LLM model was reported invalid: the magic-byte table was "
            "unpacked backwards, so bytes were compared to a format name"
        )
        assert result["total_invalid"] == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "name,body",
        [("model.gguf", _GGUF), ("model.safetensors", _SAFETENSORS)],
    )
    async def test_reconciliation_does_not_delete_a_real_model(
        self, llm_modal_app, tmp_path, name, body
    ):
        """The one that mattered: `reconciliation.py` calls this with True.

        Every tick of the two-hourly loop ran `os.remove` over the whole
        `models/` directory, so this is the assertion that would have caught it.
        """
        model = _write(tmp_path / "models", name, body)

        result = await llm_modal_app.validate_models.local(["models"], True)

        assert result["total_valid"] == 1
        assert result["total_invalid"] == 0
        assert model.exists(), "reconciliation deleted a valid model off the volume"

    @pytest.mark.asyncio
    async def test_a_genuinely_corrupt_model_is_still_swept(self, llm_modal_app, tmp_path):
        """The control: a real invalid file must still be classified and removed.

        A truncated `.safetensors` — right magic, impossible header length —
        is the case the deep header parse exists for. An *unknown* header over
        the size floor is deliberately only warned about, because that is the
        path a legitimately new model format takes.
        """
        broken = _write(tmp_path / "models", "truncated.safetensors", _corrupt_safetensors())

        result = await llm_modal_app.validate_models.local(["models"], True)

        assert result["total_invalid"] == 1
        assert not broken.exists(), "delete_invalid must still sweep a corrupt model"

    @pytest.mark.asyncio
    async def test_a_truncated_file_below_the_size_floor_is_partial_not_invalid(
        self, llm_modal_app, tmp_path
    ):
        """Under `MIN_MODEL_SIZE` means "transfer did not finish", not "corrupt".

        Classified and reported, never unlinked: whether an undersized file is
        an abandoned attempt is `pending_download_paths`' judgement to make,
        not the validator's.
        """
        stub = _write(tmp_path / "models", "half.gguf", b"GGUF" + b"\x00" * 512)

        result = await llm_modal_app.validate_models.local(["models"], True)

        assert result["total_partial"] == 1
        assert result["total_invalid"] == 0
        assert stub.exists(), "a possibly-in-flight transfer was unlinked"

    @pytest.mark.asyncio
    async def test_an_in_flight_temp_is_partial_and_never_deleted(
        self, llm_modal_app, tmp_path
    ):
        """A partial download is reported, never unlinked.

        Removing an in-flight temp leaves its writer holding a live descriptor:
        it transfers the whole file and then fails at `os.replace`, which
        reconciliation reports as a failed download. `provider_core/utils.py`
        records this having happened.
        """
        temp = _write(
            tmp_path / "models", f"model.gguf.4242.abcdef01{DOWNLOADING_SUFFIX}", b"7GB so far"
        )
        lock = _write(tmp_path / "models", f"model.gguf{LOCK_SUFFIX}", b"")

        result = await llm_modal_app.validate_models.local(["models"], True)

        assert temp.exists(), "an in-flight download was unlinked mid-transfer"
        assert lock.exists(), "a held flock was unlinked"
        assert result["total_partial"] == 2, (
            "total_partial feeds reconciliation step 0; reporting 0 for a "
            "directory that contains partials is what made it blind"
        )

    @pytest.mark.asyncio
    async def test_a_model_alongside_a_partial_still_counts_as_valid(
        self, llm_modal_app, tmp_path
    ):
        """Classification must be per-file, not per-directory."""
        _write(tmp_path / "models", "model.gguf", _GGUF)
        _write(tmp_path / "models", f"model2.gguf.99.deadbeef{DOWNLOADING_SUFFIX}", b"partial")

        result = await llm_modal_app.validate_models.local(["models"], True)

        assert result["total_valid"] == 1
        assert result["total_partial"] == 1

    @pytest.mark.asyncio
    async def test_a_sidecar_is_not_counted_as_a_model(self, llm_modal_app, tmp_path):
        """`model.gguf.json` is metadata that belongs to the model, not a model.

        A sidecar swept as an invalid model takes the model's own metadata with
        it — the incident `provider_core/utils.py` records.
        """
        _write(tmp_path / "models", "model.gguf", _GGUF)
        _write(tmp_path / "models", "model.gguf.json", b'{"name": "model"}')

        result = await llm_modal_app.validate_models.local(["models"], True)

        assert result["total_valid"] == 1
        assert result["total_invalid"] == 0
        assert result["total_partial"] == 0
        assert (tmp_path / "models" / "model.gguf.json").exists()
