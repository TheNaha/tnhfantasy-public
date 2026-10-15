"""Shared download pipeline helpers for provider workers."""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from .utils import DOWNLOADING_SUFFIX, LOCK_SUFFIX
from .validation import validate_downloaded_file
from .logging import get_logger

logger = get_logger("provider_core.downloads")

ProgressCallback = Callable[[Dict[str, Any]], None]
LogCallback = Callable[[str], None]

# Marker inside the name of a resume slot. A resume slot is a single,
# deterministic sibling of the model holding the bytes of an *abandoned*
# attempt so that the next invocation of download_model_to_path continues it
# instead of re-fetching gigabytes that are already on disk.
#
# The name deliberately ends in DOWNLOADING_SUFFIX. `is_transient_artifact`,
# `is_model_file` and `pending_download_paths` already treat that suffix as
# pipeline-owned, so reconciliation can neither publish a partial as a model nor
# leave it behind, and `FileStorage.delete_file` already sweeps it. A new suffix
# would have to be added to TRANSIENT_SUFFIXES in utils.py, which a multi-GB
# partial must not depend on being noticed there.
RESUME_SLOT_MARKER = ".resume."

DEFAULT_MAX_ATTEMPTS = 3
RETRY_BACKOFF_BASE_SECONDS = 2.0
RETRY_BACKOFF_MAX_SECONDS = 30.0

# HTTP statuses worth another attempt. Everything else in the 4xx range (401,
# 403, 404, 410, 422 ...) will fail identically on a retry and is reported at
# once so the operator sees the real cause instead of a backoff countdown.
TRANSIENT_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

# Disk failures that will never succeed on a retry. A connection reset must be
# retried (that is the whole point of resume); ENOSPC must not be.
PERMANENT_ERRNOS = frozenset(
    {errno.ENOSPC, errno.EDQUOT, errno.EACCES, errno.EROFS, errno.EISDIR, errno.EPERM}
)

# "The filesystem said no", as distinct from "I could not read it" and from
# "something is wrong with the bytes".
#
# Parking is right for a *transient* failure: the partial is good, the next
# attempt resumes it, and nothing is lost. It is wrong for this pair. `rename(2)`
# needs no space and no blocks, so `_persist_partial` succeeds, parks the partial,
# and reports "N bytes kept" — on a volume that has no space for the next attempt
# either. The next `_claim_resume_slot` moves those gigabytes back out and
# appends into the same full volume, fails at the same wall, and parks again. So
# every out-of-space attempt leaves a multi-GB file on a full volume, and the
# error the operator sees is a resume offset rather than the actual cause.
#
# The messages are matched too, not only the errno: a gcsfuse or an overlay mount
# can report the same condition with the errno stripped, and `ENOSPC` buried
# inside a wrapper that is no longer an `OSError`.
OUT_OF_SPACE_ERRNOS = frozenset({errno.ENOSPC, errno.EDQUOT})
OUT_OF_SPACE_MESSAGES = ("No space left on device", "Disk quota exceeded")

# Headroom required on top of the bytes about to be written, so a download that
# exactly fills the volume still leaves room for its `.json` and `.preview.png`
# sidecars, the `.lock`, and whatever else shares the mount.
DOWNLOAD_FREE_SPACE_MARGIN_BYTES = int(
    os.getenv("PROVIDER_DOWNLOAD_FREE_SPACE_MARGIN_BYTES", str(64 * 1024 * 1024))
)


class _DownloadAttemptError(Exception):
    """A single attempt failed. `transient` decides retry vs. give up."""

    def __init__(self, message: str, *, transient: bool = True) -> None:
        super().__init__(message)
        self.transient = transient


class _HeldPathLock:
    """The handle `exclusive_path_lock` yields.

    `release_file()` is deliberately a separate call from leaving the `with`
    block. Unlinking a flock file is unsafe in general — a process can be between
    `open()` and `flock()` when the path disappears, and then it holds a lock on
    an unlinked inode while a third `O_CREAT`s a fresh one and takes a different
    lock — and the only party that can tell whether that is currently possible
    is the one that just let go. The downloader knows: a *failed* attempt may be
    resumed, and the resuming attempt must flock the same inode
    (`tests/test_download_resume.py::test_lock_is_still_held_across_a_resume`
    pins exactly that), whereas a *successful* one has published the model,
    swapped every byte of it and left no resume slot, so a second downloader for
    the same path has nothing to lose but the last `os.replace` — and
    `_unique_temp_path` plus `_claim_resume_slot`'s `except OSError` already
    make that race harmless.
    """

    __slots__ = ("_lock_path",)

    def __init__(self, lock_path: str) -> None:
        self._lock_path = lock_path

    def release_file(self) -> None:
        try:
            os.remove(self._lock_path)
        except OSError:
            pass


@contextlib.contextmanager
def exclusive_path_lock(full_path: str) -> Iterator[_HeldPathLock]:
    """Serialise downloads of the same destination across threads and processes.

    Without this, two concurrent downloads of one `full_path` shared the
    deterministic `<path>.downloading` temp file: the second `open(..., "wb")`
    truncated the first's partial data, both handles then wrote at their own
    offsets into the same inode, and both passed validation — the size is the
    full size either way, and whichever wrote offset 0 put a valid magic header
    there. The first to finish `os.replace`d a silently interleaved file into
    place. The second replaced it with its own interleaved version. A corrupted
    model published with no error anywhere.

    flock is used rather than an O_EXCL lock file because the kernel releases
    it if the process dies, so a crash mid-download cannot leave a lock that
    blocks every future attempt until someone deletes it by hand.

    The lock *file* outlives the flock, because a 0-byte `.lock` is a transient
    artifact that every validator counts as `partial` and nothing removed them:
    `total_partial` grew by one for every model ever downloaded and stopped
    meaning "a transfer is in flight", which is the only thing reconciliation
    reads it for. A successful download unlinks its own lock
    (`_HeldPathLock.release_file`) and a failed one deliberately does not, so
    the resuming attempt flocks the same inode. The abandoned ones — a crashed
    attempt, a lock with no model beside it — are reclaimed by the delete routes
    via `pipeline_artifacts`, which is the only place that can tell an
    in-flight attempt from a dead one.
    """
    lock_path = f"{full_path}.lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    handle = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield _HeldPathLock(lock_path)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


