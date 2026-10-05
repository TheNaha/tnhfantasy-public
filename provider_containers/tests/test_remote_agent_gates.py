"""`remote_agent/server.py` is a 397-line HTTP surface with two security gates in
it, and until now the only CI verification of any kind was the PyInstaller job
curl-ing `/health` — "did it boot". A change that inverted the path-traversal
gate, or made `verify_token` a no-op, or dropped the auth dependency from one
route, was green.

All three are trivially testable without a socket: they are pure functions of
their arguments and the filesystem. `remote_agent` is importable here because
`tests/conftest.py` puts the repo root on `sys.path` and supplies the import-time
token.

These are the gates, so they are the ones that matter:

* `_data_path` — every route resolves its input through it, so it is the
  traversal gate for the whole surface.
* `verify_token` — with a token set, a missing/wrong/truncated credential must be
  refused; with `REMOTE_AGENT_ALLOW_INSECURE` it is open, which is why
  `server.py` clamps the bind to loopback in that mode.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import remote_agent.server as server

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(server.__file__)))


class TestDataPathIsConfinedToDataDir:
    """Every route resolves its path argument through `_data_path`, so this is the
    traversal gate for all of them."""

    def test_a_plain_relative_path_resolves(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        assert server._data_path("models/checkpoints/x.safetensors") == str(
            tmp_path / "models" / "checkpoints" / "x.safetensors"
        )

    @pytest.mark.parametrize(
        "attempt",
        [
            "../../../etc/passwd",
            "models/../../etc/passwd",
            "models/checkpoints/../../../../etc/passwd",
            "./../../etc/passwd",
            "models/./../../etc/passwd",
            "",
            "..",
        ],
    )
    def test_anything_that_escapes_is_refused(self, attempt, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        with pytest.raises(HTTPException) as exc:
            server._data_path(attempt)
        assert exc.value.status_code == 403

    def test_an_absolute_path_is_contained_not_honoured(self, tmp_path, monkeypatch):
        """`os.path.join(base, "/etc/passwd")` is "/etc/passwd" — the join alone
        would be the bug. `get_safe_path` strips the leading separator, so the
        result is `<DATA_DIR>/etc/passwd`. Pinned because a future "fix" that used
        `Path(base) / path` would turn this into a real traversal."""
        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        resolved = server._data_path("/etc/passwd")
        assert resolved == str(tmp_path / "etc" / "passwd")
        assert str(tmp_path) in resolved

    def test_a_traversal_that_normalises_back_inside_is_allowed(self, tmp_path, monkeypatch):
        """`models/../models/x` ends up inside DATA_DIR, so refusing it would be
        the same false positive that makes people switch a gate off."""
        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        assert server._data_path("models/../models/x.safetensors") == str(
            tmp_path / "models" / "x.safetensors"
        )

    def test_a_prefix_sibling_is_not_inside(self, tmp_path, monkeypatch):
        """`<base>/data-secret` starts with the string `<base>/data`, so a
        `startswith` check is not enough; this is the case that separates them."""
        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path / "data"))
        with pytest.raises(HTTPException):
            server._data_path("../data-secret/keys")


class TestValidateDir:
    def test_a_clean_model_is_reported_valid(self, tmp_path):
        models = tmp_path / "models" / "checkpoints"
        models.mkdir(parents=True)
        # A zip body over MIN_MODEL_SIZE, which is what `validate_downloaded_file`
        # accepts for an otherwise-unrecognised header.
        (models / "good.ckpt").write_bytes(b"PK" + b"\x00" * 20000)

        result = server._validate_dir(str(models), False)

        assert result["total_valid"] == 1
        assert [entry["name"] for entry in result["valid"]] == ["good.ckpt"]
        assert result["total_invalid"] == 0

    def test_a_truncated_model_is_reported_invalid(self, tmp_path):
        models = tmp_path / "models" / "checkpoints"
        models.mkdir(parents=True)
        (models / "small.ckpt").write_bytes(b"PK" + b"\x00" * 64)

        result = server._validate_dir(str(models), False)

        assert result["total_invalid"] == 1
        assert result["total_valid"] == 0

    def test_a_sidecar_is_not_a_model(self, tmp_path):
        models = tmp_path / "models" / "checkpoints"
        models.mkdir(parents=True)
        (models / "good.ckpt").write_bytes(b"PK" + b"\x00" * 20000)
        (models / "good.ckpt.json").write_bytes(b'{"name": "good"}')
        (models / "good.ckpt.preview.png").write_bytes(b"\x89PNG")

        result = server._validate_dir(str(models), False)

        assert result["total_valid"] == 1
        assert [entry["name"] for entry in result["valid"]] == ["good.ckpt"]

    def test_a_partial_download_is_reported_and_never_deleted(self, tmp_path):
        """`delete_invalid=True` is what reconciliation calls this with.

        Removing an in-flight temp leaves its writer holding a live descriptor: it
        finishes the transfer and then fails at `os.replace`, which reconciliation
        reports as a failed download. Removing the `.lock` additionally unlinks a
        held flock and takes the model's own `.json` with it, because
        `splitext("x.safetensors.lock")[0] == "x.safetensors"`.
        `provider_core/utils.py` (TRANSIENT_SUFFIXES) records this having
        happened. Abandoned partials are reclaimed by the delete route, via
        `pending_download_paths` — the only place that can tell an in-flight
        attempt from a dead one.
        """
        from provider_core.utils import DOWNLOADING_SUFFIX, LOCK_SUFFIX

        models = tmp_path / "models" / "checkpoints"
        models.mkdir(parents=True)
        (models / "good.ckpt").write_bytes(b"PK" + b"\x00" * 20000)
        (models / "good.ckpt.json").write_bytes(b'{"name": "good"}')
        temp = models / f"good.ckpt.4242.abcdef01{DOWNLOADING_SUFFIX}"
        temp.write_bytes(b"7GB of partial")
        lock = models / f"good.ckpt{LOCK_SUFFIX}"
        lock.write_bytes(b"")

        result = server._validate_dir(str(models), True)

        assert result["total_partial"] == 2, (
            "the agent's total_partial must see the pipeline's temp and lock files"
        )
        assert temp.exists(), "an in-flight download was unlinked mid-transfer"
        assert lock.exists(), "a held flock was unlinked"
        assert (models / "good.ckpt.json").exists(), (
            "the metadata sidecar went with its lock — that is the incident this "
            "gate exists for"
        )
        assert result["total_valid"] == 1


class TestAnUnreadableModelIsNeverDeleted:
    """`validate_downloaded_file` has three outcomes, and the destructive one
    must only ever act on a verdict.

    A `read()` that raised (EIO, ENOMEM, a gcsfuse stall) is `valid: False,
    indeterminate: True` — "we could not find out", not "it is bad". Three other
    call sites honour the third state; this one did not, and it is the one that
    touches the operator's real network volume, driven by reconciliation on a
    2-hour tick with `delete_invalid=True`. One transient read error destroyed a
    multi-GB checkpoint, unrecoverably and unattended.
    """

    @staticmethod
    def _checkpoint(tmp_path, name="big.safetensors"):
        import json as _json
        import struct as _struct

        header = _json.dumps({"__metadata__": {}, **{f"w{i}": {} for i in range(8)}}).encode()
        path = tmp_path / name
        path.write_bytes(_struct.pack("<Q", len(header)) + header + b"\x00" * 65536)
        (tmp_path / f"{name}.json").write_text('{"name": "big"}')
        return path

    def test_a_read_oserror_leaves_the_model_its_sidecar_and_the_directory_alone(
        self, tmp_path, monkeypatch
    ):
        target = self._checkpoint(tmp_path)
        real_open = open

        def exploding_open(path, *a, **k):
            if str(path) == str(target):
                raise OSError(5, "Input/output error")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", exploding_open)

        result = server._validate_dir(str(tmp_path), True)

        assert target.exists(), "an unreadable model was deleted on a guess"
        assert (tmp_path / "big.safetensors.json").exists(), "its metadata went with it"
        # Its own bucket, not `invalid`. It used to be appended to `invalid` with
        # an extra `indeterminate: True` key, so this engine's `total_invalid`
        # counted files that were merely unreadable while the Modal and LLM
        # validators — which have excluded them since 2026-09-29 — did not. The
        # same sweep answered differently depending on which engine ran it.
        assert result["total_invalid"] == 0, "an unreadable file is not an invalid one"
        assert result["total_indeterminate"] == 1, "it must still be reported"
        assert result["indeterminate"][0]["indeterminate"] is True, (
            "reported as unreadable without saying the read is what failed, so an "
            "operator cannot tell this apart from real corruption"
        )

    def test_a_genuinely_corrupt_model_is_still_deleted(self, tmp_path):
        """The distinction has to cut both ways, or a real 12-byte HTML error
        page would sit in the model tree forever and reconciliation could never
        reach zero."""
        (tmp_path / "truncated.ckpt").write_bytes(b"PK" + b"\x00" * 64)

        server._validate_dir(str(tmp_path), True)

        assert not (tmp_path / "truncated.ckpt").exists()

    def test_an_indeterminate_result_is_kept_even_with_delete_invalid_false(self, tmp_path):
        """Both flags off: reporting must not change. Guards against a 'fix' that
        only skips the delete when reconciliation is not in destructive mode."""
        target = self._checkpoint(tmp_path)
        real_open = open

        def exploding_open(path, *a, **k):
            if str(path) == str(target):
                raise OSError(5, "Input/output error")
            return real_open(path, *a, **k)

        with patch("builtins.open", exploding_open):
            result = server._validate_dir(str(tmp_path), False)

        assert result["total_indeterminate"] == 1
        assert result["total_invalid"] == 0
        assert target.exists()


class TestVerifyToken:
    @staticmethod
    def _request(authorization=None):
        request = MagicMock()
        request.headers = {"Authorization": authorization} if authorization else {}
        return request

    @pytest.mark.asyncio
    async def test_a_correct_token_is_accepted(self, monkeypatch):
        monkeypatch.setattr(server, "TOKEN", "s3cret-token")
        assert await server.verify_token(self._request("Bearer s3cret-token")) is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "presented",
        [None, "", "wrong", "Bearer wrong", "s3cret-token", "Bearer s3cret-toke", "Bearer s3cret-tokenX"],
    )
    async def test_a_wrong_or_truncated_token_is_refused(self, presented, monkeypatch):
        """A prefix must not pass, and the scheme must be `Bearer`. The comparison
        is hmac.compare_digest, which is constant-time precisely so the shared
        prefix cannot be probed byte by byte."""
        monkeypatch.setattr(server, "TOKEN", "s3cret-token")
        with pytest.raises(HTTPException) as exc:
            await server.verify_token(self._request(presented))
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_configured_is_open(self, monkeypatch):
        """`TOKEN` is empty only when REMOTE_AGENT_ALLOW_INSECURE was set at import
        (server.py raises otherwise) — the mode `_resolve_bind_host` clamps."""
        monkeypatch.setattr(server, "TOKEN", "")
        assert await server.verify_token(self._request()) is True
        assert await server.verify_token(self._request("Bearer anything")) is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "presented",
        ["Bearer \xe9", "Bearer \udce9", "Bearer ключ", "Bearer 🔑"],
    )
    async def test_a_non_ascii_bearer_is_a_401_and_not_a_500(self, presented, monkeypatch):
        """`hmac.compare_digest` raises `TypeError` on a `str` holding a byte
        >= 0x80, and Starlette decodes header bytes as latin-1 — so a single
        non-ASCII character made this dependency raise.

        Inside a FastAPI dependency an uncaught TypeError is an unmapped 500,
        and `provider_core/http_client.py` retries the call three times before
        giving up: one malformed header cost four round trips and reported a
        server fault for what is plainly a wrong credential.

        `provider_core/auth.py` documents the bug and exists to make it
        impossible; this file was the sixth hand-written copy and sat outside
        `provider_core`, so the unification never reached it.
        """
        monkeypatch.setattr(server, "TOKEN", "s3cret-token")
        with pytest.raises(HTTPException) as exc:
            await server.verify_token(self._request(presented))
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_a_non_ascii_token_still_authenticates(self, monkeypatch):
        """Not merely 'does not raise'. Encoding to bytes before comparing must
        still accept a legitimate non-ASCII secret, or the fix would lock a
        deployment out of its own agent."""
        secret = "clé-secrète-🔑"
        monkeypatch.setattr(server, "TOKEN", secret)
        assert await server.verify_token(self._request(f"Bearer {secret}")) is True
        with pytest.raises(HTTPException):
            await server.verify_token(self._request(f"Bearer {secret}x"))


class TestTheInsecureFlagCannotExposeTheRig:
    """The flag is for local dev. It must not silently turn a read-write mount into
    an unauthenticated network service."""

    def test_the_default_bind_is_clamped_to_loopback_under_the_insecure_flag(self, monkeypatch):
        monkeypatch.setattr(server, "ALLOW_INSECURE", True)
        monkeypatch.setenv("HOST", "0.0.0.0")
        assert server._resolve_bind_host() == "127.0.0.1"

    def test_an_explicit_wildcard_bind_is_also_clamped(self, monkeypatch):
        """`agentctl.sh` used to export HOST=0.0.0.0 by default, so "the operator
        asked for this" was not a signal anything could rely on. It now exports
        HOST only when it is actually set, and the clamp does not care."""
        monkeypatch.setattr(server, "ALLOW_INSECURE", True)
        monkeypatch.setenv("HOST", "0.0.0.0")
        assert server._resolve_bind_host() == "127.0.0.1"

    @pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
    def test_a_loopback_host_is_left_alone(self, host, monkeypatch):
        monkeypatch.setattr(server, "ALLOW_INSECURE", True)
        monkeypatch.setenv("HOST", host)
        assert server._resolve_bind_host() == host

    @pytest.mark.parametrize("empty", ["", " ", "\t", "\n"])
    def test_an_empty_host_is_a_wildcard_not_a_loopback(self, empty, monkeypatch):
        """The hole in the clamp, and the reason the launch script was the problem.

        `agentctl.sh` did `export HOST="${HOST-}"`, which exports `HOST=""`
        whenever the operator set none. So `os.getenv("HOST", "0.0.0.0")` never
        fell back to its default — the variable *was* set — and `""` was passed
        to uvicorn, which binds an empty host as `INADDR_ANY`. `""` was also a
        member of `_LOOPBACK_HOSTS`, so the clamp returned it unchanged.

        Net effect of the flag the clamp exists to constrain:
        `REMOTE_AGENT_ALLOW_INSECURE=1` with no `HOST` bound an
        unauthenticated writer — `/delete-model`, `/delete-file`,
        `/upload-file`, `/download-model` — to `0.0.0.0:8001`.

        An empty string is not a loopback address. It is a wildcard, and it is
        now resolved to the default and clamped like any other wildcard.
        """
        monkeypatch.setattr(server, "ALLOW_INSECURE", True)
        monkeypatch.setenv("HOST", empty)
        resolved = server._resolve_bind_host()
        assert resolved == "127.0.0.1", (
            f"HOST={empty!r} resolved to {resolved!r}; an empty bind address is "
            "INADDR_ANY, not loopback, so the insecure flag exposed the agent's "
            "write routes on every interface"
        )

    def test_an_unset_host_is_also_clamped(self, monkeypatch):
        """The ordinary path: no HOST at all, flag on. Must be loopback."""
        monkeypatch.setattr(server, "ALLOW_INSECURE", True)
        monkeypatch.delenv("HOST", raising=False)
        assert server._resolve_bind_host() == "127.0.0.1"

    def test_the_empty_string_is_not_in_the_loopback_set(self):
        """Stated directly so re-adding it is a deliberate act.

        Every other member is an address that only reaches this machine. `""` was
        never one; it was there because it made the clamp's own test pass.
        """
        assert "" not in server._LOOPBACK_HOSTS
        assert server._LOOPBACK_HOSTS == frozenset({"127.0.0.1", "::1", "localhost"})

    def test_the_launch_script_does_not_export_an_empty_host(self):
        """`agentctl.sh` is the other half of the fix, and it is a shell script.

        A Python test cannot see it, and the file it launches is the frozen
        binary — so this reads the script and asserts it never manufactures the
        empty value. Generated by content, not by line number, so editing the
        surrounding comments cannot make it vacuous.
        """
        script = (
            Path(__file__).resolve().parents[2] / "remote_agent" / "agentctl.sh"
        ).read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in script.splitlines()
            # `export HOST=` with no guard, or the `${HOST-}` form that expands
            # to empty when the variable is unset.
            if re.search(r"^\s*export\s+HOST=", line)
            and not re.search(r"if\s+\[", line)
        ]
        assert not offenders, (
            "agentctl.sh exports HOST unguarded again; an unset HOST becomes an "
            "empty string, which uvicorn binds as INADDR_ANY:\n  "
            + "\n  ".join(offenders)
        )
        assert 'if [ -n "${HOST-}" ]; then' in script, (
            "agentctl.sh should guard the HOST export on a non-empty value"
        )

    def test_a_token_protected_agent_keeps_its_bind(self, monkeypatch):
        """The clamp is about the *unauthenticated* case. With a token, a routable
        bind is the normal deployment and must not be silently rewritten."""
        monkeypatch.setattr(server, "ALLOW_INSECURE", False)
        monkeypatch.setenv("HOST", "0.0.0.0")
        assert server._resolve_bind_host() == "0.0.0.0"

    def test_the_warning_names_the_unauthenticated_routes(self, monkeypatch, capsys):
        """An operator who has just set the flag needs to know what is now open,
        not merely that a flag is set."""
        monkeypatch.setattr(server, "ALLOW_INSECURE", True)
        monkeypatch.setenv("HOST", "0.0.0.0")
        server._warn_insecure_bind()
        out = capsys.readouterr().out
        for route in ("/delete-model", "/delete-file", "/upload-file", "/download-model"):
            assert route in out, f"the warning must name {route}"
        assert "REMOTE_AGENT_TOKEN" in out, "the warning must say how to fix it"

    def test_no_warning_without_the_flag(self, monkeypatch, capsys):
        monkeypatch.setattr(server, "ALLOW_INSECURE", False)
        server._warn_insecure_bind()
        assert "UNAUTHENTICATED" not in capsys.readouterr().out


class TestTheWritableRoutesAreGated:
    """A missing `Depends(verify_token)` on one of these is the whole failure mode
    the insecure flag interacts with, so it is asserted as a shape rather than
    trusted."""

    WRITABLE = {"/delete-model", "/delete-file", "/upload-file", "/download-model"}

    def test_every_writable_route_depends_on_verify_token(self):
        with open(os.path.join(REPO_ROOT, "remote_agent", "server.py")) as handle:
            tree = ast.parse(handle.read())
        found = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                # `app.post("/delete-model", dependencies=[...])` — the route is
                # the decorator's own first argument; the attribute is the verb.
                call = decorator.func
                if not isinstance(call, ast.Attribute) or call.attr not in {"post", "delete"}:
                    continue
                if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                    continue
                route = decorator.args[0].value
                if route in self.WRITABLE:
                    found.add(route)
                    assert "verify_token" in ast.dump(node), (
                        f"{route} has no token dependency; it writes to DATA_DIR"
                    )
        assert found == self.WRITABLE, f"routes not found in source: {found}"
