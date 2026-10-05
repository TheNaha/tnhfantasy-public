"""HTTP Range resume for model downloads.

Every test here runs against a real `http.server` on a loopback socket, because
the thing under test is the conversation with the server: whether a `Range`
header is sent, and what the client does with 206 / 200 / 416. A mocked
transport cannot tell you whether the resumed file is byte-identical to an
uninterrupted one, which is the only assertion that matters.

The remote body is a real safetensors file so the pipeline's own
`validate_downloaded_file` runs against it unmodified.
"""

import fcntl
import json
import os
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional

import pytest

from provider_core import downloads
from provider_core.downloads import _parse_content_range, pending_download_paths
from provider_core.utils import is_model_file, is_transient_artifact


# The pipeline streams in 8 MB chunks, and urllib3 discards the chunk that was
# in flight when a connection breaks, so a drop has to be a multiple of the
# chunk size for the bytes before it to actually reach the file.
_CHUNK = 4096
_DROP = 5 * _CHUNK


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _model_bytes(payload_size: int = 40 * 1024, *, salt: int = 0) -> bytes:
    """A well-formed safetensors file, so real validation accepts it.

    `salt` changes the content without changing the length, which is the case a
    same-size re-upload has to be caught by.
    """
    header = json.dumps({"__metadata__": {"format": "pt"}}).encode("utf-8")
    header += b" " * ((-len(header)) % 8)
    payload = bytes((index + salt) & 0xFF for index in range(payload_size))
    return struct.pack("<Q", len(header)) + header + payload


class _Host:
    """Mutable state for the fake origin server."""

    def __init__(self, body: bytes, *, etag: str = '"rev-1"') -> None:
        self.body = body
        self.etag = etag
        self.honor_range = True
        self.honor_if_range = True
        self.suppress_content_range = False
        # A 206 that names a start but no total (`bytes 60202-*`) and no
        # Content-Length. Legal HTTP, and the case that made `total_size` 0 — so
        # every size comparison in the pipeline was skipped and a truncated body
        # published as a model.
        self.undeclared_total = False
        # A 200 with no Content-Length at all (a body delimited only by EOF).
        self.omit_content_length = False
        self.drop_after: Optional[int] = None
        self.drop_requests = 0
        self.status_override: Optional[int] = None
        self.served_bytes = 0
        self.requests: List[dict] = []


def _handler_for(host: _Host):
    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.0 keeps the connection lifetime obvious: the body ends when the
        # socket closes, so a short write is unambiguously a truncated body.
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):  # silence the stderr access log
            pass

        def do_GET(self):
            total = len(host.body)
            range_header = self.headers.get("Range")
            if_range = self.headers.get("If-Range")
            record = {"range": range_header, "if_range": if_range, "status": None}
            host.requests.append(record)

            start = 0
            partial = False

            if host.status_override is not None:
                record["status"] = host.status_override
                self.send_response(host.status_override)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            if range_header and host.honor_range:
                honoured = True
                if if_range:
                    honoured = host.honor_if_range and if_range == host.etag
                if honoured:
                    spec = range_header.split("=", 1)[1]
                    first, _, _last = spec.partition("-")
                    start = int(first or 0)
                    if start >= total:
                        # Recorded BEFORE the headers go out, not after.
                        # `end_headers()` is what first writes to the socket, so
                        # putting the assignment after it leaves a window in which
                        # the client has read a 416 and the test thread reads
                        # `record["status"]` — still the `None` this dict was
                        # created with. That is not theoretical: it failed roughly
                        # one run in eight, on the pristine tree, as
                        # `assert None == 416`. Assigning first makes the write
                        # happen-before the socket write, so a test that has
                        # received the response is guaranteed to see the status.
                        record["status"] = 416
                        self.send_response(416)
                        self.send_header(
                            "Content-Range", "" if host.suppress_content_range else f"bytes */{total}"
                        )
                        self.send_header("ETag", host.etag)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    partial = True

            record["status"] = 206 if partial else 200
            self.send_response(record["status"])

            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("ETag", host.etag)
            self.send_header("Accept-Ranges", "bytes")
            if partial:
                if not host.suppress_content_range:
                    if host.undeclared_total:
                        self.send_header("Content-Range", f"bytes {start}-*")
                    else:
                        self.send_header(
                            "Content-Range", f"bytes {start}-{total - 1}/{total}"
                        )
                if not host.omit_content_length:
                    self.send_header("Content-Length", str(total - start))
            else:
                if not host.omit_content_length:
                    self.send_header("Content-Length", str(total))
            self.end_headers()

            payload = host.body[start:]

            if host.drop_requests > 0 and host.drop_after is not None:
                host.drop_requests -= 1
                written = payload[: host.drop_after]
                # Counted before the write: the client can finish and the test can
                # read the counter before this thread gets there again.
                host.served_bytes += len(written)
                self.wfile.write(written)
                self.wfile.flush()
                # Abort: the client must see fewer bytes than Content-Length.
                self.close_connection = True
                return

            host.served_bytes += len(payload)
            self.wfile.write(payload)

    return Handler