def _download_scratch_dir() -> Optional[str]:
    scratch = os.getenv("PROVIDER_DOWNLOAD_SCRATCH_DIR", "").strip()
    if scratch:
        try:
            os.makedirs(scratch, exist_ok=True)
            return scratch
        except OSError as exc:
            logger.warning(f"Could not create PROVIDER_DOWNLOAD_SCRATCH_DIR {scratch!r}: {exc}")
    return None


def _replace_or_move(src: str, dst: str) -> None:
    """Atomically replace dst with src, handling cross-device moves safely.

    On the same filesystem, this is an atomic os.replace(2).
    Across different filesystems (e.g. local NVMe SSD scratch -> Google Drive FUSE mount),
    it copies to a transient .publishing file on the destination filesystem first,
    atomically os.replace(2)s into place, and unlinks src.
    """
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            dst_tmp = f"{dst}.{os.getpid()}.{uuid.uuid4().hex[:8]}.publishing"
            shutil.copyfile(src, dst_tmp)
            os.replace(dst_tmp, dst)
            try:
                os.remove(src)
            except OSError:
                pass
        else:
            raise


def _unique_temp_path(full_path: str) -> str:
    """Per-attempt temp path.

    Belt-and-braces with the lock: even if a lock is somehow bypassed, two
    attempts can no longer share a file, so interleaving is impossible. The
    previous deterministic `<path>.downloading` name was the root of the
    corruption described in exclusive_path_lock.

    If PROVIDER_DOWNLOAD_SCRATCH_DIR is configured, the temp file is created in
    that fast local scratch directory to protect network/FUSE mounts from high-I/O
    saturation and disconnects during streaming downloads.
    """
    scratch = _download_scratch_dir()
    if scratch:
        path_hash = hashlib.sha256(full_path.encode("utf-8", "replace")).hexdigest()[:8]
        safe_name = os.path.basename(full_path)
        return os.path.join(scratch, f"{safe_name}.{path_hash}.{os.getpid()}.{uuid.uuid4().hex[:8]}.downloading")
    return f"{full_path}.{os.getpid()}.{uuid.uuid4().hex[:8]}.downloading"


# ── Resume ────────────────────────────────────────────────────────────────────
#
# A dropped connection 6 GB into a 7 GB checkpoint used to throw all of it away.
# Resume is only safe if two things hold: the partial must be the *same* file we
# are now being offered (same URL, same ETag/Last-Modified, same total size), and
# the server must actually agree to send the remainder. A blind append to a file
# whose remote counterpart changed produces a plausible-looking, silently corrupt
# model, which is strictly worse than re-downloading.

def _sleep(seconds: float) -> None:
    """Indirection so tests can run the backoff without waiting for it."""
    if seconds > 0:
        time.sleep(seconds)


def _backoff_delay(failed_attempt: int, base: float, cap: float) -> float:
    if base <= 0:
        return 0.0
    return min(base * (2 ** (max(failed_attempt, 1) - 1)), cap)


def _format_size(num_bytes: float) -> str:
    size_gb = num_bytes / (1024 ** 3)
    if size_gb >= 1:
        return f"{size_gb:.2f} GB"
    return f"{num_bytes / (1024 ** 2):.1f} MB"


def _int_header(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _normalise_etag(value: Optional[str]) -> str:
    etag = (value or "").strip()
    if etag.startswith("W/"):
        etag = etag[2:]
    return etag


def _resume_slot_path(full_path: str, identity: str) -> str:
    return f"{full_path}{RESUME_SLOT_MARKER}{identity}{DOWNLOADING_SUFFIX}"


def _resume_slots(full_path: str) -> List[Tuple[str, str]]:
    """Return `(identity, path)` for every resume slot of `full_path`, oldest first.

    The identity lives in the file name, so a partial carries the record of what
    it is a partial *of* without a second sidecar file that reconciliation would
    have to learn about.
    """
    directory = os.path.dirname(full_path) or "."
    prefix = os.path.basename(full_path) + RESUME_SLOT_MARKER
    try:
        entries = os.listdir(directory)
    except OSError:
        return []

    found: List[Tuple[float, str, str]] = []
    for entry in entries:
        if not entry.startswith(prefix) or not entry.endswith(DOWNLOADING_SUFFIX):
            continue
        identity = entry[len(prefix): -len(DOWNLOADING_SUFFIX)]
        if not identity:
            continue
        path = os.path.join(directory, entry)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        found.append((mtime, identity, path))

    found.sort()
    return [(identity, path) for _mtime, identity, path in found]


def _remote_identity(url: str, headers: Any, total_size: int) -> str:
    """Short digest of everything that makes a remote body *the same* body.

    Size is part of the identity because a checkpoint that was re-uploaded with
    different content can keep its name and path but not its length. With no
    ETag, no Last-Modified and no known length the identity degrades to a digest
    of the URL alone: resume still works, it just cannot detect a changed remote.
    """
    etag = _normalise_etag(_header_get(headers, "etag"))
    last_modified = (_header_get(headers, "last-modified") or "").strip()
    payload = "\x00".join((url, etag, last_modified, str(int(total_size or 0))))
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:12]


def _header_get(headers: Any, name: str) -> Optional[str]:
    if headers is None:
        return None
    try:
        return headers.get(name)
    except AttributeError:
        return None


