"""Constant-time provider-token comparison, in one place.

There were five hand-written copies of "read a token out of a header and compare
it", and they did not agree. The differences were not cosmetic:

* Two of them compared `str` directly. `hmac.compare_digest` raises `TypeError`
  on a `str` containing any byte >= 0x80, and Starlette decodes header bytes as
  latin-1, so a single non-ASCII character in `X-Provider-Token` raised INSIDE the
  comparison. On the ASGI routes the catch-all turned that into a 500 with
  `retryable: true`, which the backend reads as "this provider is unhealthy, try
  it elsewhere" — so one malformed auth header became a paid retry storm across
  the whole provider pool. On the WebSocket route it tore the socket down instead
  of rejecting the request.
* The Beam `@realtime` GPU handler had no check at all, while the storage,
  download and extractor apps on the same deployment did.
* Fails-open vs fails-closed was decided per file rather than once.

Encoding to bytes before comparing makes the check total: `bytes` accepts any
byte sequence, so a non-ASCII token is simply a wrong token rather than an
exception. `surrogateescape` is used on encode because Starlette can hand back a
string with lone surrogates, which `.encode("utf-8")` would reject.
"""

from __future__ import annotations

import hmac

from .logging import get_logger

logger = get_logger("provider_core.auth")


def token_matches(provided: str | bytes | None, expected: str | bytes) -> bool:
    """Constant-time equality for a bearer token. Never raises.

    Returns False for anything that is not a string/bytes, for a missing token,
    and for an empty expected value — an unconfigured secret must never match
    anything, including the empty string.
    """
    if not expected:
        return False
    if provided is None:
        return False
    if isinstance(provided, bytes):
        provided_bytes = provided
    elif isinstance(provided, str):
        try:
            provided_bytes = provided.encode("utf-8", "surrogateescape")
        except Exception:  # pragma: no cover - defensive
            return False
    else:
        return False

    if isinstance(expected, bytes):
        expected_bytes = expected
    else:
        try:
            expected_bytes = expected.encode("utf-8")
        except Exception:  # pragma: no cover - defensive
            return False

    if not expected_bytes or not provided_bytes:
        return False
    return hmac.compare_digest(provided_bytes, expected_bytes)


def bearer_from_header(value: str | None) -> str:
    """Extract the token from an `Authorization: Bearer <token>` header.

    Returns "" for a missing, empty, or non-Bearer value, so the caller always
    compares a string and never has to branch on the header's shape.
    """
    if not value:
        return ""
    prefix = "bearer "
    lowered = value[:len(prefix)].lower()
    if lowered != prefix:
        return ""
    return value[len(prefix):]