@pytest.fixture
def origin():
    started = []

    def _start(host: _Host) -> str:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(host))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        return f"http://127.0.0.1:{server.server_address[1]}/model.safetensors"

    yield _start

    for server, _thread in started:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    monkeypatch.setattr(downloads, "_sleep", lambda _seconds: None)


def _download(url, dest, **kwargs):
    kwargs.setdefault("chunk_size", _CHUNK)
    return downloads.download_model_to_path(
        url=url,
        full_path=str(dest),
        log=kwargs.pop("log", lambda _msg: None),
        **kwargs,
    )


def _resume_slots_on_disk(dest):
    return sorted(
        p.name for p in dest.parent.iterdir()
        if downloads.RESUME_SLOT_MARKER in p.name and p.name.endswith(".downloading")
    )


def _park_partial(dest, url, identity, data: bytes):
    """Write a resume slot as if an earlier invocation had abandoned it."""
    slot = downloads._resume_slot_path(str(dest), identity)
    with open(slot, "wb") as handle:
        handle.write(data)
    return slot


def _drop_once(host: _Host) -> None:
    """Sabotage exactly the next request, then behave."""
    host.drop_after = _DROP
    host.drop_requests = 1


# ── Header parsing ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "header,expected",
    [
        ("bytes 100-199/1234", (100, 199, 1234)),
        ("bytes 0-0/1", (0, 0, 1)),
        ("bytes */1234", (None, None, 1234)),
        ("bytes 100-199/*", (100, 199, None)),
        ("bytes 100-/*", (100, None, None)),
        ("bytes 100-199/1234 ", (100, 199, 1234)),
        ("not a range", None),
        ("bytes abc-def/10", None),
        ("bytes 200-100/10", None),
        (None, None),
        ("", None),
    ],
)
def test_parse_content_range(header, expected):
    assert _parse_content_range(header) == expected


# ── 206: append ───────────────────────────────────────────────────────────────

def test_206_appends_and_serves_only_the_missing_tail(origin, tmp_path):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "models" / "model.safetensors"

    _drop_once(host)
    first = _download(url, dest, max_attempts=1)
    assert first["status"] == "error"
    assert _resume_slots_on_disk(dest), "a dropped transfer must leave a resumable partial"
    parked = dest.parent / _resume_slots_on_disk(dest)[0]
    assert parked.stat().st_size == _DROP

    served_before = host.served_bytes
    host.drop_after = None
    second = _download(url, dest)

    assert second["status"] == "success"
    assert second["resumed"] is True
    assert second["resumed_bytes"] == _DROP
    # The tail only: a re-download would have served len(body) bytes again.
    assert host.served_bytes - served_before == len(body) - _DROP
    assert [r["status"] for r in host.requests] == [200, 206]
    assert host.requests[1]["range"] == f"bytes={_DROP}-"
    assert dest.read_bytes() == body
    assert _resume_slots_on_disk(dest) == []


def test_resume_across_invocations_matches_an_uninterrupted_download(origin, tmp_path):
    body = _model_bytes(96 * 1024)
    host = _Host(body)
    url = origin(host)
    clean = tmp_path / "clean" / "model.safetensors"
    resumed = tmp_path / "resumed" / "model.safetensors"

    _drop_once(host)
    assert _download(url, resumed, max_attempts=1)["status"] == "error"

    host.drop_after = None
    assert _download(url, resumed)["status"] == "success"
    assert _download(url, clean)["status"] == "success"

    assert resumed.read_bytes() == clean.read_bytes() == body