def _parse_content_range(value: Optional[str]) -> Optional[Tuple[Optional[int], Optional[int], Optional[int]]]:
    """Parse a `Content-Range` header into `(start, end, total)`.

    `bytes 100-199/1234` -> (100, 199, 1234); `bytes */1234` -> (None, None, 1234);
    `bytes 100-199/*` -> (100, 199, None). Returns None for anything unparseable,
    which callers must treat as "cannot trust this response".
    """
    if not value:
        return None
    text = str(value).strip()
    if not text.lower().startswith("bytes"):
        return None
    spec = text[5:].strip()

    range_part, _, total_part = spec.partition("/")
    total: Optional[int] = None
    if total_part.strip() and total_part.strip() != "*":
        total = _int_header(total_part) or None

    if range_part.strip() == "*":
        return (None, None, total)

    start_text, _, end_text = range_part.partition("-")
    start_text = start_text.strip()
    if not start_text.isdigit():
        return None
    start = int(start_text)
    end: Optional[int] = None
    if end_text.strip() and end_text.strip() != "*":
        end = _int_header(end_text)
        if end < start:
            return None
    return (start, end, total)


def _claim_resume_slot(full_path: str, temp_path: str) -> Tuple[Optional[str], int]:
    """Move the newest resume slot into this attempt's unique temp file.

    Only ever called with the per-path lock held, so any slot still on disk was
    abandoned by a dead or finished attempt and nobody holds a descriptor on it.
    The rename is what keeps the per-attempt temp file unique — this attempt ends
    up writing to a path no other attempt can name — while still letting a later
    invocation find the bytes.

    Returns `(identity recorded in the slot name, bytes recovered)`.
    """
    slots = _resume_slots(full_path)
    if not slots:
        return None, 0

    identity, newest = slots[-1]
    for _stale_identity, stale in slots[:-1]:
        _remove_quietly(stale)

    try:
        recovered = os.path.getsize(newest)
        _replace_or_move(newest, temp_path)
    except OSError:
        return None, 0
    return identity, recovered


def _persist_partial(full_path: str, temp_path: str, identity: Optional[str]) -> int:
    """Park this attempt's partial in the resume slot for the next invocation.

    Returns the number of bytes kept. Without an identity there is nothing to
    prove the partial matches, so it is dropped rather than resumed blindly.
    """
    if not identity or not os.path.exists(temp_path):
        _remove_quietly(temp_path)
        return 0

    size = os.path.getsize(temp_path)
    if size <= 0:
        _remove_quietly(temp_path)
        return 0

    try:
        _replace_or_move(temp_path, _resume_slot_path(full_path, identity))
    except OSError as exc:
        # Keep the bytes where they are; the name still ends in .downloading so
        # delete_file and reconciliation can sweep it.
        logger.warning(f"Could not park partial download: {exc} ({temp_path})")
        return 0
    return size


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _close_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if close is not None:
        with contextlib.suppress(Exception):
            close()


def _reject_undeclared_total(total_size: int) -> None:
    """Refuse a response that never said how big the body is.

    `total_size == 0` does not mean "no length check needed", it means "there is
    no length to check against". Both of the pipeline's size comparisons are
    conditioned on a non-zero total — `on_disk != total_size` here and the
    `total_size > 0` gate on the published file — so an undeclared total skipped
    *both*. Reproduced against the pipeline:

        remote total                      : 7000000
        total_size seen here              : 0          <- unknown
        bytes on disk                     : 60202
        validate_downloaded_file(...)     : {'valid': True, 'indeterminate': False}
        os.replace would publish 60202 bytes as a 7 MB model: True

    `validate_downloaded_file` checks the magic header, not the length, so a short
    file of a real model is a *valid* short file. A 206 reaches this with
    `total_size == 0` when `Content-Range` names no total (`bytes 60202-*`) and
    the response carries no `Content-Length`; a 200 does when the body is
    delimited only by EOF. Both are legal HTTP.

    Raised before the body is streamed and before `observed["identity"]` is set,
    so no megabyte is fetched to reach the verdict. `transient=False`: no retry
    changes what the server chooses to send. On a resume the attempt's bytes are
    still parked under the identity the *earlier* attempt recorded, because
    `_transfer_with_resume` keeps the claimed identity when the headers named
    none — which is why the good bytes survive for the next attempt.
    """
    if total_size:
        return
    raise _DownloadAttemptError(
        "the server never declared the total size "
        "(no Content-Range total and no Content-Length); refusing to accept a "
        "download of unknown length",
        transient=False,
    )


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, _DownloadAttemptError):
        return exc.transient
    if isinstance(exc, (KeyboardInterrupt, SystemExit, MemoryError)):
        return False
    if isinstance(exc, OSError) and exc.errno in PERMANENT_ERRNOS:
        return False
    return True


def _is_out_of_space(exc: BaseException) -> bool:
    """Did the filesystem refuse because it is full?"""
    if isinstance(exc, OSError) and exc.errno in OUT_OF_SPACE_ERRNOS:
        return True
    text = str(exc)
    return any(message in text for message in OUT_OF_SPACE_MESSAGES)


def _ensure_free_space(path: str, needed_bytes: int) -> None:
    """Refuse to start writing `needed_bytes` into a volume that cannot hold them.

    Without this, "no space" is discovered by the kernel part-way through a 7 GB
    transfer: everything up to that point was fetched, written and then parked,
    and the volume is left full. Checking once the headers have named the total —
    before a single body byte is written — turns a multi-GB, minutes-long failure
    into an immediate one with a message that says what to do.

    Skipped when the remaining length is unknown (there is nothing to check
    against; `_reject_undeclared_total` has already refused that case) and when
    `disk_usage` itself fails. A volume whose free space cannot be read is not a
    reason to refuse a download — the read is a hint, not a gate, and treating it
    as a gate would break every download on a filesystem that does not report it.
    """
    if needed_bytes <= 0:
        return
    directory = os.path.dirname(path) or "."
    try:
        free = shutil.disk_usage(directory).free
    except (OSError, ValueError):
        return
    required = needed_bytes + DOWNLOAD_FREE_SPACE_MARGIN_BYTES
    if free >= required:
        return
    raise _DownloadAttemptError(
        f"not enough free space in {directory}: {_format_size(free)} available, "
        f"{_format_size(needed_bytes)} needed for this download "
        f"(plus {_format_size(DOWNLOAD_FREE_SPACE_MARGIN_BYTES)} of headroom); "
        f"free space on the volume before downloading a model",
        transient=False,
    )


