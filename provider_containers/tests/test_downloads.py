import json
import os
import threading
import time
from urllib.parse import parse_qs, urlparse

import pytest

from provider_core import downloads


class _FakeResponse:
    def __init__(self, content: bytes, *, status_code: int = 200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int):
        for idx in range(0, len(self.content), chunk_size):
            yield self.content[idx: idx + chunk_size]


def test_build_authenticated_download_request_uses_huggingface_header():
    url, headers, auth = downloads.build_authenticated_download_request(
        "https://huggingface.co/org/model/resolve/main/file.safetensors",
        token="hf_secret",
        hf_token="hf_fallback",
        civitai_token="",
    )

    assert url == "https://huggingface.co/org/model/resolve/main/file.safetensors"
    assert headers == {"Authorization": "Bearer hf_secret"}
    assert auth["used_hf_token"] is True
    assert auth["used_civitai_token"] is False


def test_build_authenticated_download_request_appends_civitai_token_once():
    url, headers, auth = downloads.build_authenticated_download_request(
        "https://civitai.com/api/download/models/123",
        token="civitai_secret",
        hf_token="",
        civitai_token="ignored",
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert query["token"] == ["civitai_secret"]
    assert headers == {}
    assert auth["used_hf_token"] is False
    assert auth["used_civitai_token"] is True

    url_with_existing, _, _ = downloads.build_authenticated_download_request(
        "https://civitai.com/api/download/models/123?token=already_here",
        token="civitai_secret",
        hf_token="",
        civitai_token="ignored",
    )
    existing_query = parse_qs(urlparse(url_with_existing).query)
    assert existing_query["token"] == ["already_here"]


def test_download_model_to_path_writes_metadata_and_preview(tmp_path, monkeypatch):
    model_bytes = b"PK" + (b"x" * (16 * 1024))
    preview_bytes = b"preview-png"

    def fake_get(url, **kwargs):
        if "preview" in url:
            return _FakeResponse(preview_bytes, status_code=200)
        return _FakeResponse(
            model_bytes,
            status_code=200,
            headers={"content-length": str(len(model_bytes))},
        )

    monkeypatch.setattr(downloads.requests, "get", fake_get)
    monkeypatch.setattr(
        downloads,
        "validate_downloaded_file",
        lambda path, total_size, unknown_header_log_prefix=None: {
            "valid": True,
            "format": "zip/ckpt",
            "size": os.path.getsize(path),
        },
    )

    progress_statuses = []

    result = downloads.download_model_to_path(
        url="https://example.com/model.ckpt",
        full_path=str(tmp_path / "models" / "model.ckpt"),
        path="models/model.ckpt",
        preview_url="https://example.com/preview.png",
        metadata={"model_id": 123},
        progress_callback=lambda payload: progress_statuses.append(payload["status"]),
        log=lambda _msg: None,
    )

    assert result["status"] == "success"
    assert result["validated"] is True
    assert result["preview_saved"] is True
    assert result["metadata_saved"] is True

    final_file = tmp_path / "models" / "model.ckpt"
    metadata_file = tmp_path / "models" / "model.json"
    preview_file = tmp_path / "models" / "model.preview.png"
    temp_file = tmp_path / "models" / "model.ckpt.downloading"

    assert final_file.exists()
    assert final_file.read_bytes() == model_bytes
    assert metadata_file.exists()
    assert json.loads(metadata_file.read_text(encoding="utf-8")) == {"model_id": 123}
    assert preview_file.exists()
    assert preview_file.read_bytes() == preview_bytes
    assert not temp_file.exists()
    assert progress_statuses[0] == "starting"
    assert "downloading" in progress_statuses
    assert progress_statuses[-1] == "success"


def test_download_model_to_path_cleans_up_temp_file_on_validation_error(tmp_path, monkeypatch):
    model_bytes = b"PK" + (b"x" * (12 * 1024))

    monkeypatch.setattr(
        downloads.requests,
        "get",
        lambda *_args, **_kwargs: _FakeResponse(
            model_bytes,
            status_code=200,
            headers={"content-length": str(len(model_bytes))},
        ),
    )
    monkeypatch.setattr(
        downloads,
        "validate_downloaded_file",
        lambda path, total_size, unknown_header_log_prefix=None: {
            "valid": False,
            "error": "checksum mismatch",
            "errors": ["checksum mismatch"],
        },
    )

    result = downloads.download_model_to_path(
        url="https://example.com/bad-model.ckpt",
        full_path=str(tmp_path / "models" / "bad-model.ckpt"),
        path="models/bad-model.ckpt",
        log=lambda _msg: None,
    )

    assert result["status"] == "error"
    assert "Validation failed" in result["message"]
    assert not (tmp_path / "models" / "bad-model.ckpt").exists()
    assert not (tmp_path / "models" / "bad-model.ckpt.downloading").exists()


# ── Concurrency safety ────────────────────────────────────────────────────────
#
# Two concurrent downloads of one destination used to share a deterministic
# `<path>.downloading` temp file. The second `open(..., "wb")` truncated the
# first's partial data and both handles then wrote at their own offsets into
# the same inode. Both passed validation — the size is the full size either
# way, and whichever attempt wrote offset 0 put a valid magic header there —
# and the first to `os.replace` published a silently interleaved file.

def _payload(tag: bytes, size: int = 24 * 1024) -> bytes:
    """A file that starts with a valid safetensors/json magic header."""
    body = tag * size
    return body[:size]


class _SlowResponse:
    """Streams `content` in chunks, yielding control so threads interleave."""

    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.headers = {"content-length": str(len(content))}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size: int):
        for idx in range(0, len(self.content), chunk_size):
            yield self.content[idx: idx + chunk_size]
            time.sleep(0.001)