def test_retries_resume_within_one_call(origin, tmp_path):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    host.drop_after = 2 * _CHUNK
    host.drop_requests = 2
    result = _download(url, dest)

    assert result["status"] == "success"
    assert result["attempts"] == 3
    assert [r["status"] for r in host.requests] == [200, 206, 206]
    assert [r["range"] for r in host.requests[1:]] == [
        f"bytes={2 * _CHUNK}-",
        f"bytes={4 * _CHUNK}-",
    ]
    assert result["resumed"] is False, "a fresh call reused nothing from a previous one"
    assert result["fetched_bytes"] == len(body)
    assert dest.read_bytes() == body
    # Three attempts, one body: no byte crossed the wire twice.
    assert host.served_bytes == len(body)


# ── 200: the server ignored the Range ─────────────────────────────────────────

def test_200_truncates_instead_of_appending(origin, tmp_path):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    _drop_once(host)
    assert _download(url, dest, max_attempts=1)["status"] == "error"

    host.drop_after = None
    host.honor_range = False  # origin now ignores Range entirely
    served_before = host.served_bytes
    result = _download(url, dest)

    assert result["status"] == "success"
    assert result["resumed"] is False
    # A full body, not the stale partial plus a tail.
    assert host.served_bytes - served_before == len(body)
    assert dest.read_bytes() == body
    assert _resume_slots_on_disk(dest) == []


def test_200_does_not_keep_a_stale_partial_in_front(origin, tmp_path):
    body = _model_bytes()
    other = _model_bytes(64 * 1024)
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    identity = downloads._remote_identity(url, {"etag": host.etag}, len(other))
    _park_partial(dest, url, identity, other)

    result = _download(url, dest)

    assert result["status"] == "success"
    assert dest.read_bytes() == body
    assert dest.read_bytes() != other


# ── 416: the local file is not shorter than the remote one ────────────────────

def test_416_with_a_matching_size_is_treated_as_complete(origin, tmp_path):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    identity = downloads._remote_identity(url, {"etag": host.etag}, len(body))
    _park_partial(dest, url, identity, body)

    result = _download(url, dest)

    assert result["status"] == "success"
    assert host.requests[0]["status"] == 416
    assert host.served_bytes == 0, "416 must not trigger any body transfer"
    assert dest.read_bytes() == body
    assert _resume_slots_on_disk(dest) == []


def test_416_that_cannot_be_confirmed_restarts_clean(origin, tmp_path):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    # A partial larger than the remote body: 416 is right, but "complete" is not.
    oversized = body + b"\x00" * 4096
    identity = downloads._remote_identity(url, {"etag": host.etag}, len(body))
    _park_partial(dest, url, identity, oversized)

    served_before = host.served_bytes
    result = _download(url, dest)

    assert result["status"] == "success"
    assert host.requests[0]["status"] == 416
    assert host.requests[1]["status"] == 200
    assert host.requests[1]["range"] is None
    assert host.served_bytes - served_before == len(body)
    assert dest.read_bytes() == body
    assert _resume_slots_on_disk(dest) == []


def test_416_without_content_range_restarts_clean(origin, tmp_path):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    identity = downloads._remote_identity(url, {"etag": host.etag}, len(body))
    _park_partial(dest, url, identity, body + b"\x00" * 128)
    host.suppress_content_range = True

    result = _download(url, dest)
    assert result["status"] == "success"
    assert host.requests[0]["status"] == 416
    assert dest.read_bytes() == body


# ── A remote file that changed under the partial ──────────────────────────────

@pytest.mark.parametrize("change", ["etag", "length"])
def test_changed_remote_file_restarts_instead_of_appending(origin, tmp_path, change):
    body_a = _model_bytes()
    body_b = _model_bytes(salt=7) if change == "etag" else _model_bytes(72 * 1024, salt=7)
    assert body_a != body_b

    host = _Host(body_a)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    _drop_once(host)
    assert _download(url, dest, max_attempts=1)["status"] == "error"

    host.drop_after = None
    host.body = body_b
    if change == "etag":
        host.etag = '"rev-2"'
    served_before = host.served_bytes
    result = _download(url, dest)

    assert result["status"] == "success"
    # The range request is answered before the change is detectable, so the cost
    # is one wasted tail of the *new* body; the file is then fetched from byte 0.
    assert [r["status"] for r in host.requests[1:]] == [206, 200]
    assert host.served_bytes - served_before == (len(body_b) - _DROP) + len(body_b)
    assert result["resumed"] is False
    assert result["fetched_bytes"] == len(body_b)
    assert dest.read_bytes() == body_b
    assert dest.read_bytes() != body_a[:_DROP] + body_b[_DROP:]