def _stream_to_file(
    response: Any,
    temp_path: str,
    *,
    append: bool,
    start_offset: int,
    total_size: int,
    chunk_size: int,
    attempt_state: Dict[str, Any],
    log: LogCallback,
    log_prefix: str,
    progress_callback: Optional[ProgressCallback],
) -> int:
    """Copy the response body into `temp_path`, returning bytes written.

    `append` selects `ab` over `wb`, i.e. keep the partial and add the remainder
    rather than truncate. Progress is reported against the whole file
    (`start_offset + written`), so a resumed download does not show 0-100% for
    the tail only.

    The running total is kept in `attempt_state` because a connection that dies
    mid-body throws away this function's return value, and the bytes it did write
    still have to be counted.
    """
    mode = "ab" if append else "wb"
    written = 0
    last_log_percent = 0
    attempt_start = time.time()

    with open(temp_path, mode) as file_handle:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if not chunk:
                continue

            file_handle.write(chunk)
            written += len(chunk)
            attempt_state["written"] = attempt_state.get("written", 0) + len(chunk)
            on_disk = start_offset + written

            elapsed = max(time.time() - attempt_start, 1e-6)
            speed_bytes_per_second = written / elapsed
            percent = int((on_disk / total_size) * 100) if total_size > 0 else 0
            eta_seconds = (
                (total_size - on_disk) / speed_bytes_per_second
                if total_size > 0 and speed_bytes_per_second > 0
                else 0
            )

            _safe_progress_emit(
                progress_callback,
                {
                    "status": "downloading",
                    "percent": percent,
                    "speed_mbps": speed_bytes_per_second / (1024 ** 2),
                    "downloaded_bytes": on_disk,
                    "total_bytes": total_size,
                    "eta_seconds": eta_seconds,
                },
            )

            if total_size > 0 and percent >= last_log_percent + 10:
                eta_str = (
                    f"{int(eta_seconds / 60)}m {int(eta_seconds % 60)}s"
                    if eta_seconds > 60
                    else f"{int(eta_seconds)}s"
                )
                log(
                    f"[{log_prefix}] {percent}% - "
                    f"{speed_bytes_per_second / (1024 ** 2):.1f} MB/s - ETA: {eta_str}"
                )
                last_log_percent = percent

    return written


def _attempt_download(
    *,
    resolved_url: str,
    temp_path: str,
    base_headers: Dict[str, str],
    offset: int,
    etag: Optional[str],
    claimed_identity: Optional[str],
    observed: Dict[str, Any],
    chunk_size: int,
    request_timeout_seconds: Optional[float],
    log: LogCallback,
    log_prefix: str,
    progress_callback: Optional[ProgressCallback],
) -> Dict[str, Any]:
    """Make one request and copy as much of the body as the server allows.

    Returns the transfer description on success. Raises `_DownloadAttemptError`
    for a retryable failure, and `transient=False` for one that cannot be fixed
    by asking again.

    `observed` is written as soon as the response headers identify the remote
    body. A connection that drops mid-stream is exactly the case where the caller
    needs that identity to park the partial for the next invocation, and it never
    reaches the return statement.
    """
    request_headers = dict(base_headers)
    if offset > 0:
        request_headers["Range"] = f"bytes={offset}-"
        # If-Range asks the server to ignore our offset and send the whole file
        # if the body changed. It is a second line of defence behind the identity
        # check below; the identity check is the one that actually decides.
        if etag and not etag.startswith("W/"):
            request_headers["If-Range"] = etag

    request_kwargs: Dict[str, Any] = {"stream": True, "headers": request_headers}
    if request_timeout_seconds is not None:
        request_kwargs["timeout"] = request_timeout_seconds

    response = requests.get(resolved_url, **request_kwargs)
    try:
        status = _int_header(getattr(response, "status_code", 0)) or 200
        headers = getattr(response, "headers", None)
        content_length = _int_header(_header_get(headers, "content-length"))
        content_range = _parse_content_range(_header_get(headers, "content-range"))

        def record(total_size: int) -> str:
            identity = _remote_identity(resolved_url, headers, total_size)
            observed["identity"] = identity
            observed["etag"] = _normalise_etag(_header_get(headers, "etag"))
            return identity

        if status == 200:
            if offset:
                log(
                    f"[{log_prefix}] Server ignored Range at offset {offset}; "
                    f"restarting from byte 0"
                )
            total_size = content_length
            _reject_undeclared_total(total_size)
            identity = record(total_size)
            if claimed_identity is not None and claimed_identity != identity:
                log(
                    f"[{log_prefix}] Remote file changed since the partial was written "
                    f"({claimed_identity} -> {identity}); restarting from byte 0"
                )
            append = False
            start_offset = 0
        elif status == 206:
            if content_range is None or content_range[0] is None:
                raise _DownloadAttemptError(
                    "server answered 206 without a usable Content-Range; restarting clean",
                )
            range_start, _range_end, range_total = content_range
            if range_start != offset:
                _remove_quietly(temp_path)
                raise _DownloadAttemptError(
                    f"server resumed at byte {range_start} but byte {offset} was requested; "
                    f"discarding the partial and restarting clean",
                )
            total_size = range_total if range_total is not None else 0
            if not total_size and content_length:
                total_size = content_length + range_start
            _reject_undeclared_total(total_size)
            identity = record(total_size)
            if claimed_identity is not None and claimed_identity != identity:
                # The 206 body starts at our offset but describes a *different*
                # file, so it cannot be appended to anything. Drop the partial and
                # let the next attempt request the whole file.
                _remove_quietly(temp_path)
                raise _DownloadAttemptError(
                    f"remote file changed since the partial was written "
                    f"({claimed_identity} -> {identity}); discarding the partial",
                )
            append = offset > 0
            start_offset = offset
        elif status == 416:
            remote_total = content_range[2] if content_range is not None else None
            local_size = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
            if remote_total is None or local_size != remote_total:
                _remove_quietly(temp_path)
                raise _DownloadAttemptError(
                    f"server rejected the resume (416) and did not confirm a complete "
                    f"local file (local={local_size}, remote={remote_total}); "
                    f"restarting clean",
                )
            identity = record(remote_total)
            if claimed_identity is not None and claimed_identity != identity:
                _remove_quietly(temp_path)
                raise _DownloadAttemptError(
                    f"remote file changed since the partial was written "
                    f"({claimed_identity} -> {identity}); discarding the partial",
                )
            log(
                f"[{log_prefix}] Server reports the local file already complete "
                f"({local_size} bytes); validating instead of re-downloading"
            )
            return {
                "total_size": remote_total,
                "identity": identity,
                "etag": observed["etag"],
                "fetched_bytes": 0,
                "resumed_bytes": local_size,
                "appended": True,
                "already_complete": True,
            }
        elif status in TRANSIENT_STATUSES or status >= 500:
            raise _DownloadAttemptError(f"HTTP {status} from the model host", transient=True)
        else:
            raise _DownloadAttemptError(f"HTTP {status} from the model host", transient=False)

        if total_size:
            log(f"[{log_prefix}] Size: {_format_size(total_size)}")
        else:
            log(f"[{log_prefix}] Size: Unknown")
        if append:
            log(f"[{log_prefix}] Resuming at byte {start_offset}")

        # The total is known and not one body byte has been written yet, so this is
        # the only moment at which the cost of a full volume is still zero.
        _ensure_free_space(temp_path, total_size - start_offset)

        written = _stream_to_file(
            response,
            temp_path,
            append=append,
            start_offset=start_offset,
            total_size=total_size,
            chunk_size=chunk_size,
            attempt_state=observed,
            log=log,
            log_prefix=log_prefix,
            progress_callback=progress_callback,
        )
    finally:
        _close_response(response)

    on_disk = os.path.getsize(temp_path)
    # Unconditional now. `_reject_undeclared_total` has already guaranteed
    # `total_size` is positive by the time control reaches here, so the
    # `if total_size and ...` guard could only ever hide a comparison that needed
    # running — which is how a 60202-byte body was published for a
    # 7000000-byte model with no error anywhere.
    if on_disk != total_size:
        if on_disk > total_size:
            _remove_quietly(temp_path)
            raise _DownloadAttemptError(
                f"received {on_disk} bytes for a {total_size} byte file; discarding the partial",
            )
        raise _DownloadAttemptError(
            f"connection ended early: {on_disk} of {total_size} bytes on disk",
        )

    return {
        "total_size": total_size,
        "identity": identity,
        "etag": observed["etag"],
        "fetched_bytes": written,
        "resumed_bytes": start_offset,
        "appended": append,
        "already_complete": False,
    }


