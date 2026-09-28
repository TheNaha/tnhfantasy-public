"""Finding 7: three of the four server-side download paths had no socket timeout.

`provider_core/downloads.py:427-431` only sets `timeout` when
`request_timeout_seconds is not None`, and the parameter defaults to None. So
`requests.get` was called with no timeout at all on:

  * image_worker/engines/modal/modal_app.py  — `download_model`
  * llm_worker/engines/modal/modal_app.py    — `download_model`
  * image_worker/engines/beam/beam_app.py    — `shared_download_model`

Only the remote agent passed one (`remote_agent/server.py:181`, DOWNLOAD_TIMEOUT).

`requests` with no timeout blocks forever on a peer that accepts the connection
and then stops sending. On the Beam storage deployment that is worse than a stuck
download: the same container also serves `/list-models` and
`/validate-all-models`, so one wedged transfer takes the provider's whole read API
with it. `MODAL_DOWNLOAD_TIMEOUT` / `BEAM_DOWNLOAD_TIMEOUT` were already read and
already passed as the Modal/Beam *function* timeout — never as the HTTP timeout.
"""

from __future__ import annotations

import pathlib

import pytest

# (module, the env knob that must exist, the call site that must pass it)
DOWNLOAD_PATHS = [
    (
        "image_worker.engines.modal.modal_app",
        "MODAL_DOWNLOAD_HTTP_TIMEOUT",
        "request_timeout_seconds=DOWNLOAD_HTTP_TIMEOUT",
    ),
    (
        "llm_worker.engines.modal.modal_app",
        "MODAL_DOWNLOAD_TIMEOUT",
        "request_timeout_seconds=DOWNLOAD_TIMEOUT",
    ),
    (
        "image_worker.engines.beam.beam_app",
        "BEAM_DOWNLOAD_HTTP_TIMEOUT",
        "request_timeout_seconds=DOWNLOAD_HTTP_TIMEOUT",
    ),
    (
        "remote_agent.server",
        "DOWNLOAD_TIMEOUT",
        "request_timeout_seconds=DOWNLOAD_TIMEOUT",
    ),
]


def _source(dotted: str) -> str:
    import importlib.util

    spec = importlib.util.find_spec(dotted)
    assert spec is not None and spec.origin, f"cannot locate {dotted}"
    return pathlib.Path(spec.origin).read_text()


class TestEveryServerSideDownloadPathHasATimeout:
    @pytest.mark.parametrize("dotted,knob,call", DOWNLOAD_PATHS)
    def test_the_download_call_passes_a_timeout(self, dotted, knob, call):
        source = _source(dotted)
        assert call in source, (
            f"{dotted} calls download_model_to_path without a request_timeout_seconds; "
            "requests.get with no timeout blocks forever on a peer that accepts the "
            "connection and stops sending"
        )

    @pytest.mark.parametrize("dotted,knob,call", DOWNLOAD_PATHS)
    def test_the_timeout_comes_from_a_documented_env_knob(self, dotted, knob, call):
        source = _source(dotted)
        assert knob in source, (
            f"{dotted} has no {knob}; the timeout must be configurable, not a "
            "hardcoded literal"
        )

    def test_the_two_modal_apps_agree_on_the_knob_name(self):
        """The image twin has MODAL_DOWNLOAD_HTTP_TIMEOUT (its own knob); the vLLM
        twin reuses MODAL_DOWNLOAD_TIMEOUT. Both are valid — what is not valid is
        the vLLM twin having NO timeout while its image twin does."""
        image = _source("image_worker.engines.modal.modal_app")
        llm = _source("llm_worker.engines.modal.modal_app")
        assert "request_timeout_seconds=" in image
        assert "request_timeout_seconds=" in llm