def test_if_range_makes_the_origin_restart_when_the_body_changes_mid_retry(origin, tmp_path):
    body_a = _model_bytes()
    body_b = _model_bytes(64 * 1024)
    host = _Host(body_a)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    host.drop_after = _DROP
    host.drop_requests = 1

    def log(message: str) -> None:
        # The retry is the first request that carries If-Range.
        if "Attempt 2/3" in message:
            host.body = body_b
            host.etag = '"rev-2"'
            host.drop_after = None

    result = _download(url, dest, log=log)

    assert result["status"] == "success"
    assert host.requests[0]["range"] is None
    assert host.requests[1]["if_range"] == '"rev-1"'
    assert host.requests[1]["status"] == 200, "a changed body must not be ranged"
    assert dest.read_bytes() == body_b


# ── The lock ──────────────────────────────────────────────────────────────────

def test_lock_is_still_held_across_a_resume(origin, tmp_path):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"
    lock_path = str(dest) + ".lock"

    _drop_once(host)
    assert _download(url, dest, max_attempts=1)["status"] == "error"

    inode_after_first_call = os.stat(lock_path).st_ino
    host.drop_after = None
    checks = []

    def log(message: str) -> None:
        if "Resuming at byte" not in message:
            return
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            checks.append("acquired")
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BlockingIOError:
            checks.append("held")
        finally:
            os.close(fd)
        checks.append(os.stat(lock_path).st_ino)

    result = _download(url, dest, log=log)

    assert result["status"] == "success"
    assert checks, "the resume never happened"
    assert checks[0] == "held", "the per-path lock was not held during the resume"
    # Unlinking and re-creating the lock is what let a second downloader take a
    # different flock on the same path; the inode must be the one from before.
    assert checks[1] == inode_after_first_call
    assert dest.read_bytes() == body


# ── Validation ────────────────────────────────────────────────────────────────

def test_validation_sees_the_whole_file_and_the_full_size(origin, tmp_path, monkeypatch):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    _drop_once(host)
    assert _download(url, dest, max_attempts=1)["status"] == "error"

    seen = []
    real_validate = downloads.validate_downloaded_file

    def spy(path, total_size, *, unknown_header_log_prefix=None):
        seen.append((path, total_size, os.path.getsize(path)))
        return real_validate(path, total_size, unknown_header_log_prefix=unknown_header_log_prefix)

    monkeypatch.setattr(downloads, "validate_downloaded_file", spy)

    host.drop_after = None
    assert _download(url, dest)["status"] == "success"

    assert len(seen) == 1
    validated_path, expected_size, on_disk = seen[0]
    # The whole file, not the appended 206 tail, and the length of the whole
    # remote body rather than the remaining bytes of the range.
    assert expected_size == len(body)
    assert on_disk == len(body)
    assert validated_path.endswith(".downloading")


def test_validation_rejects_a_resumed_file_that_is_not_a_model(origin, tmp_path):
    """The 416 path appends nothing, so validation can only pass on the whole file."""
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    # A full-length file that is not a model at all. Nothing is fetched, so a
    # validator that only looked at the appended chunk would pass this.
    impostor = b"<!DOCTYPE html><html>not a checkpoint</html>"
    impostor = impostor + b"\x00" * (len(body) - len(impostor))
    assert len(impostor) == len(body)
    identity = downloads._remote_identity(url, {"etag": host.etag}, len(body))
    _park_partial(dest, url, identity, impostor)

    result = _download(url, dest)

    assert result["status"] == "error"
    assert "Validation failed" in result["message"]
    assert not dest.exists(), "an invalid file must never be published"
    # All the bytes are there and all wrong: a rerun must start from byte 0.
    assert _resume_slots_on_disk(dest) == []


