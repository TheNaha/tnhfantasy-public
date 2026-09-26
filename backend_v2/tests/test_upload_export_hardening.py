"""Upload/export hardening tests.

Covers the bounded validation helpers in core/upload_validation.py, the shape of
the error payloads they produce, and the upload/export routes in
api/routes/files.py (plus the world_vault upload endpoints that share them).
"""
import base64
import io
import json
import struct
import zipfile
import zlib

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api.routes.files as files_module
from core.exceptions import UploadValidationError, ValidationError
from core.upload_validation import (
    decode_base64_bounded,
    human_size,
    inspect_image,
    read_upload_bounded,
    read_upload_file_bounded,
    require_batch_size,
    require_declared_size,
    require_extension,
    sanitize_filename,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def image_bytes(width: int = 2, height: int = 2, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buf, format=fmt)
    return buf.getvalue()


PNG_BYTES = image_bytes()
JPEG_BYTES = image_bytes(fmt="JPEG")


def png_claiming_dimensions(width: int, height: int) -> bytes:
    """A structurally valid PNG header that claims the given size.

    Pillow reads the dimensions from IHDR, which is all the budget check needs -
    no pixel data is allocated, so huge sizes are cheap to test.
    """

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 8))
        + chunk(b"IEND", b"")
    )


class FakeUpload:
    """Minimal stand-in for starlette's UploadFile."""

    def __init__(self, data: bytes = b"", size: int | None = None, delay: float = 0.0):
        self.data = data
        self.size = len(data) if size is None else size
        self.filename = "upload.png"
        self.delay = delay
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        import asyncio

        if self.delay:
            await asyncio.sleep(self.delay)
        if self._pos >= len(self.data):
            return b""
        chunk = self.data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    @property
    def file(self):
        return io.BytesIO(self.data)


