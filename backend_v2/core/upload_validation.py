"""Bounded validation for user-supplied uploads and exports.

Every upload route funnels through these helpers so an oversized, mistyped or
unreadable file fails the same way: HTTP 400 with an `UploadValidationError`
carrying a machine-readable code plus the limits that were exceeded. The helpers
read bodies in bounded chunks (never `await file.read()` on an untrusted stream),
so a 10 GB upload is rejected after one chunk instead of after 10 GB of RAM.

Limits are module constants and can be overridden per deployment with env vars
(all `COMFY_` prefixed, e.g. `COMFY_MAX_INPUT_SIZE_MB=25`).
"""
import asyncio
import base64
import binascii
import inspect
import io
import os
from collections.abc import Awaitable, Callable

from starlette.datastructures import UploadFile

from core.exceptions import UploadValidationError

try:  # starlette raises this from the request stream when a client disconnects
    from starlette.requests import ClientDisconnect as ClientDisconnectError
except ImportError:  # pragma: no cover - starlette layout changed
    class ClientDisconnectError(Exception):
        """Fallback when starlette does not expose ClientDisconnect."""


MB = 1024 * 1024


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """Read a positive int from the environment, falling back to `default`."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
# Generic file endpoint (/api/upload): models, archives, prompts, chat files.
MAX_UPLOAD_SIZE_MB = _env_int("COMFY_MAX_UPLOAD_SIZE_MB", 500)
# Image source/mask endpoints (/api/upload/input, /api/upload/mask): these are
# handed to ComfyUI, which resizes to a working resolution anyway.
MAX_INPUT_SIZE_MB = _env_int("COMFY_MAX_INPUT_SIZE_MB", 50)
# Avatars and location images: rendered inline in the UI, never huge.
MAX_AVATAR_SIZE_MB = _env_int("COMFY_MAX_AVATAR_SIZE_MB", 20)
# Character cards (PNG) and chat/JSON imports.
MAX_CARD_SIZE_MB = _env_int("COMFY_MAX_CARD_SIZE_MB", 25)

MAX_IMAGE_DIMENSION = _env_int("COMFY_MAX_IMAGE_DIMENSION", 16384)
MAX_IMAGE_PIXELS = _env_int("COMFY_MAX_IMAGE_PIXELS", 64_000_000)

# Export budgets (batch download archive).
MAX_EXPORT_FILES = _env_int("COMFY_MAX_EXPORT_FILES", 500)
MAX_EXPORT_FILE_MB = _env_int("COMFY_MAX_EXPORT_FILE_MB", 250)
MAX_EXPORT_TOTAL_MB = _env_int("COMFY_MAX_EXPORT_TOTAL_MB", 1024)

# Batch request budget for list-style endpoints.
MAX_BATCH_ITEMS = _env_int("COMFY_MAX_BATCH_ITEMS", 1000)

UPLOAD_CHUNK_BYTES = 1 * MB
# A single stalled read (client that stops sending without closing) is aborted.
UPLOAD_READ_TIMEOUT_SECONDS = _env_int("COMFY_UPLOAD_TIMEOUT_SECONDS", 300)

# Read cap for base64 payloads before decoding (base64 inflates by ~4/3).
BASE64_BUDGET_RATIO = 1.4

# Image extensions accepted by the generic upload endpoint. Detection of the
# real content type is separate (see inspect_image) - this is the coarse filter.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

# Extensions the generic upload endpoint accepts. Mirrors the historical
# ALLOWED_UPLOAD_EXTENSIONS set in api/routes/files.py.
ALLOWED_UPLOAD_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff',
    '.safetensors', '.ckpt', '.pt', '.pth', '.bin',
    '.json', '.yaml', '.yml', '.txt', '.csv',
    '.zip', '.tar', '.gz',
    '.onnx', '.gguf',
}

# Detected image format -> extension used when storing a validated image.
PIL_FORMAT_EXTENSIONS = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "WEBP": ".webp",
    "GIF": ".gif",
    "BMP": ".bmp",
    "TIFF": ".tiff",
}

_DATA_URL_PREFIX = "data:"


def human_size(num_bytes: float) -> str:
    """Render a byte count the way limit messages expect ('12.5 MB')."""
    if num_bytes >= MB:
        return f"{num_bytes / MB:.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{int(num_bytes)} B"


def sanitize_filename(
    raw: str | None,
    *,
    default: str = "upload",
    max_length: int = 180,
) -> str:
    """Reduce a client-supplied filename to a safe single path component.

    Strips directory components from both separator styles (browsers send
    `C:\\fakepath\\x.png`, Windows clients may send `..\\..\\x.png`), drops
    control/reserved characters, and bounds the length. Never returns an empty
    string, `.` or `..`.
    """
    name = (raw or "").strip()
    if not name:
        return default

    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*')
    # Leading dots would hide the file; trailing dots/spaces break Windows.
    name = name.strip(" .")
    if not name or set(name) <= {"."}:
        return default

    stem, ext = os.path.splitext(name)
    if len(ext) > 16:
        # Not really an extension (a long dot-suffixed token) - keep the name whole.
        stem, ext = name, ""
    stem = stem.strip(" .") or default

    if len(stem) + len(ext) > max_length:
        stem = stem[: max_length - len(ext)].strip(" .") or default
    return stem + ext


def too_large(received_bytes: int, max_bytes: int, *, field: str = "file") -> UploadValidationError:
    """Build the canonical 'too large' error for a byte budget."""
    return UploadValidationError(
        f"File size exceeds the {human_size(max_bytes)} limit. "
        f"Received: {human_size(received_bytes)}",
        code="UPLOAD_TOO_LARGE",
        field=field,
        max_bytes=max_bytes,
        received_bytes=received_bytes,
    )


def require_extension(
    filename: str | None,
    allowed: set[str],
    *,
    field: str = "file",
    allowed_hint: str | None = None,
) -> str:
    """Return the lowercased extension, rejecting anything outside `allowed`."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in allowed:
        hint = allowed_hint or ", ".join(sorted(allowed))
        raise UploadValidationError(
            f"File type '{ext or 'unknown'}' is not allowed. Allowed types: {hint}",
            code="UNSUPPORTED_FILE_TYPE",
            field=field,
            details={"received": ext, "allowed": sorted(allowed)},
        )
    return ext


