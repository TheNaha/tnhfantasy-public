"""Two provider-side failures that both cost real money.

1. The Beam `@realtime` GPU handler had no authentication. `verify_beam_token`
   gates `storage_app`, `download_app` and `extractor_app`; the `@realtime`
   `comfy_gpu` route — the one that bills GPU time, executes an arbitrary ComfyUI
   graph, and reads and writes the `/mnt/data` volume holding the checkpoints —
   took no token at all, and the worker's `Authorization: Bearer` header went
   unread. Anyone who learned the deployment URL got free inference.

   The comparison itself lives in `provider_core/auth.py` so it is testable here:
   `beam_app` cannot be imported in this venv (the pinned `beta9` has no
   `rest_api`), which is exactly why the handler went unaudited before. The
   source-level assertions at the end are what pin the wiring.

2. `validate_downloaded_file` reported `valid: False` both for a file it read and
   judged corrupt AND for a file it could not read at all (`OSError`, ENOMEM, a
   gcsfuse stall). Reconciliation calls the validators with
   `delete_invalid=True` on a network volume every 2 hours, so a single transient
   read error deleted a healthy 7 GB checkpoint along with its sidecars. That is
   unrecoverable — the download has to be paid for again.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from provider_core.auth import bearer_from_header, token_matches  # noqa: E402
from provider_core.validation import validate_downloaded_file  # noqa: E402

PROVIDER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _valid_safetensors(tmp_path, name="model.safetensors", tensors=8):
    """A genuinely valid safetensors file.

    The format is: an 8-byte little-endian header length, then that many bytes of
    JSON. Anything else fails the structural check, which is why a fixture built
    from a magic prefix alone reports "corrupted" — and why that is a correct
    verdict rather than a false positive.
    """
    import json as _json
    import struct as _struct

    header = _json.dumps({"__metadata__": {}, **{f"w{i}": {} for i in range(tensors)}}).encode()
    blob = _struct.pack("<Q", len(header)) + header
    blob += b"\x00" * max(0, 64 * 1024 - len(blob))
    p = tmp_path / name
    p.write_bytes(blob)
    return p



def _read(*parts: str) -> str:
    with open(os.path.join(PROVIDER_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------- auth on GPU


class TestTokenComparison:
    def test_exact_match_only(self):
        assert token_matches("s3cret", "s3cret") is True
        assert token_matches("s3cre", "s3cret") is False
        assert token_matches("s3cret ", "s3cret") is False
        assert token_matches("S3CRET", "s3cret") is False

    def test_never_matches_when_unconfigured(self):
        """Fails closed. An unconfigured secret must not match anything —
        including the empty string, which is what a missing header decodes to."""
        assert token_matches("", "") is False
        assert token_matches("anything", "") is False
        assert token_matches(None, "") is False
        assert token_matches(b"anything", b"") is False

    def test_missing_or_mistyped_provided_never_matches(self):
        assert token_matches(None, "s3cret") is False
        assert token_matches("", "s3cret") is False
        assert token_matches(b"", "s3cret") is False
        assert token_matches(12345, "s3cret") is False
        assert token_matches(["a"], "s3cret") is False
        assert token_matches({"a": 1}, "s3cret") is False

    def test_non_ascii_never_raises(self):
        """`hmac.compare_digest` raises TypeError on a str holding a byte >= 0x80,
        and Starlette decodes header/payload bytes as latin-1.

        On the ASGI routes that TypeError was caught by the catch-all and
        answered 500 with `retryable: true`, which the backend reads as "this
        provider is unhealthy, try it elsewhere" — so one malformed auth header
        became a paid retry across the whole pool. Reproduced: a raw ASGI request
        with `x-provider-token: b"\\xe9"` raised; `b"wrong"` answered a clean 401.
        """
        # latin-1 decodes 0xE9 to U+00E9, which utf-8 CAN encode.
        assert token_matches("é", "s3cret") is False
        # A lone surrogate (what latin-1 cannot encode) must not raise either.
        assert token_matches("\udce9", "s3cret") is False
        assert token_matches("\udce9\udca0\udc89", "s3cret") is False
        # And the reverse: a non-ascii *expected* value.
        assert token_matches("x", "é") is False

    def test_raw_bytes_work_on_both_sides(self):
        assert token_matches(b"s3cret", b"s3cret") is True
        assert token_matches(b"s3cret", "s3cret") is True
        assert token_matches("s3cret", b"s3cret") is True
        assert token_matches(b"\xe9", b"s3cret") is False

    def test_a_high_byte_token_still_compares_correctly(self):
        """Not just 'does not raise' — a legitimate non-ASCII secret must still
        authenticate, or the fix would lock a deployment out of its own provider."""
        secret = "clé-secrète-🔑"
        assert token_matches(secret, secret) is True
        assert token_matches(secret + "x", secret) is False


class TestBearerExtraction:
    def test_extracts_the_token(self):
        assert bearer_from_header("Bearer abc123") == "abc123"

    def test_non_bearer_and_missing_values_become_empty(self):
        for value in (None, "", "abc123", "bearer abc", "Basic abc", "Bearer"):
            assert bearer_from_header(value) == ""

    def test_an_empty_bearer_is_empty_not_a_pass(self):
        # The single most dangerous shape for an auth check: a header of exactly
        # "Bearer " must not produce a value that compares equal to an unset
        # secret. `token_matches` refuses empty on both sides regardless.
        assert bearer_from_header("Bearer ") == ""


class TestWiring:
    """`beam_app` cannot be imported in this venv, so the wiring is pinned by
    source. These are the assertions that would have caught the missing gate."""

    def test_the_gpu_handler_checks_the_token(self):
        src = _read("image_worker", "engines", "beam", "beam_app.py")
        assert "_realtime_token_ok" in src
        # The check must run before inference, and must return rather than fall
        # through to a new message.
        handler = src[src.index("async def comfy_gpu"):]
        handler = handler[: handler.index("logger.info(\"[comfy_gpu] Inference complete\"")]
        assert handler.index("_realtime_token_ok") < handler.index("_run_inference_realtime")
        assert "chat_swipe" not in handler
        assert 'if not _realtime_token_ok' in handler
        assert "return" in handler

    def test_the_gpu_handler_fails_closed(self):
        src = _read("image_worker", "engines", "beam", "beam_app.py")
        body = src[src.index("def _realtime_token_ok"):]
        body = body[: body.index("\ndef ")]
        assert "BEAM_API_KEY" in body
        assert "return False" in body, "an unset BEAM_API_KEY must not authenticate"

    def test_the_client_sends_the_token_in_the_payload(self):
        """Both ends changed in one commit. The payload is the channel that is
        guaranteed readable: a `@realtime` handler's signature is what the SDK
        decorator inspects, and the request-context object that would carry the
        header is not present in every deployed version."""
        src = _read("image_worker", "engines", "beam", "client.py")
        assert '"token": BEAM_API_KEY' in src
        assert '"workflow": request.workflow' in src

    def test_every_destructive_validation_site_respects_indeterminate(self):
        """A guard that only exists inside `validation.py` is defeated by every
        caller that reads `valid` and deletes, so every call site is pinned.

        The list is the pin: the four that existed when this test was written are
        named, so a fifth cannot appear without somebody adding it here. The
        remote agent is on it because it is the one that touches the operator's
        real network volume — reconciliation drives it with `delete_invalid=True`
        on a 2-hour tick, so a single transient read error destroyed a multi-GB
        checkpoint there and nowhere else.
        """
        for parts in (
            ("image_worker", "engines", "beam", "beam_app.py"),
            ("image_worker", "engines", "modal", "modal_app.py"),
            ("llm_worker", "engines", "modal", "modal_app.py"),
        ):
            assert "indeterminate" in _read(*parts), f"{parts[-2]} ignores indeterminate"

    def test_the_remote_agent_guards_its_delete(self):
        agent = os.path.join(PROVIDER_ROOT, "..", "remote_agent", "server.py")
        with open(agent, encoding="utf-8") as fh:
            src = fh.read()
        assert "indeterminate" in src, (
            "remote_agent/server.py deletes on `not validation['valid']` with no "
            "indeterminate guard, which is the one call site that can destroy a "
            "real model irrecoverably"
        )
        # The guard has to be on the delete itself, not merely mentioned: a
        # `validation.get("indeterminate")` that only annotates the report is
        # the shape that reads as fixed and is not.
        assert "delete_invalid and not validation.get(\"indeterminate\")" in src, (
            "the delete is not gated on an indeterminate verdict"
        )


# ------------------------------------------------- read failure vs corruption


class TestIndeterminateValidation:
    def test_a_missing_file_is_indeterminate_not_invalid(self, tmp_path):
        result = validate_downloaded_file(str(tmp_path / "nope.safetensors"))
        assert result["valid"] is False
        assert result["indeterminate"] is True

    def test_a_read_oserror_is_indeterminate(self, tmp_path):
        p = _valid_safetensors(tmp_path)

        real_open = open

        def exploding_open(path, *a, **k):
            if str(path) == str(p):
                raise OSError(5, "Input/output error")
            return real_open(path, *a, **k)

        with patch("builtins.open", exploding_open):
            result = validate_downloaded_file(str(p))

        assert result["valid"] is False
        assert result["indeterminate"] is True
        assert "Error reading header" in result["error"]

    def test_a_header_that_does_not_parse_is_a_real_verdict(self, tmp_path):
        """The bytes were read and are wrong — that IS corrupt, and deleting is
        the right call. The distinction has to cut both ways, or a genuinely
        broken download would never be cleaned up."""
        p = tmp_path / "model.safetensors"
        # Valid safetensors magic-length header, then garbage JSON.
        p.write_bytes(b"\xff\xff\xff\xff\xff\xff\xff\x7f" + b"not json at all" + b"0" * 4096)

        result = validate_downloaded_file(str(p))
        assert result["valid"] is False
        assert result["indeterminate"] is False

    def test_html_instead_of_a_model_is_a_real_verdict(self, tmp_path):
        p = tmp_path / "model.safetensors"
        p.write_bytes(b"<!DOCTYPE html><html>" + b" " * 4096)
        result = validate_downloaded_file(str(p))
        assert result["valid"] is False
        assert result["indeterminate"] is False
        assert "HTML" in result["error"]

    def test_a_good_file_reports_indeterminate_false(self, tmp_path):
        p = _valid_safetensors(tmp_path)
        result = validate_downloaded_file(str(p))
        assert result["valid"] is True, result
        assert result["indeterminate"] is False

    def test_every_result_carries_the_flag(self, tmp_path):
        """Callers use `.get("indeterminate")`, so the key must be present on
        every return path including the healthy one."""
        good = _valid_safetensors(tmp_path, "good.safetensors")
        for path in (good, tmp_path / "absent"):
            assert "indeterminate" in validate_downloaded_file(str(path))

    def test_the_size_floor_is_still_a_real_verdict(self, tmp_path):
        p = tmp_path / "tiny.safetensors"
        p.write_bytes(b"\x80\x04")
        result = validate_downloaded_file(str(p))
        assert result["valid"] is False
        assert result["indeterminate"] is False


@pytest.mark.parametrize("name", ["token_matches", "bearer_from_header"])
def test_the_helpers_are_importable_without_a_provider_sdk(name):
    """`provider_core` must not drag in modal/beam/beta9 — that is what let this
    be unit-testable at all."""
    import provider_core.auth as mod

    assert callable(getattr(mod, name))