def _transfer_with_resume(
    *,
    resolved_url: str,
    full_path: str,
    temp_path: str,
    base_headers: Dict[str, str],
    claimed_identity: Optional[str],
    chunk_size: int,
    request_timeout_seconds: Optional[float],
    max_attempts: int,
    retry_backoff_base_seconds: float,
    retry_backoff_max_seconds: float,
    log: LogCallback,
    log_prefix: str,
    progress_callback: Optional[ProgressCallback],
) -> Dict[str, Any]:
    """Fetch the body into `temp_path`, resuming a partial and retrying.

    The caller holds the per-path lock for the whole of this, so a resume is not
    a window in which a second downloader can start. On giving up the partial is
    parked in the resume slot, which is what lets the *next* invocation of
    download_model_to_path continue rather than start over.
    """
    attempts_allowed = max(1, int(max_attempts))
    observed: Dict[str, Any] = {}
    etag: Optional[str] = None
    total_written = 0
    first_offset = 0
    identity = claimed_identity
    last_error = "no attempt was made"
    last_exc: Optional[BaseException] = None
    attempt = 0

    while attempt < attempts_allowed:
        attempt += 1
        offset = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
        if attempt == 1:
            # What this call found on disk. A resume that happens on attempt 2 or
            # 3 after a fresh 200 reused nothing and must not report as resumed.
            first_offset = offset
        if attempt > 1:
            delay = _backoff_delay(attempt - 1, retry_backoff_base_seconds, retry_backoff_max_seconds)
            log(
                f"[{log_prefix}] Attempt {attempt}/{attempts_allowed} in {delay:.1f}s "
                f"from byte {offset}: {last_error}"
            )
            _sleep(delay)

        observed.clear()
        try:
            outcome = _attempt_download(
                resolved_url=resolved_url,
                temp_path=temp_path,
                base_headers=base_headers,
                offset=offset,
                etag=etag,
                claimed_identity=identity,
                observed=observed,
                chunk_size=chunk_size,
                request_timeout_seconds=request_timeout_seconds,
                log=log,
                log_prefix=log_prefix,
                progress_callback=progress_callback,
            )
        except Exception as exc:  # transport, HTTP status, protocol violation
            # Headers may already have named the remote body even though the body
            # never arrived. That identity is what makes the partial resumable,
            # and the ETag lets the retry carry If-Range.
            identity = observed.get("identity", identity)
            etag = observed.get("etag") or etag
            total_written += observed.get("written", 0)
            if not _is_transient_error(exc):
                if _is_out_of_space(exc):
                    # Not parked. See OUT_OF_SPACE_ERRNOS: parking succeeds here
                    # because `rename(2)` needs no space, which leaves a multi-GB
                    # partial on a volume that cannot hold the next attempt either.
                    # The bytes on disk are dropped rather than left behind, and
                    # the message says why — the operator has to free space either
                    # way, and a parked partial is what makes the next attempt look
                    # like it is resuming when it is hitting the same wall.
                    _remove_quietly(temp_path)
                    raise _DownloadAttemptError(
                        f"{exc} — the partial was not kept: there is no room for it "
                        f"or for the next attempt, so resuming would hit the same wall",
                        transient=False,
                    ) from exc
                kept = _persist_partial(full_path, temp_path, identity)
                raise _DownloadAttemptError(
                    f"{exc}" + (f" ({kept} bytes kept at offset {kept})" if kept else ""),
                    transient=False,
                ) from exc
            last_error = str(exc)
            last_exc = exc
            log(f"[{log_prefix}] Attempt {attempt}/{attempts_allowed} failed: {last_error}")
            continue

        # The response that told us the offset is also the one that carries the
        # ETag, so it is only known after the first attempt that got headers.
        etag = outcome.get("etag") or etag
        identity = outcome["identity"]
        total_written += outcome["fetched_bytes"]

        # A transfer that restarted from byte 0 threw away whatever the earlier
        # attempts wrote, so nothing was resumed and only the last attempt counts.
        if outcome.get("appended"):
            outcome["fetched_bytes"] = total_written
            outcome["resumed_bytes"] = first_offset
        else:
            outcome["fetched_bytes"] = outcome["fetched_bytes"]
            outcome["resumed_bytes"] = 0

        outcome["attempts"] = attempt
        return outcome

    if last_exc is not None and _is_out_of_space(last_exc):
        # Same reasoning as the per-attempt branch above: a partial parked on a
        # volume with no room is a multi-GB file that makes the next attempt look
        # like a resume when it is hitting the identical wall.
        _remove_quietly(temp_path)
        raise _DownloadAttemptError(
            f"{last_error} — the partial was not kept: the volume is out of space, "
            f"so there is nothing to resume into",
            transient=False,
        )

    kept = _persist_partial(full_path, temp_path, identity)
    if kept:
        detail = f"rerun the download to resume from byte {kept}"
    else:
        detail = "no bytes were saved to resume from"
    raise _DownloadAttemptError(
        f"{last_error} — gave up after {attempts_allowed} attempt(s); {detail}"
    )