def require_declared_size(upload: UploadFile, max_bytes: int, *, field: str = "file") -> None:
    """Reject an upload whose declared size is already over budget.

    Uses the parser-provided `size` so an oversized body is refused before a
    single chunk is read.
    """
    declared = getattr(upload, "size", None)
    if declared is not None and declared > max_bytes:
        raise too_large(declared, max_bytes, field=field)


async def read_upload_bounded(
    upload: UploadFile,
    max_bytes: int,
    *,
    field: str = "file",
    on_progress: Callable[[int, int | None], None] | None = None,
    should_cancel: Callable[[], bool | Awaitable[bool]] | None = None,
    timeout: int | None = None,
) -> bytes:
    """Read an upload into memory in bounded chunks.

    Stops at the first chunk that crosses `max_bytes` (so peak memory stays near
    the limit instead of the body size), reports progress via `on_progress`
    after every chunk, and honours `should_cancel()` between chunks so a caller
    can abort work when its client goes away. A read that stalls longer than
    `timeout` is aborted rather than pinning a worker forever.
    """
    declared = getattr(upload, "size", None)
    if declared is not None and declared > max_bytes:
        raise too_large(declared, max_bytes, field=field)

    read_timeout = timeout if timeout is not None else UPLOAD_READ_TIMEOUT_SECONDS
    chunks: list[bytes] = []
    received = 0

    while True:
        if should_cancel is not None:
            cancelled = should_cancel()
            if inspect.isawaitable(cancelled):
                cancelled = await cancelled
            if cancelled:
                raise UploadValidationError(
                    "Upload cancelled before completion",
                    code="UPLOAD_CANCELLED",
                    field=field,
                    received_bytes=received,
                )

        try:
            chunk = await asyncio.wait_for(upload.read(UPLOAD_CHUNK_BYTES), timeout=read_timeout)
        except asyncio.TimeoutError as exc:
            raise UploadValidationError(
                f"Upload stalled for more than {read_timeout}s",
                code="UPLOAD_TIMEOUT",
                field=field,
                received_bytes=received,
            ) from exc
        except ClientDisconnectError as exc:
            raise UploadValidationError(
                "Upload aborted before completion",
                code="UPLOAD_CANCELLED",
                field=field,
                received_bytes=received,
            ) from exc

        if not chunk:
            break

        received += len(chunk)
        if received > max_bytes:
            raise too_large(received, max_bytes, field=field)
        chunks.append(chunk)
        if on_progress is not None:
            on_progress(received, declared)

    return b"".join(chunks)


def read_upload_file_bounded(
    upload: UploadFile,
    max_bytes: int,
    *,
    field: str = "file",
) -> bytes:
    """Sync counterpart of read_upload_bounded for already-spooled uploads.

    Starlette writes the multipart body to a temp file before the route runs, so
    a sync route can still blow up on `upload.file.read()`. This walks the
    spooled file in chunks under the same budget.
    """
    require_declared_size(upload, max_bytes, field=field)

    handle = getattr(upload, "file", None)
    if handle is None:  # pragma: no cover - starlette always provides .file
        return b""

    chunks: list[bytes] = []
    received = 0
    while True:
        chunk = handle.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        received += len(chunk)
        if received > max_bytes:
            raise too_large(received, max_bytes, field=field)
        chunks.append(chunk)

    return b"".join(chunks)


