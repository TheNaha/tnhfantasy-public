import json
from typing import Any, AsyncIterator, Dict, Optional

from infrastructure.logging import get_logger

logger = get_logger("provider_ndjson")


def _parse_line(raw_line: str, *, source: str) -> Optional[Dict[str, Any]]:
    line = raw_line.strip()
    if not line:
        return None

    try:
        payload = json.loads(line)
    except json.JSONDecodeError as error:
        logger.warning(
            "provider_ndjson_parse_error",
            source=source,
            line_length=len(line),
            error=str(error),
        )
        return None

    if not isinstance(payload, dict):
        return None

    return payload


async def iter_ndjson_payloads(
    chunks: AsyncIterator[bytes],
    *,
    source: str,
) -> AsyncIterator[Dict[str, Any]]:
    """Parse an NDJSON byte stream into JSON object payloads."""
    buffer = ""

    async for chunk in chunks:
        buffer += chunk.decode("utf-8")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            payload = _parse_line(line, source=source)
            if payload is not None:
                yield payload

    if buffer.strip():
        payload = _parse_line(buffer, source=f"{source}:tail")
        if payload is not None:
            yield payload