def _append_query_param(url: str, key: str, value: str) -> str:
    """Append a query parameter only when the key does not already exist."""
    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)

    if any(existing_key == key for existing_key, _ in query_items):
        return url

    query_items.append((key, value))
    return urlunparse(parsed._replace(query=urlencode(query_items)))


def build_authenticated_download_request(
    url: str,
    token: Optional[str] = None,
    *,
    hf_token: Optional[str] = None,
    civitai_token: Optional[str] = None,
) -> Tuple[str, Dict[str, str], Dict[str, bool]]:
    """Build a download URL and headers with provider token resolution rules."""
    headers: Dict[str, str] = {}
    resolved_url = url

    if not url:
        raise ValueError("download_url is empty or None — model may need to be re-added from CivitAI")

    resolved_hf_token = token if token and token.startswith("hf_") else hf_token
    resolved_civitai_token = token if token and not token.startswith("hf_") else civitai_token

    used_hf_token = False
    used_civitai_token = False

    hostname = (urlparse(url).hostname or "").lower()
    is_huggingface = hostname == "huggingface.co" or hostname.endswith(".huggingface.co")
    is_civitai = hostname in {"civitai.com", "civitai.red"} or hostname.endswith(".civitai.com")

    if is_huggingface and resolved_hf_token:
        headers["Authorization"] = f"Bearer {resolved_hf_token}"
        used_hf_token = True
    elif is_civitai and resolved_civitai_token:
        resolved_url = _append_query_param(url, "token", resolved_civitai_token)
        used_civitai_token = True

    auth_info = {
        "used_hf_token": used_hf_token,
        "used_civitai_token": used_civitai_token,
    }
    return resolved_url, headers, auth_info


def _safe_progress_emit(callback: Optional[ProgressCallback], payload: Dict[str, Any]) -> None:
    if not callback:
        return

    try:
        callback(payload)
    except Exception:
        # Progress updates must never break download flow.
        return


def _default_log(message: str) -> None:
    logger.info(message)


def download_model_to_path(**kwargs: Any) -> Dict[str, Any]:
    """Serialise downloads of the same destination, then perform the download.

    Keyword-only by design so this wrapper can forward everything without
    repeating the long parameter list. See exclusive_path_lock for why the
    serialisation is load-bearing rather than merely tidy.
    """
    full_path = kwargs.get("full_path")
    if not full_path:
        raise ValueError("full_path is required")
    with exclusive_path_lock(full_path) as held:
        result = _download_model_to_path_unlocked(**kwargs)
    # A published model has nothing left to resume, so its lock is dead weight
    # that every validator would go on counting as a partial download. A failed
    # or raised attempt keeps its lock, so the retry flocks the same inode.
    if isinstance(result, dict) and result.get("status") == "success":
        held.release_file()
    return result