def test_an_indeterminate_validation_keeps_the_bytes_and_the_resume_slot(origin, tmp_path):
    """`indeterminate` means the file could not be READ, not that it is bad.

    `provider_core/validation.py` states the contract this caller broke: "A
    caller that can act destructively on `invalid` MUST check `indeterminate`
    first. Deleting on an indeterminate result is never correct." It removed the
    temp file *and* every resume slot, so one transient read fault — a gcsfuse
    EIO, routine on the Modal volumes — converted a partially-downloaded 7 GB
    checkpoint back to byte 0, which is the entire thing `_transfer_with_resume`
    exists to prevent. Unattended, every couple of hours, on a multi-GB artifact
    with no way to recover it.
    """
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    identity = downloads._remote_identity(url, {"etag": host.etag}, len(body))
    _park_partial(dest, url, identity, body[:_DROP])

    import provider_core.downloads as downloads_mod

    real_validator = downloads_mod.validate_downloaded_file

    def _read_fails(path, total_size=0, **kwargs):
        # The shape `validate_downloaded_file` returns when a `read()` raises
        # EIO/ENOMEM: valid False, indeterminate True. The file on disk is the
        # real, complete, byte-correct model — which is the point: the reader
        # could not find out, and neither can we.
        return {
            "valid": False,
            "indeterminate": True,
            "error": "Could not read file: [Errno 5] Input/output error",
        }

    downloads_mod.validate_downloaded_file = _read_fails
    try:
        result = _download(url, dest)
    finally:
        downloads_mod.validate_downloaded_file = real_validator

    # Still reported as a failure: the caller learns the download did not finish,
    # and the message says why rather than implying the bytes are corrupt.
    assert result["status"] == "error"
    assert "could not read" in result["message"].lower(), result["message"]
    assert not dest.exists(), "nothing may be published on an unreadable read"

    # The property that matters: the bytes are still on disk in a form the next
    # attempt can find and resume from. The outer `except Exception` sweeps this
    # attempt's temp file on any raise, so the fix has to RE-PARK the partial as
    # a resume slot rather than merely skip two removes — otherwise "leave it
    # alone" is satisfied by a file nothing will ever look at again.
    slots = _resume_slots_on_disk(dest)
    assert len(slots) == 1, (
        f"an indeterminate validation left the bytes where no attempt will find "
        f"them: {list(downloads.pending_download_paths(str(dest)))}"
    )
    parked = dest.parent / slots[0]
    assert parked.stat().st_size == len(body), (
        "the partial did not keep its bytes, so the next attempt starts from 0"
    )


def test_the_next_attempt_resumes_after_an_indeterminate_validation(origin, tmp_path):
    """The reason the previous test exists: not "a file is left", but "it is used".

    The whole point of `_transfer_with_resume` is that the second call does not
    re-fetch the bytes the first one already had.
    """
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    import provider_core.downloads as downloads_mod

    real_validator = downloads_mod.validate_downloaded_file
    calls = {"n": 0}

    def _first_read_fails(path, total_size=0, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "valid": False,
                "indeterminate": True,
                "error": "Could not read file: [Errno 5] Input/output error",
            }
        return real_validator(path, total_size, **kwargs)

    downloads_mod.validate_downloaded_file = _first_read_fails
    try:
        first = _download(url, dest)
        assert first["status"] == "error"
        assert len(_resume_slots_on_disk(dest)) == 1

        second = _download(url, dest)
    finally:
        downloads_mod.validate_downloaded_file = real_validator

    assert second["status"] == "success", second
    assert second["resumed"] is True, "the second attempt re-fetched from byte 0"
    assert dest.read_bytes() == body


def test_a_genuinely_invalid_file_still_loses_its_resume_slot(origin, tmp_path):
    """The counter-test: `invalid` (not `indeterminate`) must still sweep.

    Otherwise "never delete on indeterminate" is satisfied by never deleting at
    all, and a corrupt checkpoint would be retried forever against a body that
    is wrong every time.
    """
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    # A full-length body that is not a model, parked as the partial. Same setup as
    # `test_validation_rejects_a_resumed_file_that_is_not_a_model`, so this branch
    # is the one that differs: `invalid` rather than `indeterminate`.
    impostor = b"<!DOCTYPE html><html>not a checkpoint</html>"
    impostor = impostor + b"\x00" * (len(body) - len(impostor))
    identity = downloads._remote_identity(url, {"etag": host.etag}, len(body))
    _park_partial(dest, url, identity, impostor)

    result = _download(url, dest)

    assert result["status"] == "error"
    assert "Validation failed" in result["message"]
    assert not dest.exists()
    assert _resume_slots_on_disk(dest) == [], (
        "a genuinely invalid file must start from byte 0 on the next attempt"
    )


# ── Giving up ─────────────────────────────────────────────────────────────────