@pytest.fixture(name="sandbox_dirs")
def sandbox_dirs_fixture(tmp_path, monkeypatch):
    """Point the file routes at a temp output/input tree."""
    output_dir = tmp_path / "output"
    input_dir = tmp_path / "input"
    output_dir.mkdir()
    input_dir.mkdir()
    monkeypatch.setattr(files_module, "OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(files_module, "INPUT_DIR", str(input_dir))
    return {"output": output_dir, "input": input_dir}


# ---------------------------------------------------------------------------
# sanitize_filename / path handling
# ---------------------------------------------------------------------------

class TestSanitizeFilename:
    def test_plain_name_unchanged(self):
        assert sanitize_filename("photo.png") == "photo.png"

    def test_strips_posix_traversal(self):
        assert sanitize_filename("../../etc/passwd.png") == "passwd.png"

    def test_strips_windows_traversal(self):
        assert sanitize_filename("..\\..\\windows\\system32\\evil.png") == "evil.png"

    def test_strips_browser_fakepath(self):
        assert sanitize_filename("C:\\fakepath\\holiday photo.png") == "holiday photo.png"

    def test_drops_control_and_reserved_chars(self):
        assert sanitize_filename("ev\x00il?.png") == "evil.png"

    def test_dot_only_and_extension_names_stay_safe(self):
        # A leading dot is stripped (no hidden files, no "." / ".." escape) and
        # the result is a single safe component - the extension allowlist then
        # rejects it, exactly as it did before filename sanitization existed.
        assert sanitize_filename("..") == "upload"
        assert sanitize_filename(".") == "upload"
        assert sanitize_filename("") == "upload"
        assert sanitize_filename(None) == "upload"
        assert sanitize_filename(".png") == "png"

    def test_hidden_file_is_unhidden(self):
        assert sanitize_filename(".env") == "env"

    def test_length_is_bounded_keeping_extension(self):
        result = sanitize_filename("a" * 500 + ".png")
        assert len(result) <= 180
        assert result.endswith(".png")


class TestGetSafePathHardening:
    def test_backslash_traversal_rejected(self, tmp_path):
        with pytest.raises(ValidationError):
            files_module.get_safe_path(str(tmp_path), "..\\..\\etc\\passwd")

    def test_null_byte_rejected(self, tmp_path):
        with pytest.raises(ValidationError):
            files_module.get_safe_path(str(tmp_path), "ok.png\x00.txt")

    def test_overlong_path_rejected(self, tmp_path):
        with pytest.raises(ValidationError):
            files_module.get_safe_path(str(tmp_path), "a/" * 2000 + "x.png")

    def test_symlink_escape_rejected(self, tmp_path):
        base = tmp_path / "base"
        base.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")
        (base / "link").symlink_to(outside, target_is_directory=True)

        with pytest.raises(ValidationError):
            files_module.get_safe_path(str(base), "link/secret.txt")

    def test_nested_path_still_allowed(self, tmp_path):
        result = files_module.get_safe_path(str(tmp_path), "a/b/c.png")
        assert result == str(tmp_path / "a" / "b" / "c.png")


# ---------------------------------------------------------------------------
# Bounded read / base64 / image helpers
# ---------------------------------------------------------------------------

class TestReadUploadBounded:
    @pytest.mark.asyncio
    async def test_reads_under_limit(self):
        content = await read_upload_bounded(FakeUpload(b"hello"), 1024)
        assert content == b"hello"

    @pytest.mark.asyncio
    async def test_rejects_declared_oversize_before_reading(self):
        upload = FakeUpload(b"x" * 10, size=10_000)
        with pytest.raises(UploadValidationError) as exc:
            await read_upload_bounded(upload, 100)
        assert exc.value.code == "UPLOAD_TOO_LARGE"
        assert exc.value.max_bytes == 100
        assert exc.value.received_bytes == 10_000

    @pytest.mark.asyncio
    async def test_rejects_streamed_oversize_even_when_size_lies(self):
        from core.upload_validation import UPLOAD_CHUNK_BYTES

        # A client that understates the body is still cut off mid-stream: the
        # read never runs past the first chunk that crosses the limit.
        body = b"y" * (UPLOAD_CHUNK_BYTES * 3)
        upload = FakeUpload(body, size=10)
        with pytest.raises(UploadValidationError) as exc:
            await read_upload_bounded(upload, UPLOAD_CHUNK_BYTES + 1024)
        assert exc.value.code == "UPLOAD_TOO_LARGE"
        assert upload._pos <= UPLOAD_CHUNK_BYTES * 2

    @pytest.mark.asyncio
    async def test_reports_progress(self):
        seen = []
        await read_upload_bounded(
            FakeUpload(b"z" * 10), 100, on_progress=lambda got, total: seen.append((got, total))
        )
        assert seen == [(10, 10)]

    @pytest.mark.asyncio
    async def test_cancel_hook_aborts(self):
        calls = {"n": 0}

        def should_cancel():
            calls["n"] += 1
            return calls["n"] > 1

        with pytest.raises(UploadValidationError) as exc:
            await read_upload_bounded(FakeUpload(b"a" * 10), 100, should_cancel=should_cancel)
        assert exc.value.code == "UPLOAD_CANCELLED"

    @pytest.mark.asyncio
    async def test_stalled_read_times_out(self):
        with pytest.raises(UploadValidationError) as exc:
            await read_upload_bounded(FakeUpload(b"a" * 10, delay=0.2), 100, timeout=0.01)
        assert exc.value.code == "UPLOAD_TIMEOUT"

    @pytest.mark.asyncio
    async def test_async_cancel_hook_supported(self):
        async def should_cancel():
            return False

        assert await read_upload_bounded(FakeUpload(b"a"), 10, should_cancel=should_cancel) == b"a"

    def test_sync_variant_enforces_budget(self):
        with pytest.raises(UploadValidationError) as exc:
            read_upload_file_bounded(FakeUpload(b"a" * 3000, size=10), 1000)
        assert exc.value.code == "UPLOAD_TOO_LARGE"

    def test_sync_variant_reads_under_limit(self):
        assert read_upload_file_bounded(FakeUpload(b"abc"), 100) == b"abc"


class TestDecodeBase64Bounded:
    def test_decodes_plain_base64(self):
        assert decode_base64_bounded(base64.b64encode(PNG_BYTES).decode(), 1024) == PNG_BYTES

    def test_decodes_data_url(self):
        payload = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()
        assert decode_base64_bounded(payload, 1024) == PNG_BYTES

    def test_rejects_non_base64_data_url(self):
        with pytest.raises(UploadValidationError) as exc:
            decode_base64_bounded("data:image/png,notbase64", 1024)
        assert exc.value.code == "UPLOAD_INVALID"

    def test_rejects_malformed_data_url(self):
        with pytest.raises(UploadValidationError):
            decode_base64_bounded("data:image/png;base64", 1024)

    def test_rejects_invalid_base64(self):
        with pytest.raises(UploadValidationError) as exc:
            decode_base64_bounded("!!!not base64!!!", 1024)
        assert exc.value.code == "UPLOAD_INVALID"

    def test_rejects_empty(self):
        with pytest.raises(UploadValidationError):
            decode_base64_bounded("", 1024)

    def test_budget_applied_before_decoding(self, monkeypatch):
        # Nothing may be decoded when the encoded string alone is over budget.
        def explode(*args, **kwargs):
            raise AssertionError("base64 decode must not run for an oversized payload")

        monkeypatch.setattr("core.upload_validation.base64.b64decode", explode)
        with pytest.raises(UploadValidationError) as exc:
            decode_base64_bounded("A" * 5000, 1000)
        assert exc.value.code == "UPLOAD_TOO_LARGE"
        assert exc.value.field == "mask_data"


class TestInspectImage:
    def test_returns_dimensions_and_detected_extension(self):
        assert inspect_image(PNG_BYTES) == (2, 2, ".png")

    def test_detects_jpeg_regardless_of_name(self):
        assert inspect_image(JPEG_BYTES) == (2, 2, ".jpg")

    def test_rejects_non_image(self):
        with pytest.raises(UploadValidationError) as exc:
            inspect_image(b"not an image at all")
        assert exc.value.code == "INVALID_IMAGE"

    def test_rejects_empty(self):
        with pytest.raises(UploadValidationError) as exc:
            inspect_image(b"")
        assert exc.value.code == "INVALID_IMAGE"

    def test_rejects_oversized_dimension(self):
        payload = png_claiming_dimensions(20000, 100)
        with pytest.raises(UploadValidationError) as exc:
            inspect_image(payload)
        assert exc.value.code == "IMAGE_DIMENSIONS_TOO_LARGE"
        assert exc.value.details["max_dimension"] == 16384

    def test_rejects_pixel_bomb(self):
        # 9000x8000 = 72M pixels, above the 64M budget but below Pillow's own
        # bomb threshold, so this exercises our guard rather than Pillow's.
        payload = png_claiming_dimensions(9000, 8000)
        with pytest.raises(UploadValidationError) as exc:
            inspect_image(payload)
        assert exc.value.code == "IMAGE_PIXEL_LIMIT"

    def test_rejects_truncated_image(self):
        with pytest.raises(UploadValidationError) as exc:
            inspect_image(PNG_BYTES[: len(PNG_BYTES) // 2])
        assert exc.value.code == "INVALID_IMAGE"


class TestRequireHelpers:
    def test_require_extension_accepts(self):
        assert require_extension("a.PNG", {".png"}) == ".png"

    def test_require_extension_rejects_with_details(self):
        with pytest.raises(UploadValidationError) as exc:
            require_extension("payload.exe", {".png", ".jpg"})
        assert exc.value.code == "UNSUPPORTED_FILE_TYPE"
        assert exc.value.details["received"] == ".exe"
        assert exc.value.details["allowed"] == [".jpg", ".png"]

    def test_require_extension_rejects_missing_extension(self):
        with pytest.raises(UploadValidationError):
            require_extension("payload", {".png"})

    def test_require_declared_size(self):
        require_declared_size(FakeUpload(b"x" * 10, size=10), 100)
        with pytest.raises(UploadValidationError):
            require_declared_size(FakeUpload(b"x" * 10, size=101), 100)

    def test_require_batch_size(self):
        require_batch_size(["a"], 2)
        with pytest.raises(UploadValidationError) as exc:
            require_batch_size(["a", "b", "c"], 2)
        assert exc.value.code == "BATCH_TOO_LARGE"

    def test_human_size(self):
        assert human_size(512) == "512 B"
        assert human_size(2048) == "2.0 KB"
        assert human_size(5 * 1024 * 1024) == "5.0 MB"


class TestErrorPayload:
    def test_payload_shape(self):
        exc = UploadValidationError(
            "too big", code="UPLOAD_TOO_LARGE", field="file", max_bytes=10, received_bytes=20
        )
        assert exc.to_payload() == {
            "error": "too big",
            "code": "UPLOAD_TOO_LARGE",
            "field": "file",
            "max_bytes": 10,
            "received_bytes": 20,
        }

    def test_is_a_validation_error(self):
        # Subclassing ValidationError keeps the 400 status from the existing handler.
        assert issubclass(UploadValidationError, ValidationError)
        assert exc_code() == "UPLOAD_TOO_LARGE"


def exc_code() -> str:
    return UploadValidationError("x", code="UPLOAD_TOO_LARGE").code


class TestDisconnectCancelHook:
    """The routes hand `read_upload_bounded` a client-disconnect hook."""

    class _FakeRequest:
        def __init__(self, disconnected: bool):
            self._disconnected = disconnected
            self.polls = 0

        async def is_disconnected(self) -> bool:
            self.polls += 1
            return self._disconnected

    @pytest.mark.asyncio
    async def test_samples_every_fourth_chunk(self):
        request = self._FakeRequest(disconnected=True)
        check = files_module._cancel_checker(request)

        # Sampled: the first three calls stay False, the fourth reports the
        # disconnect, so a large upload polls a handful of times, not per chunk.
        assert [await check() for _ in range(4)] == [False, False, False, True]
        assert request.polls == 1

    @pytest.mark.asyncio
    async def test_stays_false_while_connected(self):
        check = files_module._cancel_checker(self._FakeRequest(disconnected=False))
        assert not any([await check() for _ in range(8)])

    @pytest.mark.asyncio
    async def test_swallows_hook_errors(self):
        class Broken:
            async def is_disconnected(self):
                raise RuntimeError("connection object gone")

        check = files_module._cancel_checker(Broken())
        assert not any([await check() for _ in range(8)])


# ---------------------------------------------------------------------------
# /api/upload
# ---------------------------------------------------------------------------

class TestGenericUploadRoute:
    def test_rejects_disallowed_extension(self, client: TestClient, sandbox_dirs):
        resp = client.post("/api/upload", files={"file": ("payload.exe", b"MZ\x00\x00", "application/octet-stream")})
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "UNSUPPORTED_FILE_TYPE"
        assert body["field"] == "file"
        assert ".exe" not in body["details"]["allowed"]

    def test_rejects_disguised_image(self, client: TestClient, sandbox_dirs):
        resp = client.post("/api/upload", files={"file": ("evil.png", b"<html>not an image", "image/png")})
        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_IMAGE"

    def test_rejects_empty_file(self, client: TestClient, sandbox_dirs):
        resp = client.post("/api/upload", files={"file": ("empty.png", b"", "image/png")})
        assert resp.status_code == 400
        assert resp.json()["code"] in {"INVALID_IMAGE", "UPLOAD_INVALID"}

    def test_rejects_oversize_declared(self, client: TestClient, sandbox_dirs, monkeypatch):
        monkeypatch.setattr(files_module, "MAX_UPLOAD_BYTES", 16)
        resp = client.post("/api/upload", files={"file": ("big.png", image_bytes(64, 64), "image/png")})
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "UPLOAD_TOO_LARGE"
        assert body["max_bytes"] == 16
        assert body["received_bytes"] > 16

    def test_rejects_oversize_image_dimensions(self, client: TestClient, sandbox_dirs):
        payload = png_claiming_dimensions(20000, 100)
        resp = client.post("/api/upload", files={"file": ("wide.png", payload, "image/png")})
        assert resp.status_code == 400
        assert resp.json()["code"] == "IMAGE_DIMENSIONS_TOO_LARGE"

    def test_sanitizes_traversal_filename(self, client: TestClient, sandbox_dirs):
        resp = client.post(
            "/api/upload",
            files={"file": ("../../hacked.png", PNG_BYTES, "image/png")},
            params={"path": "input"},
        )
        assert resp.status_code == 200
        assert resp.json()["filename"] == "hacked.png"
        written = list((sandbox_dirs["output"] / "input").iterdir())
        assert [p.name for p in written] == ["hacked.png"]

    def test_rejects_traversal_target_path(self, client: TestClient, sandbox_dirs):
        resp = client.post(
            "/api/upload",
            files={"file": ("x.png", PNG_BYTES, "image/png")},
            params={"path": "../escape"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_allows_non_image_allowlisted_types(self, client: TestClient, sandbox_dirs):
        resp = client.post(
            "/api/upload",
            files={"file": ("prompt.txt", b"a prompt", "text/plain")},
            params={"path": "chat_attachments"},
        )
        assert resp.status_code == 200
        assert resp.json()["filename"] == "prompt.txt"


# ---------------------------------------------------------------------------
# /api/upload/input
# ---------------------------------------------------------------------------

class TestInputImageUploadRoute:
    def test_rejects_non_image_content(self, client: TestClient, sandbox_dirs):
        resp = client.post("/api/upload/input", files={"file": ("fake.png", b"nope", "image/png")})
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "INVALID_IMAGE"
        assert list(sandbox_dirs["input"].iterdir()) == []

    def test_rejects_executable_content(self, client: TestClient, sandbox_dirs):
        resp = client.post("/api/upload/input", files={"file": ("tool.png", b"MZ\x90\x00", "image/png")})
        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_IMAGE"

    def test_rejects_oversize(self, client: TestClient, sandbox_dirs, monkeypatch):
        monkeypatch.setattr(files_module, "MAX_INPUT_BYTES", 128)
        resp = client.post("/api/upload/input", files={"file": ("big.png", image_bytes(64, 64), "image/png")})
        assert resp.status_code == 400
        assert resp.json()["code"] == "UPLOAD_TOO_LARGE"

    def test_rejects_oversized_dimensions(self, client: TestClient, sandbox_dirs):
        resp = client.post(
            "/api/upload/input",
            files={"file": ("wide.png", png_claiming_dimensions(20000, 50), "image/png")},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "IMAGE_DIMENSIONS_TOO_LARGE"

    def test_stored_extension_follows_detected_format(self, client: TestClient, sandbox_dirs):
        # A JPEG mislabelled as .png is stored with its real extension.
        resp = client.post("/api/upload/input", files={"file": ("lying.png", JPEG_BYTES, "image/png")})
        assert resp.status_code == 200
        body = resp.json()
        assert body["filename"].endswith(".jpg")
        assert body["path"] == f"input/{body['filename']}"
        assert (sandbox_dirs["input"] / body["filename"]).exists()
        assert body["width"] == 2 and body["height"] == 2

    def test_extensionless_image_is_accepted(self, client: TestClient, sandbox_dirs):
        resp = client.post("/api/upload/input", files={"file": ("screenshot", PNG_BYTES, "image/png")})
        assert resp.status_code == 200
        assert resp.json()["filename"].endswith(".png")


# ---------------------------------------------------------------------------
# /api/upload/mask
# ---------------------------------------------------------------------------

class TestMaskUploadRoute:
    def test_rejects_non_image_payload(self, client: TestClient, sandbox_dirs):
        payload = {"mask_data": base64.b64encode(b"just some bytes").decode()}
        resp = client.post("/api/upload/mask", json=payload)
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "INVALID_IMAGE"
        assert body["field"] == "mask_data"
        assert list(sandbox_dirs["input"].iterdir()) == []

    def test_rejects_oversize_payload(self, client: TestClient, sandbox_dirs, monkeypatch):
        monkeypatch.setattr(files_module, "MAX_INPUT_BYTES", 1024)
        payload = {"mask_data": base64.b64encode(b"\x00" * (5 * 1024 * 1024)).decode()}
        resp = client.post("/api/upload/mask", json=payload)
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "UPLOAD_TOO_LARGE"
        assert body["field"] == "mask_data"
        assert list(sandbox_dirs["input"].iterdir()) == []

    def test_requires_mask_data(self, client: TestClient, sandbox_dirs):
        resp = client.post("/api/upload/mask", json={})
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_sanitizes_source_filename(self, client: TestClient, sandbox_dirs):
        payload = {
            "mask_data": "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode(),
            "source_filename": "../../etc/passwd.png",
        }
        resp = client.post("/api/upload/mask", json=payload)
        assert resp.status_code == 200
        name = resp.json()["filename"]
        assert name.startswith("passwd_mask_") and name.endswith(".png")
        assert ".." not in resp.json()["path"]
        assert (sandbox_dirs["input"] / name).exists()

    def test_missing_source_filename_uses_default(self, client: TestClient, sandbox_dirs):
        payload = {"mask_data": base64.b64encode(PNG_BYTES).decode()}
        resp = client.post("/api/upload/mask", json=payload)
        assert resp.status_code == 200
        assert resp.json()["filename"].startswith("mask_")


# ---------------------------------------------------------------------------
# /api/files/batch-download
# ---------------------------------------------------------------------------

class TestBatchDownloadRoute:
    def _seed(self, sandbox_dirs, *names):
        for name in names:
            (sandbox_dirs["output"] / name).write_bytes(PNG_BYTES)

    def test_empty_request_rejected(self, client: TestClient, sandbox_dirs):
        resp = client.post("/api/files/batch-download", json={"files": []})
        assert resp.status_code == 400
        assert resp.json()["code"] == "EXPORT_NO_MATCHING_FILES"

    def test_too_many_files_rejected(self, client: TestClient, sandbox_dirs, monkeypatch):
        monkeypatch.setattr(files_module, "MAX_EXPORT_FILES", 2)
        resp = client.post("/api/files/batch-download", json={"files": ["a.png", "b.png", "c.png"]})
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "EXPORT_TOO_MANY_FILES"
        assert body["details"]["max_files"] == 2

    def test_all_missing_rejected_with_names(self, client: TestClient, sandbox_dirs):
        resp = client.post("/api/files/batch-download", json={"files": ["ghost.png", "phantom.png"]})
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "EXPORT_NO_MATCHING_FILES"
        assert "ghost.png" in body["details"]["missing"]

    def test_per_file_budget_rejected(self, client: TestClient, sandbox_dirs, monkeypatch):
        self._seed(sandbox_dirs, "big.png")
        monkeypatch.setattr(files_module, "MAX_EXPORT_FILE_BYTES", 10)
        resp = client.post("/api/files/batch-download", json={"files": ["big.png"]})
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "EXPORT_TOO_LARGE"
        assert body["details"]["filename"] == "big.png"

    def test_total_budget_rejected(self, client: TestClient, sandbox_dirs, monkeypatch):
        self._seed(sandbox_dirs, "a.png", "b.png", "c.png")
        monkeypatch.setattr(files_module, "MAX_EXPORT_TOTAL_BYTES", len(PNG_BYTES) * 2)
        resp = client.post("/api/files/batch-download", json={"files": ["a.png", "b.png", "c.png"]})
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "EXPORT_TOO_LARGE"
        assert body["received_bytes"] > body["max_bytes"]

    def test_zip_contains_all_requested_files(self, client: TestClient, sandbox_dirs):
        self._seed(sandbox_dirs, "a.png", "b.png")
        resp = client.post("/api/files/batch-download", json={"files": ["a.png", "b.png"]})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            assert sorted(zf.namelist()) == ["a.png", "b.png"]
            assert zf.testzip() is None

    def test_duplicate_names_do_not_clobber(self, client: TestClient, sandbox_dirs):
        # Same basename reachable through two relative paths.
        nested = sandbox_dirs["output"] / "2026" / "01" / "01"
        nested.mkdir(parents=True)
        (sandbox_dirs["output"] / "dup.png").write_bytes(PNG_BYTES)
        (nested / "dup.png").write_bytes(JPEG_BYTES)

        resp = client.post(
            "/api/files/batch-download",
            json={"files": ["dup.png", "2026/01/01/dup.png"]},
        )
        assert resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
            assert len(names) == 2
            assert len(set(names)) == 2

    def test_partial_missing_reported_in_headers(self, client: TestClient, sandbox_dirs):
        self._seed(sandbox_dirs, "present.png")
        resp = client.post("/api/files/batch-download", json={"files": ["present.png", "gone.png"]})
        assert resp.status_code == 200
        assert resp.headers["x-missing-count"] == "1"
        assert "gone.png" in resp.headers["x-missing-files"]
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            assert zf.namelist() == ["present.png"]

    def test_traversal_request_is_refused(self, client: TestClient, sandbox_dirs, tmp_path):
        secret = tmp_path / "secret.png"
        secret.write_bytes(PNG_BYTES)
        resp = client.post("/api/files/batch-download", json={"files": ["../secret.png"]})
        assert resp.status_code == 400
        assert resp.json()["code"] == "EXPORT_NO_MATCHING_FILES"


# ---------------------------------------------------------------------------
# Batch request budgets
# ---------------------------------------------------------------------------

class TestBatchRequestBudgets:
    def test_batch_delete_rejects_oversized_list(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(files_module, "MAX_BATCH_ITEMS", 2)
        resp = client.post(
            "/api/batch/delete", json={"directory": "output", "files": ["a.png", "b.png", "c.png"]}
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "BATCH_TOO_LARGE"

    def test_batch_delete_invalid_directory_stays_400(self, client: TestClient):
        resp = client.post("/api/batch/delete", json={"directory": "../../etc", "files": ["passwd"]})
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_metadata_batch_rejects_oversized_list(self, client: TestClient, monkeypatch):
        monkeypatch.setattr(files_module, "MAX_BATCH_ITEMS", 1)
        resp = client.post("/api/files/metadata/batch", json={"paths": ["a.png", "b.png"]})
        assert resp.status_code == 400
        assert resp.json()["code"] == "BATCH_TOO_LARGE"


# ---------------------------------------------------------------------------
# Endpoints whose blocking bodies moved to a worker thread
#
# These assert the *payload* is unchanged by the `asyncio.to_thread`
# conversion. The blocking part — the synchronous session, the recursive globs
# of output/thumb, the DEFLATE pass — now runs off the event loop, but the
# responses must be byte-for-byte what they were inline.
# ---------------------------------------------------------------------------

class TestThumbnailRouteOffLoop:
    def _seed_indexed_thumb(self, sandbox_dirs, session):
        """An asset row plus its on-disk WebP thumbnail."""
        from datetime import datetime, timezone

        from core.entities import Asset

        (sandbox_dirs["output"] / "shot.png").write_bytes(PNG_BYTES)
        thumb_rel = "thumb/shot.webp"
        thumb = sandbox_dirs["output"] / thumb_rel
        thumb.parent.mkdir(parents=True, exist_ok=True)
        thumb.write_bytes(PNG_BYTES)

        asset = Asset(
            relative_path="shot.png",
            filename="shot.png",
            thumbnail_relative_path=thumb_rel,
            workspace="default",
            generated_at=datetime.now(timezone.utc),
        )
        session.add(asset)
        session.commit()
        return asset

    def test_indexed_thumbnail_is_served(self, client: TestClient, sandbox_dirs, session):
        self._seed_indexed_thumb(sandbox_dirs, session)

        resp = client.get("/api/thumbnail/medium/shot.png")
        assert resp.status_code == 200
        assert resp.content == PNG_BYTES
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert resp.headers["etag"]

    def test_mirrored_legacy_thumb_is_served(self, client: TestClient, sandbox_dirs):
        (sandbox_dirs["output"] / "orig.png").write_bytes(PNG_BYTES)
        mirrored = sandbox_dirs["output"] / "thumb" / "orig.webp"
        mirrored.parent.mkdir(parents=True, exist_ok=True)
        mirrored.write_bytes(PNG_BYTES)

        resp = client.get("/api/thumbnail/medium/orig.png")
        assert resp.status_code == 200
        assert resp.content == PNG_BYTES

    def test_falls_back_to_the_full_image(self, client: TestClient, sandbox_dirs):
        (sandbox_dirs["output"] / "solo.png").write_bytes(PNG_BYTES)

        resp = client.get("/api/thumbnail/medium/solo.png")
        assert resp.status_code == 200
        assert resp.content == PNG_BYTES
        assert resp.headers["cache-control"] == "public, max-age=3600"

    def test_invalid_size_is_still_a_400(self, client: TestClient, sandbox_dirs):
        resp = client.get("/api/thumbnail/huge/whatever.png")
        assert resp.status_code == 400

    def test_missing_file_is_a_404(self, client: TestClient, sandbox_dirs):
        resp = client.get("/api/thumbnail/medium/nothing-here.png")
        assert resp.status_code == 404


class TestBatchDeleteOffLoop:
    def test_removes_files_and_their_thumbnails(self, client: TestClient, sandbox_dirs):
        for name in ("a.png", "b.png"):
            (sandbox_dirs["output"] / name).write_bytes(PNG_BYTES)
            thumb = sandbox_dirs["output"] / "thumb" / name.replace(".png", ".webp")
            thumb.parent.mkdir(parents=True, exist_ok=True)
            thumb.write_bytes(PNG_BYTES)

        resp = client.post(
            "/api/batch/delete", json={"directory": "output", "files": ["a.png", "b.png"]}
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "success", "deleted": 2, "total": 2}

        assert not (sandbox_dirs["output"] / "a.png").exists()
        assert not (sandbox_dirs["output"] / "b.png").exists()
        assert not (sandbox_dirs["output"] / "thumb" / "a.webp").exists()
        assert not (sandbox_dirs["output"] / "thumb" / "b.webp").exists()

    def test_counts_a_name_that_does_not_exist(self, client: TestClient, sandbox_dirs):
        resp = client.post(
            "/api/batch/delete", json={"directory": "output", "files": ["ghost.png"]}
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "success", "deleted": 1, "total": 1}

    def test_traversal_entries_are_skipped_not_deleted(self, client: TestClient, tmp_path):
        secret = tmp_path / "secret.png"
        secret.write_bytes(PNG_BYTES)

        resp = client.post(
            "/api/batch/delete", json={"directory": "output", "files": ["../secret.png"]}
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0
        assert secret.exists()

    def test_model_directory_delete_still_works(self, client: TestClient, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache"
        (cache_dir / "models" / "checkpoints").mkdir(parents=True)
        target = cache_dir / "models" / "checkpoints" / "m.safetensors"
        target.write_bytes(b"weights")
        monkeypatch.setattr(files_module, "CACHE_DIR", str(cache_dir))

        resp = client.post(
            "/api/batch/delete",
            json={"directory": "models/checkpoints", "files": ["m.safetensors"]},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1
        assert not target.exists()


# ---------------------------------------------------------------------------
# world_vault upload endpoints (same helpers, same error shape)
# ---------------------------------------------------------------------------

@pytest.fixture(name="vault_image_dirs")
def vault_image_dirs_fixture(tmp_path, monkeypatch):
    import config as app_config

    avatar_dir = tmp_path / "avatars"
    location_dir = tmp_path / "locations"
    avatar_dir.mkdir()
    location_dir.mkdir()
    monkeypatch.setattr(app_config.settings, "character_avatar_dir", str(avatar_dir))
    monkeypatch.setattr(app_config.settings, "location_image_dir", str(location_dir))
    return {"avatars": avatar_dir, "locations": location_dir}


def _make_character(session, name="Hero"):
    from core.entities import Character

    character = Character(name=name, description="d", personality="p", scenario="s",
                          first_mes="m", mes_example="e")
    session.add(character)
    session.commit()
    session.refresh(character)
    return character


class TestAvatarUpload:
    def test_rejects_non_image(self, client: TestClient, session, vault_image_dirs):
        character = _make_character(session)
        resp = client.post(
            f"/api/v2/characters/{character.id}/avatar",
            files={"file": ("evil.png", b"<script>alert(1)</script>", "image/png")},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_IMAGE"
        assert list(vault_image_dirs["avatars"].iterdir()) == []

    def test_rejects_oversize(self, client: TestClient, session, vault_image_dirs, monkeypatch):
        import api.routes.world_vault.characters as chars_module

        character = _make_character(session)
        monkeypatch.setattr(chars_module, "MAX_AVATAR_BYTES", 16)
        resp = client.post(
            f"/api/v2/characters/{character.id}/avatar",
            files={"file": ("a.png", PNG_BYTES, "image/png")},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "UPLOAD_TOO_LARGE"

    def test_accepts_real_image(self, client: TestClient, session, vault_image_dirs):
        character = _make_character(session)
        resp = client.post(
            f"/api/v2/characters/{character.id}/avatar",
            files={"file": ("face.png", PNG_BYTES, "image/png")},
        )
        assert resp.status_code == 200
        assert resp.json()["has_avatar"] is True
        assert (vault_image_dirs["avatars"] / character.id / "avatar.png").exists()


class TestLocationImageUpload:
    def _make_location(self, session, name="Tavern"):
        from core.entities import Location

        location = Location(name=name, description="d", atmosphere="a")
        session.add(location)
        session.commit()
        session.refresh(location)
        return location

    def test_rejects_non_image(self, client: TestClient, session, vault_image_dirs):
        location = self._make_location(session)
        resp = client.post(
            f"/api/v2/locations/{location.id}/image",
            files={"file": ("evil.png", b"not a png", "image/png")},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_IMAGE"

    def test_extension_comes_from_detected_format(self, client: TestClient, session, vault_image_dirs):
        location = self._make_location(session)
        resp = client.post(
            f"/api/v2/locations/{location.id}/image",
            files={"file": ("shot.png", JPEG_BYTES, "image/png")},
        )
        assert resp.status_code == 200
        assert resp.json()["image_path"].endswith("image.jpg")


class TestCharacterCardImport:
    def test_rejects_oversize_card(self, client: TestClient, session, monkeypatch, tmp_path):
        import api.routes.world_vault.characters as chars_module

        monkeypatch.setattr(chars_module, "MAX_CARD_BYTES", 32)
        resp = client.post(
            "/api/v2/characters/import",
            files={"file": ("card.png", PNG_BYTES, "image/png")},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "UPLOAD_TOO_LARGE"

    def test_rejects_oversized_card_dimensions(self, client: TestClient, session):
        resp = client.post(
            "/api/v2/characters/import",
            files={"file": ("card.png", png_claiming_dimensions(20000, 20), "image/png")},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] in {"IMAGE_DIMENSIONS_TOO_LARGE", "INVALID_IMAGE"}


class TestChatImport:
    def test_rejects_oversize_chat_file(self, client: TestClient, monkeypatch):
        import api.routes.world_vault.chats as chats_module

        monkeypatch.setattr(chats_module, "MAX_CHAT_IMPORT_BYTES", 64)
        payload = json.dumps({"messages": [{"role": "user", "content": "x" * 500}]}).encode()
        resp = client.post(
            "/api/v2/chats/import",
            files={"file": ("chat.json", payload, "application/json")},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "UPLOAD_TOO_LARGE"
