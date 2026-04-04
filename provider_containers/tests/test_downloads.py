import json
import os
from urllib.parse import parse_qs, urlparse

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