def test_giving_up_reports_the_resume_offset_and_keeps_the_partial(origin, tmp_path):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    host.drop_after = 2 * _CHUNK
    host.drop_requests = 99  # every attempt dies the same way
    result = _download(url, dest, max_attempts=3)

    assert result["status"] == "error"
    assert "gave up after 3 attempt(s)" in result["message"]
    assert f"resume from byte {6 * _CHUNK}" in result["message"]

    slots = _resume_slots_on_disk(dest)
    assert len(slots) == 1, f"exactly one resumable partial expected, got {slots}"
    parked = dest.parent / slots[0]
    assert parked.stat().st_size == 6 * _CHUNK
    assert parked.read_bytes() == body[: 6 * _CHUNK]


def test_permanent_http_status_is_not_retried(origin, tmp_path):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    _drop_once(host)
    assert _download(url, dest, max_attempts=1)["status"] == "error"

    requests_before = len(host.requests)
    host.status_override = 404
    result = _download(url, dest, max_attempts=3)

    assert result["status"] == "error"
    assert "HTTP 404" in result["message"]
    assert len(host.requests) - requests_before == 1, "a 404 must not be retried"


# ── The parked partial is pipeline-owned, not a model ─────────────────────────

def test_parked_partial_is_a_transient_artifact_not_a_model(origin, tmp_path):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    host.drop_after = _DROP
    host.drop_requests = 99
    assert _download(url, dest, max_attempts=1)["status"] == "error"

    slots = _resume_slots_on_disk(dest)
    assert len(slots) == 1
    name = slots[0]

    assert is_transient_artifact(name)
    assert not is_model_file(name)
    assert str(dest) not in [str(p) for p in pending_download_paths(str(dest))]
    assert str(dest.parent / name) in [str(p) for p in pending_download_paths(str(dest))]


def test_no_partial_survives_a_successful_download(origin, tmp_path):
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    _drop_once(host)
    assert _download(url, dest, max_attempts=1)["status"] == "error"
    assert _download(url, dest)["status"] == "success"

    leftovers = [p.name for p in dest.parent.iterdir() if p.name.endswith(".downloading")]
    assert leftovers == []


# ── A transfer whose total was never declared ─────────────────────────────────
#
# `total_size == 0` does not mean "no length check needed", it means "there is no
# length to check against". Both of the pipeline's size comparisons are
# conditioned on a non-zero total, so an undeclared total skipped *both*:
#
#     remote total                     : 7000000
#     total_size seen by _attempt_download: 0        <- unknown
#     bytes on disk                    : 60202
#     validate_downloaded_file(...)     : {'valid': True, 'indeterminate': False}
#     os.replace would publish 60202 bytes as a 7 MB model: True
#
#   — `validate_downloaded_file` checks the magic header, not the length, so a
#   short file of a real model is a *valid* short file.


def test_a_206_without_a_declared_total_is_never_published(origin, tmp_path):
    body = _model_bytes(96 * 1024)
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "models" / "model.safetensors"

    _drop_once(host)
    assert _download(url, dest, max_attempts=1)["status"] == "error"
    assert _resume_slots_on_disk(dest), "precondition: a resumable partial exists"

    # The resume now answers 206 with `bytes <start>-*` and no Content-Length.
    host.undeclared_total = True
    host.omit_content_length = True
    result = _download(url, dest)

    assert host.requests[-1]["status"] == 206
    assert result["status"] == "error", result
    assert "never declared the total size" in result["message"], result
    assert not dest.exists(), "a download of unknown length was published as a model"


def test_a_206_without_a_total_does_not_retry(origin, tmp_path):
    """A server that will not name a total will not name one on the next ask, and
    each attempt re-fetches the body."""
    body = _model_bytes(96 * 1024)
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "models" / "model.safetensors"

    _drop_once(host)
    assert _download(url, dest, max_attempts=1)["status"] == "error"

    host.undeclared_total = True
    host.omit_content_length = True
    before = len(host.requests)
    _download(url, dest, max_attempts=3)

    assert len(host.requests) - before == 1, host.requests[before:]


def test_a_200_without_a_content_length_is_never_published(origin, tmp_path):
    """The other shape of the same hole: a body delimited only by EOF."""
    body = _model_bytes(96 * 1024)
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "models" / "model.safetensors"

    host.omit_content_length = True
    result = _download(url, dest)

    assert host.requests[0]["status"] == 200
    assert result["status"] == "error", result
    assert "never declared the total size" in result["message"], result
    assert not dest.exists()