def _download_model_to_path_unlocked(
    *,
    url: str,
    full_path: str,
    path: Optional[str] = None,
    token: Optional[str] = None,
    hf_token: Optional[str] = None,
    civitai_token: Optional[str] = None,
    preview_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    log: Optional[LogCallback] = None,
    log_prefix: str = "Download",
    progress_callback: Optional[ProgressCallback] = None,
    validation_unknown_header_log_prefix: Optional[str] = None,
    chunk_size: int = 8 * 1024 * 1024,  # 8 MB — reduces Python iteration overhead for large files
    preview_timeout_seconds: float = 30.0,
    # A real default, not None. `None` meant "omit the timeout kwarg entirely",
    # and `requests` then blocks forever on a peer that accepts the connection
    # and goes quiet. Every current caller passes a value so the unsafe branch
    # was latent rather than live — but the function's entire job is multi-GB
    # transfers, and a default that can hang forever is the wrong default for the
    # next caller. 30 minutes is generous for a single chunked read and still
    # bounds a stuck container.
    request_timeout_seconds: Optional[float] = 1800.0,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_backoff_base_seconds: float = RETRY_BACKOFF_BASE_SECONDS,
    retry_backoff_max_seconds: float = RETRY_BACKOFF_MAX_SECONDS,
) -> Dict[str, Any]:
    """Download a model file to disk with strict validation and atomic rename.

    Callers should use download_model_to_path, which holds the per-path lock for
    the whole transfer, retries included.
    """
    logger = log or _default_log
    label = path or os.path.basename(full_path)
    temp_path = _unique_temp_path(full_path)

    if not url:
        raise ValueError("Cannot download model because download_url is missing or empty")

    resolved_url, headers, auth_info = build_authenticated_download_request(
        url,
        token,
        hf_token=hf_token,
        civitai_token=civitai_token,
    )

    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    logger(f"[{log_prefix}] Starting: {label}")
    logger(f"[{log_prefix}] Using temp file: {os.path.basename(temp_path)}")

    if auth_info["used_hf_token"]:
        logger(f"[{log_prefix}] Using HuggingFace token")
    if auth_info["used_civitai_token"]:
        logger(f"[{log_prefix}] Using CivitAI token")

    # Claimed under the per-path lock, so this is the only attempt in flight for
    # this destination and any slot on disk was abandoned by an earlier one.
    claimed_identity, claimed_bytes = _claim_resume_slot(full_path, temp_path)
    if claimed_bytes:
        logger(
            f"[{log_prefix}] Found a partial download of {_format_size(claimed_bytes)}; "
            f"resuming from byte {claimed_bytes}"
        )

    _safe_progress_emit(
        progress_callback,
        {"status": "starting", "percent": 0, "resumed_bytes": claimed_bytes},
    )

    try:
        transfer_started = time.time()
        transfer = _transfer_with_resume(
            resolved_url=resolved_url,
            full_path=full_path,
            temp_path=temp_path,
            base_headers=headers,
            claimed_identity=claimed_identity,
            chunk_size=chunk_size,
            request_timeout_seconds=request_timeout_seconds,
            max_attempts=max_attempts,
            retry_backoff_base_seconds=retry_backoff_base_seconds,
            retry_backoff_max_seconds=retry_backoff_max_seconds,
            log=logger,
            log_prefix=log_prefix,
            progress_callback=progress_callback,
        )

        total_size = int(transfer.get("total_size") or 0)
        fetched = int(transfer.get("fetched_bytes") or 0)
        resumed = int(transfer.get("resumed_bytes") or 0)
        on_disk = os.path.getsize(temp_path)

        # The publish gate, and deliberately independent of the one in
        # `_attempt_download`. `total_size == 0` means "the remote never said how
        # big this is", and both size checks in the pipeline are conditioned on a
        # non-zero total — so with an unknown total, nothing downstream compares
        # the bytes against anything. `_attempt_download` already refuses that
        # case; this refuses it again at the only place where the consequence
        # (an `os.replace` into the live model tree) actually happens, so a future
        # path that reaches `os.replace` with an unverified length cannot do it
        # just because it did not inherit the inner guard.
        if total_size <= 0:
            _remove_quietly(temp_path)
            for _identity, slot in _resume_slots(full_path):
                _remove_quietly(slot)
            raise ValueError(
                f"Refusing to publish {label}: the server never declared its total size, "
                f"so the {on_disk} bytes received could not be verified against it."
            )
        if on_disk != total_size:
            _remove_quietly(temp_path)
            for _identity, slot in _resume_slots(full_path):
                _remove_quietly(slot)
            raise ValueError(
                f"Refusing to publish {label}: {on_disk} bytes on disk against a declared "
                f"total of {total_size}."
            )

        elapsed = max(time.time() - transfer_started, 1e-6)
        speed_mbps = (fetched / (1024 ** 2)) / elapsed
        logger(f"[{log_prefix}] Download complete (temp file)")
        logger(
            f"[{log_prefix}] Size: {on_disk / (1024 ** 2):.1f} MB "
            f"in {elapsed:.1f}s ({speed_mbps:.1f} MB/s)"
        )

        # Validation is given the whole file and the whole expected length, never
        # the appended chunk: a partial safetensors header read is not a check
        # that the model is intact.
        validation = validate_downloaded_file(
            temp_path,
            total_size,
            unknown_header_log_prefix=validation_unknown_header_log_prefix,
        )

        if not validation.get("valid"):
            for err in validation.get("errors", [validation.get("error", "Validation failed")]):
                logger(f"[{log_prefix}] Validation error: {err}")

            if validation.get("indeterminate"):
                # The file could not be READ (EIO, ENOMEM, a gcsfuse stall) —
                # that is not a verdict on it. `provider_core/validation.py`
                # states the contract this was breaking: "A caller that can act
                # destructively on `invalid` MUST check `indeterminate` first.
                # Deleting on an indeterminate result is never correct." Four
                # callers honoured it; this one removed the temp file AND every
                # resume slot, so a single transient read fault on a 7 GB
                # checkpoint reset a transfer that `_transfer_with_resume` exists
                # to protect back to byte 0 — unattended, on a mount where EIO is
                # routine. There is no way to recover a multi-GB download deleted
                # on a guess.
                #
                # The partial is PARKED rather than just left alone, because the
                # outer `except Exception` sweeps this attempt's temp file on any
                # raise — so "do not delete" has to mean "re-park it where the
                # next attempt will find it", not "skip two removes".
                kept = _persist_partial(full_path, temp_path, transfer.get("identity"))
                raise ValueError(
                    f"Validation could not read the downloaded file: "
                    f"{validation.get('error', 'unknown error')} "
                    f"({kept} bytes parked for the next attempt; the model is not "
                    f"known to be bad)"
                )

            # Read succeeded and the bytes are wrong, so there is nothing worth
            # resuming: a rerun must start from byte 0.
            _remove_quietly(temp_path)
            for _identity, slot in _resume_slots(full_path):
                _remove_quietly(slot)
            raise ValueError(f"Validation failed: {validation.get('error', 'unknown validation error')}")

        detected_format = validation.get("format", "unknown")
        actual_size = int(validation.get("size", on_disk))
        logger(f"[{log_prefix}] Validation passed: {detected_format}")

        # `_replace_or_move` handles same-filesystem atomic rename and cross-device
        # copies (e.g. fast local SSD scratch -> Google Drive FUSE) atomically.
        _replace_or_move(temp_path, full_path)
        logger(f"[{log_prefix}] Moved to final path: {label}")

        # Nothing is left to resume now that the model is published.
        for _identity, slot in _resume_slots(full_path):
            _remove_quietly(slot)

        metadata_saved = False
        if metadata:
            metadata_path = os.path.splitext(full_path)[0] + ".json"
            with open(metadata_path, "w", encoding="utf-8") as metadata_handle:
                json.dump(metadata, metadata_handle)
            metadata_saved = True

        preview_saved = False
        if preview_url:
            try:
                preview_response = requests.get(preview_url, timeout=preview_timeout_seconds)
                if preview_response.status_code == 200:
                    preview_path = os.path.splitext(full_path)[0] + ".preview.png"
                    with open(preview_path, "wb") as preview_handle:
                        preview_handle.write(preview_response.content)
                    preview_saved = True
                    logger(f"[{log_prefix}] Preview saved")
            except Exception as preview_exc:
                logger(f"[{log_prefix}] Preview failed: {preview_exc}")

        success_payload = {
            "status": "success",
            "path": label,
            "size": actual_size,
            "speed_mbps": round(speed_mbps, 1),
            "format": detected_format,
            "validated": True,
            "downloaded_bytes": on_disk,
            "total_size_bytes": total_size,
            "resumed": resumed > 0,
            "resumed_bytes": resumed,
            "fetched_bytes": fetched,
            "attempts": int(transfer.get("attempts") or 1),
            "metadata_saved": metadata_saved,
            "preview_saved": preview_saved,
        }

        _safe_progress_emit(
            progress_callback,
            {
                "status": "success",
                "percent": 100,
                "speed_mbps": round(speed_mbps, 1),
                "downloaded_bytes": on_disk,
                "total_bytes": total_size,
            },
        )

        return success_payload

    except Exception as exc:
        # A partial that _transfer_with_resume could resume from has already been
        # moved into the resume slot; this only sweeps the attempt temp file, which
        # is a no-op in that case.
        _remove_quietly(temp_path)

        error_message = str(exc)
        logger(f"[{log_prefix}] Error: {error_message}")
        _safe_progress_emit(
            progress_callback,
            {
                "status": "error",
                "percent": 0,
                "message": error_message,
            },
        )
        return {"status": "error", "message": error_message, }