class TestTheDefaultIsSafe:
    """The old strategy was "keep the parameter optional, and make every caller
    pass a value". It worked only for the four callers that existed. The
    parameter's default was `None`, which meant the `timeout` kwarg was omitted
    from `requests.get` entirely — and `requests` blocks forever on a peer that
    accepts the connection and then goes quiet.

    That is the wrong default for a function whose entire job is multi-GB
    transfers, running inside a billed Modal/Beam container. The mitigation was
    a convention every future caller had to remember; the fix is a default that
    cannot hang. Passing `None` explicitly still opts out, so an embedder that
    genuinely wants no timeout still can."""

    def test_the_default_is_a_real_timeout(self):
        import inspect as _inspect

        from provider_core.downloads import _download_model_to_path_unlocked

        default = _inspect.signature(
            _download_model_to_path_unlocked
        ).parameters["request_timeout_seconds"].default

        assert default is not None, (
            "a None default omits the timeout kwarg and lets a stuck peer hold "
            "a billed download container forever"
        )
        assert isinstance(default, (int, float)) and default > 0

    def test_the_helper_passes_the_timeout_to_requests_get(self, monkeypatch):
        """End to end: a non-None value really does reach `requests.get`."""
        import provider_core.downloads as downloads

        seen = {}
        _BODY = b'PK' + b'\x00' * 20000  # over MIN_MODEL_SIZE (10 KiB), valid zip/ckpt header
        class _Response:
            status_code = 200
            headers = {"content-length": str(len(_BODY)), "etag": "abc"}

            def iter_content(self, chunk_size=8192):
                return iter([_BODY])

            def close(self):
                pass

        def _fake_get(url, **kwargs):
            seen.update(kwargs)
            return _Response()

        monkeypatch.setattr(downloads.requests, "get", _fake_get)

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = downloads.download_model_to_path(
                url="https://example.invalid/model.ckpt",
                full_path=f"{tmp}/model.ckpt",
                request_timeout_seconds=12.5,
            )

        assert result["status"] == "success"
        assert seen["timeout"] == 12.5

    def test_the_default_reaches_requests_get_without_the_caller_asking(self, monkeypatch):
        """The whole point of the change: a caller that says nothing still gets
        a bounded read, so the next call site added to this module is safe
        without anyone having to remember."""
        import provider_core.downloads as downloads

        seen = {}
        _BODY = b'PK' + b'\x00' * 20000  # over MIN_MODEL_SIZE (10 KiB), valid zip/ckpt header
        class _Response:
            status_code = 200
            headers = {"content-length": str(len(_BODY))}

            def iter_content(self, chunk_size=8192):
                return iter([_BODY])

            def close(self):
                pass

        monkeypatch.setattr(
            downloads.requests, "get", lambda url, **kw: (seen.update(kw), _Response())[1]
        )

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            downloads.download_model_to_path(
                url="https://example.invalid/model.ckpt",
                full_path=f"{tmp}/model.ckpt",
            )

        assert seen.get("timeout"), "the default never reached requests.get"

    def test_no_timeout_key_when_the_caller_passes_none(self, monkeypatch):
        """Documents the conditional at downloads.py:427-429: with an explicit
        None the kwarg is absent entirely, not set to None. `requests` treats an
        explicit `timeout=None` the same as omitting it, so both mean "block
        forever" — which is why None is now opt-in rather than the default."""
        import provider_core.downloads as downloads

        seen = {}
        _BODY = b'PK' + b'\x00' * 20000  # over MIN_MODEL_SIZE (10 KiB), valid zip/ckpt header
        class _Response:
            status_code = 200
            headers = {"content-length": str(len(_BODY))}

            def iter_content(self, chunk_size=8192):
                return iter([_BODY])

            def close(self):
                pass

        monkeypatch.setattr(
            downloads.requests, "get", lambda url, **kw: (seen.update(kw), _Response())[1]
        )

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            downloads.download_model_to_path(
                url="https://example.invalid/model.ckpt",
                full_path=f"{tmp}/model.ckpt",
                request_timeout_seconds=None,
            )

        assert "timeout" not in seen


class TestTheAgentSetupSeedsAreBounded:
    """Finding 12: `/setup` gathered 8 `asyncio.to_thread` downloads with no
    semaphore and no timeout.

    `asyncio.to_thread` uses the default executor, whose worker count is bounded,
    so 8 stalled peers pinned every thread in the single-process agent and every
    later `to_thread` — `/validate-models`, `/get-file` — queued behind them.
    """

    def test_the_setup_path_passes_a_timeout(self):
        source = _source("remote_agent.server")
        # Two call sites: the seed helper and /download-model.
        assert source.count("request_timeout_seconds=DOWNLOAD_TIMEOUT") == 2

    def test_setup_bounds_its_concurrency(self):
        source = _source("remote_agent.server")
        assert "SEED_MAX_CONCURRENT" in source
        assert "asyncio.Semaphore" in source, (
            "/setup must bound its seeds, or a rig where the model hosts are slow "
            "occupies every executor thread the agent has"
        )

    def test_the_semaphore_wraps_the_await_not_the_thread_body(self):
        """An `asyncio.Semaphore` is not a sync context manager, and holding it
        inside the `to_thread` body would not bound anything — the coroutine would
        already have handed the work to the executor."""
        source = _source("remote_agent.server")
        assert "async with seed_semaphore:" in source