def test_the_bytes_are_kept_for_the_next_attempt(origin, tmp_path):
    """The verdict is about the *length*, not the content.

    Parking the partial is correct here and deleting it would be the F7 mistake:
    the bytes that arrived are good, and an attempt that later gets a declared
    total resumes from them instead of re-fetching the whole file.

    Asserted from the request the client made, not from a byte counter: the origin
    thread increments `served_bytes` when it finishes writing, so a response the
    client deliberately refused leaves the counter settling afterwards, and
    measuring across one is a race.
    """
    body = _model_bytes(96 * 1024)
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "models" / "model.safetensors"

    _drop_once(host)
    assert _download(url, dest, max_attempts=1)["status"] == "error"

    host.undeclared_total = True
    host.omit_content_length = True
    _download(url, dest)
    assert _resume_slots_on_disk(dest), "the good bytes were thrown away"

    # ...and the next attempt, against a server that declares its total, resumes
    # from them: a 206 with a Range, not a fresh 200 from byte 0.
    host.undeclared_total = False
    host.omit_content_length = False
    before = len(host.requests)
    result = _download(url, dest)

    assert result["status"] == "success", result
    assert dest.read_bytes() == body
    assert host.requests[before]["status"] == 206, host.requests[before:]
    assert host.requests[before]["range"] == "bytes=20480-", host.requests[before:]
    assert len(host.requests) - before == 1, "the resume took more than one request"


def test_a_declared_total_is_still_honoured(origin, tmp_path):
    """The control, in both directions.

    Without it, "always refuse to publish" passes everything above while breaking
    every real download.
    """
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    complete = tmp_path / "complete" / "model.safetensors"
    truncated = tmp_path / "truncated" / "model.safetensors"

    assert _download(url, complete)["status"] == "success"
    assert complete.read_bytes() == body

    _drop_once(host)
    result = _download(url, truncated, max_attempts=1)
    assert result["status"] == "error", "a truncated body must still be rejected"


def test_the_publish_gate_rejects_a_zero_total_even_if_the_transfer_claims_success(
    origin, tmp_path, monkeypatch
):
    """The gate is independent of the one in `_attempt_download`.

    `download_model_to_path` refuses an undeclared total at the only place where
    the consequence happens — `os.replace` into the live model tree — so a path
    that reaches the publish with an unverified length cannot do it merely by not
    inheriting the inner guard.
    """
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    real = downloads._transfer_with_resume

    def _undeclared(**kwargs):
        outcome = real(**kwargs)
        outcome["total_size"] = 0
        return outcome

    monkeypatch.setattr(downloads, "_transfer_with_resume", _undeclared)

    result = _download(url, dest)

    assert result["status"] == "error", result
    assert "Refusing to publish" in result["message"], result
    assert not dest.exists()


# ── Out of space ──────────────────────────────────────────────────────────────
#
# Parking is right for `indeterminate` and for a dropped connection: the partial
# is good and the next attempt resumes it. It is wrong for "the filesystem said
# no", because `rename(2)` needs no space — so `_persist_partial` succeeded on a
# volume with none, and every out-of-space attempt stranded a multi-GB partial
# that the next attempt moved straight back into the same wall.
#
# `shutil.disk_usage` was not called anywhere in the tier (`rg
# 'disk_usage|statvfs|free_space|shutil.disk'` returned zero hits), so the volume's
# state was never consulted before a multi-GB transfer started.


# Comfortably more than the 64 MB default headroom, so a test that wants the
# download to proceed does not have to reason about it.
PLENTY = 8 * 1024 ** 3


def _fake_disk_usage(free_bytes: int):
    """A `shutil.disk_usage` reporting `free_bytes` free, whatever the mount says."""
    import collections

    usage = collections.namedtuple("usage", "total used free")
    reported = usage(total=free_bytes + 1024, used=1024, free=free_bytes)

    def _fake(path):
        return reported

    return _fake


def test_a_download_that_cannot_fit_is_refused_before_any_byte_is_written(
    origin, tmp_path, monkeypatch
):
    body = _model_bytes(96 * 1024)
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "models" / "model.safetensors"

    # Room for the bytes but not for the headroom the sidecars and the lock need.
    monkeypatch.setattr(downloads.shutil, "disk_usage", _fake_disk_usage(len(body)))

    result = _download(url, dest)

    assert result["status"] == "error", result
    assert "not enough free space" in result["message"], result
    assert not dest.exists()
    # Not one byte was written. The request itself still happened — the total is
    # only known from the headers, so the client cannot refuse before connecting —
    # but the body was never put on disk.
    assert [p.name for p in dest.parent.iterdir() if p.name.endswith(".downloading")] == []


