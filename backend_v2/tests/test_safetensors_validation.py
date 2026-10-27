"""Tests for validate_downloaded_file focusing on safetensors and format detection."""

import json
import struct
from pathlib import Path

from tests.repo_paths import require_repo_root

ROOT = require_repo_root("remote_agent/provider_core/")
import sys
if str(ROOT / "remote_agent") not in sys.path:
    sys.path.insert(0, str(ROOT / "remote_agent"))

from provider_core.validation import validate_downloaded_file


def _create_safetensors_file(path: Path, header_dict: dict, data_bytes: bytes = b"\x00" * 1024):
    header_json = json.dumps(header_dict).encode("utf-8")
    header_len = len(header_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", header_len))
        f.write(header_json)
        f.write(data_bytes)


def test_valid_safetensors_passes_validation(tmp_path):
    sf_path = tmp_path / "models" / "unet" / "flux2_klein.safetensors"
    header = {"__metadata__": {"format": "pt"}, "model.weight": {"dtype": "F16", "shape": [10, 10], "data_offsets": [0, 200]}}
    # Pad to exceed 10KB
    _create_safetensors_file(sf_path, header, data_bytes=b"\x00" * 20000)

    result = validate_downloaded_file(str(sf_path))
    assert result["valid"] is True, result
    assert result["format"] == "safetensors"
    assert result["indeterminate"] is False


def test_valid_safetensors_temp_downloading_file_passes(tmp_path):
    temp_path = tmp_path / "models" / "loras" / "muscle_slider.safetensors.77bcb4c1.downloading"
    header = {"weight": {"dtype": "F16", "shape": [5, 5], "data_offsets": [0, 50]}}
    _create_safetensors_file(temp_path, header, data_bytes=b"\x00" * 20000)

    result = validate_downloaded_file(str(temp_path))
    assert result["valid"] is True, result
    assert result["format"] == "safetensors"
    assert result["indeterminate"] is False


def test_small_embedding_safetensors_passes(tmp_path):
    emb_path = tmp_path / "models" / "embeddings" / "_lazy_embeddings_lazyneg.safetensors"
    header = {"emb_params": {"dtype": "F16", "shape": [1, 768], "data_offsets": [0, 1536]}}
    # 1.5 KB embedding (under normal 10KB MIN_MODEL_SIZE, but valid for embeddings)
    _create_safetensors_file(emb_path, header, data_bytes=b"\x00" * 1536)

    result = validate_downloaded_file(str(emb_path))
    assert result["valid"] is True, result
    assert result["format"] == "safetensors"


def test_corrupted_safetensors_fails(tmp_path):
    bad_sf = tmp_path / "models" / "unet" / "bad.safetensors"
    bad_sf.parent.mkdir(parents=True, exist_ok=True)
    with open(bad_sf, "wb") as f:
        f.write(struct.pack("<Q", 50))
        f.write(b"NOT A VALID JSON STRING PADDED PADDED PADDED PADDED PADDED")
        f.write(b"\x00" * 20000)

    result = validate_downloaded_file(str(bad_sf))
    assert result["valid"] is False
    assert any("Safetensors corrupted" in err for err in result["errors"])


def test_html_error_response_fails(tmp_path):
    html_file = tmp_path / "models" / "unet" / "model.safetensors"
    html_file.parent.mkdir(parents=True, exist_ok=True)
    html_file.write_text("<!DOCTYPE html><html><body>Error 403 Forbidden</body></html>" + " " * 20000)

    result = validate_downloaded_file(str(html_file))
    assert result["valid"] is False
    assert any("Downloaded HTML instead of model" in err for err in result["errors"])


def test_json_error_response_fails(tmp_path):
    json_err_file = tmp_path / "models" / "unet" / "model.safetensors"
    json_err_file.parent.mkdir(parents=True, exist_ok=True)
    json_err_file.write_text(json.dumps({"error": "Unauthorized", "detail": "Invalid token"}) + " " * 20000)

    result = validate_downloaded_file(str(json_err_file))
    assert result["valid"] is False
    assert any("Downloaded JSON instead of model" in err or "JSON error envelope" in err for err in result["errors"])


def test_unrecognised_header_fails(tmp_path):
    unk_file = tmp_path / "models" / "unet" / "model.bin"
    unk_file.parent.mkdir(parents=True, exist_ok=True)
    with open(unk_file, "wb") as f:
        f.write(b"\xde\xad\xbe\xef\xca\xfe\xba\xbe" + b"\x00" * 20000)

    result = validate_downloaded_file(str(unk_file))
    assert result["valid"] is False
    assert any("Unrecognised file header" in err for err in result["errors"])