# The two shapes of pipeline temp file, as *structure* rather than as a prefix.
#
# `_unique_temp_path`  -> f"{full_path}.{os.getpid()}.{uuid.uuid4().hex[:8]}.downloading"
# `_resume_slot_path`  -> f"{full_path}{RESUME_SLOT_MARKER}{identity}.downloading"
#
# These are the patterns, not a guess at them, and they are deliberately defined
# next to the two functions above so a change to a name breaks this rather than
# silently making the sweeper match nothing.
_ATTEMPT_TEMP_RE = re.compile(r"^\d+\.[0-9a-f]{8}$")
_RESUME_TEMP_RE = re.compile(rf"^{re.escape(RESUME_SLOT_MARKER.lstrip('.'))}[0-9a-zA-Z_-]+$")


def _is_temp_for(basename: str, entry: str) -> bool:
    """Is `entry` a pipeline temp file belonging to the model named `basename`?

    This was `entry.startswith(basename + ".") and entry.endswith(".downloading")`,
    which is a prefix test, and a prefix test over a namespace that contains other
    legal model names is not a containment test. For `foo.safetensors` it also
    swept `foo.safetensors.fp16.safetensors.999.00112233.downloading` — and
    `is_model_file("foo.safetensors.fp16.safetensors")` is `True`, so that is a
    perfectly legal filename belonging to a *different* model.

    That matters more than it looks, because this function is the authorisation
    gate on the delete routes. `remote_agent/server.py`, both Modal apps and
    `beam_app.py` all do:

        if not os.path.exists(full_path) and not list(pending_download_paths(full_path)):
            return 404
        ... remove it ...

    So a false positive here is not a stray entry in a listing — it turns "this
    model does not exist" into "delete what we found", and what we found belongs to
    somebody else's in-flight download.

    Matching the two real shapes fixes that and costs nothing: a name that is not
    `<pid>.<hex>` or `resume.<identity>` after the model name is not ours.
    """
    if not entry.endswith(DOWNLOADING_SUFFIX):
        return False
    prefix = basename + "."
    if not entry.startswith(prefix):
        return False
    remainder = entry[len(prefix): -len(DOWNLOADING_SUFFIX)]
    return bool(_ATTEMPT_TEMP_RE.match(remainder) or _RESUME_TEMP_RE.match(remainder))


def pending_download_paths(full_path: str) -> Iterator[str]:
    """Yield the temp files of every in-flight or abandoned attempt at `full_path`.

    `_unique_temp_path` names each attempt `<path>.<pid>.<hex>.downloading`, so a
    single fixed `.downloading` name no longer identifies "the" partial file.
    Deleting a model used to probe the old deterministic name and therefore
    never removed a partial download, leaving multi-GB files on the volume.

    Resume slots (`<path>.resume.<identity>.downloading`) match this pattern too,
    which is what makes `FileStorage.delete_file` remove a parked partial along
    with the model it belongs to instead of stranding it on the volume.

    Only names of exactly those two shapes are yielded — see `_is_temp_for` for
    why that is an authorisation decision and not a tidiness one.
    """
    directory = os.path.dirname(full_path) or "."
    basename = os.path.basename(full_path)
    try:
        entries = os.listdir(directory)
    except OSError:
        return
    for entry in entries:
        if _is_temp_for(basename, entry):
            yield os.path.join(directory, entry)


def pipeline_artifacts(full_path: str) -> Iterator[str]:
    """Every pipeline-owned file belonging to `full_path`, lock included.

    `pending_download_paths` deliberately does not name the lock: it is the
    "is a transfer of this path in flight?" probe, and a `.lock` answers that
    question wrongly — `exclusive_path_lock` creates one before it blocks, so a
    lock exists for a *waiting* downloader as much as for a running one, and
    treating it as a pending transfer would make `delete-model` claim a model
    exists when only an abandoned lock does.

    It is the operator-initiated delete routes that want all three, and only
    they: there the user has asked for this model to go, so a lock beside it
    belongs to it. Validation deliberately must not do this — a lock is 0 bytes,
    reconciliation runs with `delete_invalid=True`, and unlinking one that is
    held takes the model's `.json` and `.preview.png` with it, because
    `os.path.splitext("x.safetensors.lock")[0]` is `"x.safetensors"`.
    """
    yield f"{full_path}{LOCK_SUFFIX}"
    yield from pending_download_paths(full_path)