def test_the_refusal_names_the_volume_and_the_shortfall(origin, tmp_path, monkeypatch):
    body = _model_bytes(96 * 1024)
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "models" / "model.safetensors"

    monkeypatch.setattr(downloads.shutil, "disk_usage", _fake_disk_usage(1024))

    result = _download(url, dest)

    message = result["message"]
    assert str(dest.parent) in message, message
    assert "needed for this download" in message, message


def test_a_resume_checks_only_the_bytes_still_missing(origin, tmp_path, monkeypatch):
    """Not the whole file again. A 7 GB resume that needs 200 MB must not be
    refused by a 7 GB requirement on a volume holding 1 GB."""
    body = _model_bytes(96 * 1024)
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "models" / "model.safetensors"

    _drop_once(host)
    assert _download(url, dest, max_attempts=1)["status"] == "error"

    remaining = len(body) - 2 * _CHUNK
    # Enough for what is missing, and not enough for the whole file again.
    monkeypatch.setattr(
        downloads.shutil,
        "disk_usage",
        _fake_disk_usage(remaining + downloads.DOWNLOAD_FREE_SPACE_MARGIN_BYTES),
    )

    result = _download(url, dest)
    assert result["status"] == "success", result
    assert dest.read_bytes() == body


def test_an_enospc_mid_transfer_is_not_parked(origin, tmp_path, monkeypatch):
    """The bytes on disk are dropped, not parked on a volume that is full.

    `_persist_partial` would have succeeded — `rename(2)` needs no space — so the
    unfixed pipeline reported "N bytes kept at offset N" and left them there.
    """
    body = _model_bytes(96 * 1024)
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "models" / "model.safetensors"

    monkeypatch.setattr(downloads.shutil, "disk_usage", _fake_disk_usage(PLENTY))

    real_open = open

    def _fail_once(path, mode="r", *args, **kwargs):
        if "ab" in mode or "wb" in mode:
            handle = real_open(path, mode, *args, **kwargs)
            real_write = handle.write

            def _write(chunk):
                real_write(chunk)
                raise OSError(28, "No space left on device")

            handle.write = _write
            return handle
        return real_open(path, mode, *args, **kwargs)

    # Restored directly rather than via `monkeypatch.undo()`, which would also
    # unwind the autouse backoff patch this test never asked about.
    import builtins

    builtins.open = _fail_once
    try:
        result = _download(url, dest, max_attempts=1)
    finally:
        builtins.open = real_open

    assert result["status"] == "error", result
    assert "No space left on device" in result["message"], result
    assert _resume_slots_on_disk(dest) == [], "an ENOSPC partial was parked"
    assert [p.name for p in dest.parent.iterdir() if p.name.endswith(".downloading")] == []
    assert not dest.exists()


def test_a_connection_reset_is_still_parked(origin, tmp_path, monkeypatch):
    """The control, and the reason the rule is narrow.

    Parking a partial is what `_transfer_with_resume` exists for. If the out-of-space
    branch swallowed everything, a dropped connection would also stop being
    resumable and every retry would restart from byte 0.
    """
    body = _model_bytes(96 * 1024)
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "models" / "model.safetensors"

    monkeypatch.setattr(downloads.shutil, "disk_usage", _fake_disk_usage(PLENTY))

    _drop_once(host)
    result = _download(url, dest, max_attempts=1)

    assert result["status"] == "error", result
    assert _resume_slots_on_disk(dest), "a transient drop must stay resumable"


def test_a_read_failure_in_free_space_does_not_block_the_download(
    origin, tmp_path, monkeypatch
):
    """`disk_usage` is a hint, not a gate. A filesystem that cannot report its free
    space must not make every download on it impossible."""
    body = _model_bytes()
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "model.safetensors"

    def _explode(path):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(downloads.shutil, "disk_usage", _explode)

    result = _download(url, dest)
    assert result["status"] == "success", result
    assert dest.read_bytes() == body


def test_the_headroom_is_configurable(origin, tmp_path, monkeypatch):
    body = _model_bytes(96 * 1024)
    host = _Host(body)
    url = origin(host)
    dest = tmp_path / "models" / "model.safetensors"

    monkeypatch.setattr(downloads, "DOWNLOAD_FREE_SPACE_MARGIN_BYTES", 0)
    monkeypatch.setattr(downloads.shutil, "disk_usage", _fake_disk_usage(len(body)))

    result = _download(url, dest)
    assert result["status"] == "success", result
