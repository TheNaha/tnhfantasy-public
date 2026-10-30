"""File-size cap for /get-file relay, read from the environment.

The rest of this module (connection pooling, retry logic, `SharedHttpClient`)
was provider-worker infrastructure deleted on 2026-10-08 when the backend moved
to in-process engines. `relays_bytes` is unused since `server.py` delegates
downloads to `downloads.download_model_to_path`; only `get_file_size_cap`
survived in the remote agent.
"""

import os

# Default ceiling on a single /get-file transfer. Files served by the storage
# apps are model sidecars, previews and output images; a checkpoint weights file
# is not fetched through this path.
DEFAULT_GET_FILE_SIZE_CAP = 512 * 1024 * 1024

# Default ceiling on one uploaded file body (decoded bytes) — the same default
# backend_v2/services/engines/base.py documents for PROVIDER_UPLOAD_MAX_BYTES.
DEFAULT_UPLOAD_MAX_BYTES = 512 * 1024 * 1024


def get_upload_size_cap() -> int:
    """Ceiling on one uploaded file body, in decoded bytes.

    Override with ``PROVIDER_UPLOAD_MAX_BYTES`` — the name the backend's
    pre-check (`services/engines/base.get_upload_size_cap`) reads, so the
    container and the route in front of it agree on one knob. Zero or
    negative disables the cap, exactly like ``get_file_size_cap``.

    Mirrored in ``deployables/provider_worker_core/http_client.py``
    (deliberate fork); `tests/test_provider_core_parity.py` pins the two.
    """
    raw = os.getenv("PROVIDER_UPLOAD_MAX_BYTES", "").strip()
    if not raw:
        return DEFAULT_UPLOAD_MAX_BYTES
    try:
        cap = int(raw)
    except ValueError:
        return DEFAULT_UPLOAD_MAX_BYTES
    return cap if cap > 0 else 0


def get_file_size_cap() -> int:
    """Max bytes a provider will relay for one /get-file call.

    Override with ``PROVIDER_GET_FILE_MAX_BYTES``. Zero or negative disables the
    cap (only for a deployment that genuinely streams model weights).
    """
    raw = os.getenv("PROVIDER_GET_FILE_MAX_BYTES", "").strip()
    if not raw:
        return DEFAULT_GET_FILE_SIZE_CAP
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_GET_FILE_SIZE_CAP
