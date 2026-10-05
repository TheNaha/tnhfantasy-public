"""The three `validate_models` implementations must agree, and none may abort.

The same logical sweep — walk a directory of model files, validate each one,
report the counts, optionally delete what is genuinely bad — exists in three
places, and the three disagreed in the direction that loses information:

| | image twin | LLM twin | remote agent |
|---|---|---|---|
| `os.path.getsize` on an unreadable file | unguarded (raised) | guarded -> `indeterminate` | unguarded (raised) |
| an `indeterminate` read reported as | `type: "invalid"` | a third bucket | appended to `invalid` |
| fan-out | `gather(...)` | n/a | `gather(...)` |

Three consequences, one per row. A stat that fails did not report one bad file —
it discarded the result of every *other* file in the sweep, because an unguarded
`asyncio.gather` re-raises the first exception and drops the rest. And
`total_invalid` counted three different quantities depending on which engine
answered, which is the number reconciliation reads to decide whether anything is
wrong.

`provider_core/validation.py` states why `indeterminate` exists at all: the read
FAILED (EIO, ENOMEM, a gcsfuse stall), which is not a verdict on the file, and
these sweeps run unattended with `delete_invalid=True` every couple of hours
against the operator's real network volume.

The tests below assert the RULE — the same sweep reports the same thing on every
implementation — rather than each file's field list, so an implementation cannot
be "fixed" by agreeing with a transcribed copy.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def modal_image_app(monkeypatch, tmp_path):
    """`image_worker.engines.modal.modal_app`, rooted at a temp directory."""
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


@pytest.fixture
def modal_llm_app(monkeypatch, tmp_path):
    """`llm_worker.engines.modal.modal_app`, rooted at a temp directory."""
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


def _good(directory, name):
    """A file that passes `validate_downloaded_file`: zip body, over the size floor."""
    path = directory / name
    path.write_bytes(b"PK" + b"\x00" * 20000)
    return path


def _broken(directory, name):
    """Under `MIN_MODEL_SIZE`, so validation rejects it on size."""
    path = directory / name
    path.write_bytes(b"PK" + b"\x00" * 4096)
    return path


def _make_getsize_fail(*names):
    """A `os.path.getsize` that raises EIO for `names` and works for everything else.

    This is the fault the guard exists for. The real one is a gcsfuse `EIO` on a
    Modal volume mount, which is why the validators distinguish it from a verdict.

    Two call sites in the LLM twin are reached by this, and both are the same
    fault: a model file's own size (already guarded, classified `indeterminate`)
    and a *transient artifact's* size (unguarded until this pass, and the one that
    aborted the whole 16-directory sweep).
    """
    real = os.path.getsize

    def _fake(path):
        if os.path.basename(str(path)) in names:
            raise OSError(5, "Input/output error")
        return real(path)

    return _fake


def _make_listdir_fail(*fragments):
    """An `os.listdir` that raises EIO for paths containing any `fragments`.

    A sibling of `_make_getsize_fail` for the other unwrapped call: the LLM twin's
    `validate_directory` iterated `os.listdir(full_dir)` with no `try`, so one EIO
    on the directory raised out of the sweep rather than being reported against
    that directory. Matching on a path fragment keeps the injection independent of
    the temp directory pytest hands out.
    """
    real = os.listdir

    def _fake(path):
        text = str(path)
        if any(fragment in text for fragment in fragments):
            raise OSError(5, "Input/output error")
        return real(path)

    return _fake


class TestImageTwinSurvivesAnUnreadableFile:
    @pytest.mark.asyncio
    async def test_a_failed_stat_does_not_discard_the_other_files(
        self, modal_image_app, tmp_path, monkeypatch
    ):
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        _good(directory, "a.ckpt")
        _good(directory, "b.ckpt")
        _good(directory, "c.ckpt")
        unreadable = _good(directory, "eio.ckpt")

        monkeypatch.setattr(
            os.path, "getsize", _make_getsize_fail("eio.ckpt")
        )

        result = await modal_image_app.validate_models.local(["models/checkpoints"], True)

        # The property: three readable files are still accounted for. Before the
        # fix this raised out of the unguarded `asyncio.gather` and the caller
        # got nothing at all — one EIO on one file erased the state of the rest.
        assert result["total_valid"] == 3, result
        assert result["total_indeterminate"] == 1, result
        assert unreadable.exists(), "an unreadable file must never be deleted"

    @pytest.mark.asyncio
    async def test_an_indeterminate_read_is_not_counted_as_invalid(
        self, modal_image_app, tmp_path, monkeypatch
    ):
        """`total_invalid` means "read, and bad" — on every engine.

        It used to mean "read and bad, or we could not read", so the image twin's
        number was not comparable with the LLM twin's, which has excluded them
        since 2026-09-29.
        """
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        _good(directory, "a.ckpt")
        _broken(directory, "small.ckpt")
        _good(directory, "eio.ckpt")

        monkeypatch.setattr(os.path, "getsize", _make_getsize_fail("eio.ckpt"))

        result = await modal_image_app.validate_models.local(["models/checkpoints"], True)

        assert result["total_invalid"] == 1, "the genuinely broken file"
        assert result["total_valid"] == 1
        assert result["total_indeterminate"] == 1, "and the unreadable one is its own bucket"
        by_dir = result["by_directory"]["models/checkpoints"]
        assert by_dir["indeterminate"] == 1
        assert by_dir["indeterminate_files"][0]["name"] == "eio.ckpt"


class TestImageTwinContentLevelIndeterminate:
    @pytest.mark.asyncio
    async def test_a_validation_that_could_not_read_gets_its_own_type(
        self, modal_image_app, tmp_path, monkeypatch
    ):
        """The read-fault case that is not a stat fault.

        `validate_downloaded_file` returns `indeterminate` when the file's *content*
        cannot be read — which is the case the LLM twin already handled and the
        image twin reported as `type: "invalid"`.
        """
        import provider_core.validation as validation_mod

        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        unreadable = _good(directory, "unreadable.ckpt")
        _good(directory, "fine.ckpt")

        real = validation_mod.validate_downloaded_file

        def _faulty(path, total_size=0, **kwargs):
            if os.path.basename(str(path)) == "unreadable.ckpt":
                return {
                    "valid": False,
                    "indeterminate": True,
                    "error": "Could not read file: [Errno 5] Input/output error",
                }
            return real(path, total_size, **kwargs)

        monkeypatch.setattr(validation_mod, "validate_downloaded_file", _faulty)
        monkeypatch.setattr(modal_image_app, "validate_downloaded_file", _faulty, raising=False)

        result = await modal_image_app.validate_models.local(["models/checkpoints"], True)

        assert result["total_valid"] == 1
        assert result["total_invalid"] == 0, "an unreadable file is not an invalid one"
        assert result["total_indeterminate"] == 1
        assert unreadable.exists(), "and it must not be swept"


class TestTheTwinsAgreeOnWhatTheyReport:
    @pytest.mark.asyncio
    async def test_the_same_directory_gives_the_same_counts_on_both_engines(
        self, modal_image_app, modal_llm_app, tmp_path, monkeypatch
    ):
        """The rule: identical directory -> identical verdicts.

        Written as agreement between the two implementations rather than as two
        expected dicts, because the failure being prevented is precisely that the
        two answers drifted apart while both still looked reasonable.

        Scope, and why it stops short of `total_partial`: the twins deliberately
        classify a too-small file differently — the LLM twin calls it `partial`
        (a truncated transfer, left on disk) and the image twin calls it `invalid`
        and sweeps it. That divergence is documented at
        `llm_worker/engines/modal/modal_app.py` ("A file under the size floor is a
        truncated transfer, not a corrupt model") and is not what this test is
        about. What must agree is the unreadable case, which used to land in
        `total_invalid` on the image twin and in a third bucket here.
        """
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        _good(directory, "good.ckpt")
        _good(directory, "unreadable.ckpt")

        import provider_core.validation as validation_mod

        real = validation_mod.validate_downloaded_file

        def _faulty(path, total_size=0, **kwargs):
            if os.path.basename(str(path)) == "unreadable.ckpt":
                return {
                    "valid": False,
                    "indeterminate": True,
                    "error": "Could not read file: [Errno 5] Input/output error",
                }
            return real(path, total_size, **kwargs)

        # Both modal apps import the validator BY NAME (`llm_worker/.../modal_app.py:16`,
        # and the image one lazily inside the function), so each holds its own
        # binding. Patching the source module would reach neither.
        monkeypatch.setattr(validation_mod, "validate_downloaded_file", _faulty)
        monkeypatch.setattr(modal_image_app, "validate_downloaded_file", _faulty, raising=False)
        monkeypatch.setattr(modal_llm_app, "validate_downloaded_file", _faulty)

        image = await modal_image_app.validate_models.local(["models/checkpoints"], False)
        llm = await modal_llm_app.validate_models.local(["models/checkpoints"], False)

        for bucket in ("total_valid", "total_invalid", "total_partial", "total_indeterminate"):
            assert bucket in image, f"the image twin does not report {bucket} at all"
            assert bucket in llm, f"the LLM twin does not report {bucket} at all"
            assert image[bucket] == llm[bucket], (
                f"{bucket} disagrees between the image and LLM validators: "
                f"image={image[bucket]} llm={llm[bucket]}"
            )

        assert image["total_valid"] == llm["total_valid"] == 1
        assert image["total_indeterminate"] == llm["total_indeterminate"] == 1
        assert image["total_invalid"] == llm["total_invalid"] == 0, (
            "an unreadable file counted as invalid on one engine only"
        )
        assert (directory / "unreadable.ckpt").exists()


class TestRemoteAgentValidateDir:
    """`remote_agent/server.py` `_validate_dir` — the third implementation.

    Covered here rather than in the remote agent's own suite because the agent is
    a sibling package that imports `provider_core`, so this file already has it on
    `sys.path` (see `tests/conftest.py`), and the point being pinned is that the
    three agree.
    """

    def _module(self, monkeypatch, tmp_path):
        import remote_agent.server as server

        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        return server

    def test_an_unreadable_file_is_indeterminate_not_invalid(self, monkeypatch, tmp_path):
        server = self._module(monkeypatch, tmp_path)
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        _good(directory, "good.ckpt")
        unreadable = _good(directory, "eio.ckpt")

        real = os.path.getsize
        monkeypatch.setattr(
            os.path,
            "getsize",
            lambda p: (_ for _ in ()).throw(OSError(5, "Input/output error"))
            if os.path.basename(str(p)) == "eio.ckpt"
            else real(p),
        )

        result = server._validate_dir(str(directory), True)

        assert result["total_valid"] == 1
        assert result["total_invalid"] == 0, "a stat that failed is not a verdict"
        assert result["total_indeterminate"] == 1
        assert unreadable.exists()
        # The count the rest of the system reads must exclude it, as on Modal.
        assert result["total"] == 2

    def test_an_indeterminate_validation_is_not_counted_as_invalid(self, monkeypatch, tmp_path):
        server = self._module(monkeypatch, tmp_path)
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        unreadable = _good(directory, "unreadable.ckpt")

        import provider_core.validation as validation_mod

        real = validation_mod.validate_downloaded_file

        def _faulty(path, total_size=0, **kwargs):
            if os.path.basename(str(path)) == "unreadable.ckpt":
                return {
                    "valid": False,
                    "indeterminate": True,
                    "error": "Could not read file: [Errno 5] Input/output error",
                }
            return real(path, total_size, **kwargs)

        # Patched on the *agent's* name: `remote_agent/server.py` does
        # `from provider_core.validation import validate_downloaded_file`, so it
        # holds its own binding and patching the source module would not reach it.
        monkeypatch.setattr(server, "validate_downloaded_file", _faulty)

        result = server._validate_dir(str(directory), True)

        assert result["total_invalid"] == 0
        assert result["total_indeterminate"] == 1
        assert unreadable.exists(), "an unreadable model must never be deleted"

    def test_a_genuinely_invalid_file_is_still_invalid_and_swept(self, monkeypatch, tmp_path):
        """The control, so "indeterminate" cannot be satisfied by never deleting."""
        server = self._module(monkeypatch, tmp_path)
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        broken = _broken(directory, "small.ckpt")

        result = server._validate_dir(str(directory), True)

        assert result["total_invalid"] == 1
        assert result["total_indeterminate"] == 0
        assert not broken.exists(), "delete_invalid must still sweep a broken model"


class TestLlmTwinOneDirectoryCannotDiscardTheOtherFifteen:
    """The LLM validator's 16-directory loop had no `try` anywhere.

    Reproduced: an unguarded `os.path.getsize` on a transient artifact raised
    `OSError: [Errno 28] No space left on device` out of `validate_models`, which
    `llm_worker/engines/modal/client.py` turned into `failed(...)`, which
    reconciliation's `except Exception` logged as "⚠ Validation step failed". Step 0
    then ran with no data at all — not just for the affected directory.

    `remote_agent/server.py::validate_models` is the reference: `return_exceptions=True`
    plus a per-directory `{"error": ...}` entry.
    """

    DIRECTORIES = ("models/checkpoints", "models/loras", "models/vae")

    @pytest.mark.asyncio
    async def test_a_transient_artifact_whose_stat_fails_does_not_abort_the_sweep(
        self, modal_llm_app, tmp_path, monkeypatch
    ):
        for directory in self.DIRECTORIES:
            (tmp_path / directory).mkdir(parents=True)
            _good(tmp_path / directory, "good.ckpt")
        artifact = "inflight.1234.abcdef12.downloading"
        (tmp_path / self.DIRECTORIES[0] / artifact).write_bytes(b"PK" + b"\x00" * 20000)

        monkeypatch.setattr(os.path, "getsize", _make_getsize_fail(artifact))

        result = await modal_llm_app.validate_models.local(list(self.DIRECTORIES), False)

        # Every directory still reported. Before the fix this raised.
        for directory in self.DIRECTORIES:
            assert "error" not in result["by_directory"][directory], result
        assert result["total_valid"] == 3, result
        # And the artifact that could not be stat'd is reported as a fact we
        # could not determine, not as a size.
        assert result["total_indeterminate"] == 1, result
        assert result["total_partial"] == 0, (
            "an unstat'able artifact is not a known-size partial"
        )

    @pytest.mark.asyncio
    async def test_an_unreadable_directory_does_not_abort_the_sweep(
        self, modal_llm_app, tmp_path, monkeypatch
    ):
        broken_directory = self.DIRECTORIES[0]
        for directory in self.DIRECTORIES:
            (tmp_path / directory).mkdir(parents=True)
            _good(tmp_path / directory, "good.ckpt")

        monkeypatch.setattr(os, "listdir", _make_listdir_fail("checkpoints"))

        result = await modal_llm_app.validate_models.local(list(self.DIRECTORIES), False)

        # The directory that could not be opened says so, against itself.
        failed = result["by_directory"][broken_directory]
        assert "error" in failed, failed
        assert "Input/output error" in failed["error"], failed

        # ...and the two that could be read are still counted, which is the whole
        # point: before the fix the raise discarded them too.
        assert result["total_valid"] == 2, result
        for directory in self.DIRECTORIES[1:]:
            assert len(result["by_directory"][directory]["valid"]) == 1, directory

    @pytest.mark.asyncio
    async def test_an_unreadable_directory_is_not_counted_as_indeterminate(
        self, modal_llm_app, tmp_path, monkeypatch
    ):
        """"A file was seen and could not be judged" is a different statement from
        "this directory was never opened", and reconciliation reads the second as
        a file it may act on."""
        for directory in self.DIRECTORIES:
            (tmp_path / directory).mkdir(parents=True)
            _good(tmp_path / directory, "good.ckpt")

        monkeypatch.setattr(os, "listdir", _make_listdir_fail("checkpoints"))

        result = await modal_llm_app.validate_models.local(list(self.DIRECTORIES), False)

        assert result["total_indeterminate"] == 0, result
        assert result["total_valid"] == 2
        assert result["total_invalid"] == 0

    @pytest.mark.asyncio
    async def test_a_sweepable_directory_still_reports_no_error_key(
        self, modal_llm_app, tmp_path
    ):
        """The control: a healthy directory carries the four buckets and no error."""
        directory = tmp_path / "models" / "checkpoints"
        directory.mkdir(parents=True)
        _good(directory, "good.ckpt")

        result = await modal_llm_app.validate_models.local(["models/checkpoints"], False)

        assert "error" not in result["by_directory"]["models/checkpoints"], result
        assert result["total_valid"] == 1, result