def test_concurrent_downloads_of_one_path_do_not_interleave(tmp_path, monkeypatch):
    dest = tmp_path / "model.ckpt"
    payloads = [_payload(b"A"), _payload(b"B")]

    responses = iter([_SlowResponse(p) for p in payloads])

    def fake_get(url, **kwargs):
        return next(responses)

    monkeypatch.setattr(downloads.requests, "get", fake_get)

    results = []
    lock = threading.Lock()

    def worker():
        result = downloads.download_model_to_path(
            url="https://example.test/model.ckpt",
            full_path=str(dest),
        )
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert all(r["status"] == "success" for r in results), results

    final = dest.read_bytes()
    # The published file must be exactly one payload, byte for byte. An
    # interleaved write would be some other length or a mixture of both tags.
    assert final in payloads, (
        f"published file is an interleaved mixture, not one payload "
        f"(len={len(final)}, expected one of {[len(p) for p in payloads]})"
    )


def test_each_attempt_uses_a_distinct_temp_file(tmp_path, monkeypatch):
    """Even without the lock, two attempts must never share a temp file."""
    dest = tmp_path / "model.ckpt"
    seen = []

    real_replace = os.replace

    def spy_replace(src, dst):
        seen.append(os.path.basename(src))
        return real_replace(src, dst)

    monkeypatch.setattr(downloads.os, "replace", spy_replace)
    monkeypatch.setattr(
        downloads.requests, "get", lambda url, **kw: _SlowResponse(_payload(b"C"))
    )

    for _ in range(2):
        downloads.download_model_to_path(
            url="https://example.test/model.ckpt", full_path=str(dest)
        )

    assert len(seen) == 2, seen
    assert seen[0] != seen[1], f"both attempts reused temp file {seen[0]}"
    assert all(name.endswith(".downloading") for name in seen), seen


def test_failed_download_leaves_no_temp_residue(tmp_path, monkeypatch):
    """The per-attempt temp file is cleaned up on failure."""
    dest = tmp_path / "model.ckpt"

    class _Boom:
        headers = {"content-length": "999999"}
        status_code = 200

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield _payload(b"D")[:1024]
            raise OSError("connection reset")

    monkeypatch.setattr(downloads.requests, "get", lambda url, **kw: _Boom())

    result = downloads.download_model_to_path(
        url="https://example.test/model.ckpt", full_path=str(dest)
    )

    assert result["status"] == "error"
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".downloading")]
    assert leftovers == [], f"temp files leaked: {leftovers}"


def test_lock_is_released_after_an_exception(tmp_path, monkeypatch):
    """A crash inside the locked region must not wedge the path forever."""
    dest = tmp_path / "model.ckpt"
    monkeypatch.setattr(
        downloads, "_download_model_to_path_unlocked",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError):
        downloads.download_model_to_path(url="u", full_path=str(dest))

    # A second call must be able to take the lock immediately.
    monkeypatch.undo()
    monkeypatch.setattr(
        downloads.requests, "get", lambda url, **kw: _SlowResponse(_payload(b"E"))
    )
    result = downloads.download_model_to_path(
        url="https://example.test/model.ckpt", full_path=str(dest)
    )
    assert result["status"] == "success"