def decode_base64_bounded(
    raw: str,
    max_bytes: int,
    *,
    field: str = "mask_data",
    label: str = "Payload",
) -> bytes:
    """Decode a base64 or data-URL payload with the size budget applied first.

    The encoded string is bounded before decoding (base64 inflates by ~4/3) so an
    oversized request never materialises as a large bytes object.
    """
    if not isinstance(raw, str) or not raw:
        raise UploadValidationError(
            f"{label} is required", code="UPLOAD_INVALID", field=field
        )

    payload = raw
    if payload.startswith(_DATA_URL_PREFIX):
        header, separator, payload = payload.partition(",")
        if not separator:
            raise UploadValidationError(
                f"{label} data URL is malformed (missing ',' separator)",
                code="UPLOAD_INVALID",
                field=field,
            )
        if not header.lower().endswith("base64"):
            raise UploadValidationError(
                f"{label} data URL must be base64 encoded",
                code="UPLOAD_INVALID",
                field=field,
            )

    max_encoded = int(max_bytes * BASE64_BUDGET_RATIO) + 1024
    if len(payload) > max_encoded:
        received = int(len(payload) / BASE64_BUDGET_RATIO)
        raise UploadValidationError(
            f"{label} exceeds the {human_size(max_bytes)} limit when decoded. "
            f"Received: {human_size(received)}",
            code="UPLOAD_TOO_LARGE",
            field=field,
            max_bytes=max_bytes,
            received_bytes=received,
        )

    try:
        content = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UploadValidationError(
            f"{label} is not valid base64: {exc}",
            code="UPLOAD_INVALID",
            field=field,
        ) from exc

    if len(content) > max_bytes:
        raise too_large(len(content), max_bytes, field=field)
    if not content:
        raise UploadValidationError(
            f"{label} decoded to an empty payload",
            code="UPLOAD_INVALID",
            field=field,
        )
    return content


def inspect_image(
    content: bytes,
    *,
    field: str = "file",
    label: str = "File",
    max_dimension: int = MAX_IMAGE_DIMENSION,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> tuple[int, int, str]:
    """Validate that `content` is a readable image within the dimension budget.

    Returns `(width, height, extension)` where extension is derived from the
    format Pillow actually detected, so a mislabelled upload is stored with a
    truthful extension.
    """
    from PIL import Image, UnidentifiedImageError

    if not content:
        raise UploadValidationError(f"{label} is empty", code="INVALID_IMAGE", field=field)

    try:
        with Image.open(io.BytesIO(content)) as img:
            # Dimensions are readable from the header alone, so the budget is
            # enforced before walking/decoding the body: a decompression bomb is
            # rejected without ever materialising pixels.
            width, height = img.size
            image_format = (img.format or "").upper()

            if not width or not height:
                raise UploadValidationError(
                    f"{label} has no usable dimensions",
                    code="INVALID_IMAGE",
                    field=field,
                )
            if width > max_dimension or height > max_dimension:
                raise UploadValidationError(
                    f"{label} dimensions {width}x{height} exceed the "
                    f"{max_dimension}x{max_dimension} limit",
                    code="IMAGE_DIMENSIONS_TOO_LARGE",
                    field=field,
                    details={"width": width, "height": height, "max_dimension": max_dimension},
                )
            if width * height > max_pixels:
                raise UploadValidationError(
                    f"{label} has {width * height} pixels, above the {max_pixels} pixel limit",
                    code="IMAGE_PIXEL_LIMIT",
                    field=field,
                    details={"width": width, "height": height, "max_pixels": max_pixels},
                )

            # verify() walks the container so truncated/garbage payloads are
            # rejected here rather than failing later inside a worker.
            img.verify()
    except UploadValidationError:
        raise
    except Image.DecompressionBombError as exc:
        raise UploadValidationError(
            f"{label} declares more pixels than the {max_pixels} pixel limit allows",
            code="IMAGE_PIXEL_LIMIT",
            field=field,
            details={"max_pixels": max_pixels},
        ) from exc
    except UnidentifiedImageError as exc:
        raise UploadValidationError(
            f"{label} is not a readable image",
            code="INVALID_IMAGE",
            field=field,
        ) from exc
    except Exception as exc:
        raise UploadValidationError(
            f"{label} is not a readable image: {exc}",
            code="INVALID_IMAGE",
            field=field,
        ) from exc

    return width, height, PIL_FORMAT_EXTENSIONS.get(image_format, ".png")


def require_batch_size(
    items: list,
    max_items: int = MAX_BATCH_ITEMS,
    *,
    field: str = "files",
) -> None:
    """Reject oversized batch lists before any per-item work happens."""
    if len(items) > max_items:
        raise UploadValidationError(
            f"Too many items requested: {len(items)} (limit {max_items})",
            code="BATCH_TOO_LARGE",
            field=field,
            details={"received": len(items), "max_items": max_items},
        )
