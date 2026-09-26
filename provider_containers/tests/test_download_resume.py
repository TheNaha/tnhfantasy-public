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
                self.send_response(host.status_override)
                self.send_header("Content-Length", "0")
                self.end_headers()
                record["status"] = host.status_override
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
                        self.send_response(416)
                        self.send_header(
                            "Content-Range", "" if host.suppress_content_range else f"bytes */{total}"
                        )
                        self.send_header("ETag", host.etag)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        record["status"] = 416
                        return
                    partial = True

            record["status"] = 206 if partial else 200
            self.send_response(record["status"])
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("ETag", host.etag)
            self.send_header("Accept-Ranges", "bytes")
            if partial:
                if not host.suppress_content_range:
                    self.send_header("Content-Range", f"bytes {start}-{total - 1}/{total}")
                self.send_header("Content-Length", str(total - start))
            else:
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
