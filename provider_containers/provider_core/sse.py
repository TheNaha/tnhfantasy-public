"""Server-Sent Events framing, shared by every streaming engine.

One parser, because the three LLM engines each had their own copy of the same
four lines and each of them was wrong in the same way:

    if line.startswith("data: "):
        data_str = line[6:]

SSE (and the EventSource spec every one of these vendors implements) permits
`data:{...}` with no space after the colon. `startswith("data: ")` rejects that
frame outright, and `line[6:]` would have cut its first byte had it matched — so
a no-space frame was dropped whole, mid-stream, with no error and no log. The
client sees the stream end early and the assistant's answer truncated at whatever
token the vendor happened to emit without the space.

`removeprefix("data:").lstrip()` is the correct read: the field name, then
optional leading whitespace, then the payload.

This module owns the framing only. Turning a payload into a `TaskEvent` stays in
each engine, because that mapping is genuinely per-vendor (`choices[].delta` vs
`content_block_delta` vs `candidates[].content.parts`). It also owns the
cancellation probe, which was a third identical copy: every line, of every
engine, awaited `job_tracker.is_cancelled(job_id)`.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, List, Optional

from .logging import get_logger

logger = get_logger("provider_core.sse")

#: The OpenAI-style end-of-stream sentinel. Compared against the *payload*, not
#: the raw line, so `data:[DONE]` terminates as readily as `data: [DONE]`.
SSE_DONE = "[DONE]"


def sse_payload(line: str) -> Optional[str]:
    """The payload of one `data:` SSE line, or `None` if it is not a data line.

    Accepts `data:`, `data:{...}`, `data:  {...}` and `data: [DONE]` alike. The
    engine should compare the result to `SSE_DONE` rather than string-matching
    the line, which is what made the no-space form miss the sentinel.

    Only the *front* of the line is normalised. It used to `strip()` the whole
    line, so a payload whose JSON legitimately ends in whitespace lost it — and
    `.strip()` is exactly the kind of fix that reads as defensive and is not: a
    trailing `\n` or space is part of the payload the sender wrote, and the JSON
    grammar permits whitespace there, so removing it changes bytes the sender
    chose. The line terminator is dropped (it is framing, not payload) and the
    leading run is dropped only to find the field name; the payload is then taken
    from there, so its tail survives.
    """
    candidate = line.rstrip("\r\n").lstrip()
    if not candidate.startswith("data:"):
        return None
    return candidate.removeprefix("data:").lstrip()


async def iter_sse_data(
    response: Any,
    *,
    job_id: Optional[str] = None,
    job_tracker: Any = None,
    on_cancelled: Any = None,
) -> AsyncIterator[str]:
    """Yield the payload of each `data:` frame in an SSE response.

    Yields **raw strings**, not parsed JSON: a frame that is not valid JSON is
    the vendor's business, and every caller wrapped its own `json.loads` in
    `except json.JSONDecodeError: pass`. Parsing here would either change that
    behaviour for all three engines or need a flag.

    A **frame is one or more `data:` lines**, dispatched by a blank line — the
    EventSource algorithm, and the reason this parser buffers. Each of the three
    engines used to yield every `data:` line on its own, so a frame split across
    two lines arrived as two half-frames. Reproduced against this module:

        payloads: ['{"choices":[{"delta":', '{"content":"Hi"}}]}']
        parsed:   [None, None]

    Both halves fail `json.loads`, so a conforming frame is dropped whole,
    mid-answer, with nothing logged — the same class of silent truncation the
    consolidation was meant to end. The spec joins the lines with `\\n`, and
    because JSON treats a newline as ordinary whitespace, the joined payload
    parses as the single object it was always meant to be. vLLM's multi-line JSON
    writer is the in-scope server that emits these.

    `[DONE]` is compared per line rather than per frame, so a vendor that sends
    it without a preceding blank line still terminates. A frame that ends up with
    no payload at all is skipped here rather than handed on as `""`, which
    `openai_compat` logged as `logger.error("Failed to decode JSON: ")` while
    anthropic and google skipped it — three engines, one behaviour wanted.

    `job_tracker`/`job_id` reproduce the cancellation probe the three copies each
    re-implemented: on every frame, check whether the job was cancelled, and if
    so call `on_cancelled()` and stop. Cancellation is only *observed* between
    frames — an unbounded generation still has to emit a frame for the probe to
    run — which is why the callers emit their own `cancelled` TaskEvent from
    `on_cancelled` and return immediately after. The probe runs per *frame*, so a
    frame split across two lines is one probe, not two.

    Lines that are not `data:` frames (`event:`, `:`, `id:`, `retry:`, blank
    keep-alives) are skipped here, so an engine never has to think about them
    again.
    """
    buffer: List[str] = []

    async def _take_cancelled() -> bool:
        """One cancellation probe per frame. True means stop the stream."""
        if not (job_id and job_tracker is not None):
            return False
        try:
            cancelled = await job_tracker.is_cancelled(job_id)
        except Exception as exc:  # pragma: no cover - tracker is best-effort
            logger.warning(f"sse_cancellation_probe_failed job_id={job_id} error={exc}")
            return False
        if not cancelled:
            return False
        if on_cancelled is not None:
            await on_cancelled()
        return True

    async for raw_line in response.aiter_lines():
        if raw_line.strip():
            one = sse_payload(raw_line)
            if one is None:
                continue
            if one == SSE_DONE:
                # A vendor that omits the blank line before the sentinel must not
                # lose the frame sitting in the buffer — that is the last delta of
                # the answer. Flush it, then stop.
                if buffer:
                    trailing = "\n".join(buffer)
                    buffer.clear()
                    if trailing.strip() and not await _take_cancelled():
                        yield trailing
                return
            buffer.append(one)
            continue

        # A blank line is the spec's dispatch boundary: everything buffered so far
        # is one frame.
        if not buffer:
            continue
        payload = "\n".join(buffer)
        buffer.clear()
        if not payload.strip():
            # A bare `data:` line with nothing after it. See the docstring.
            continue
        if await _take_cancelled():
            return
        yield payload

    # End of stream with a frame still buffered. `data: [DONE]` on its own line is
    # handled above, so reaching here means the server closed without a trailing
    # blank line — a legal ending, and dropping the frame would lose the last
    # delta of the answer.
    if buffer:
        payload = "\n".join(buffer)
        buffer.clear()
        if payload.strip() and not await _take_cancelled():
            yield payload


def parse_sse_json(payload: str) -> Optional[dict]:
    """`json.loads` for an SSE payload, or `None` when the frame is not JSON.

    Every engine already did this with a bare `except json.JSONDecodeError:
    pass`; the point of wrapping it is that a truncated frame and a non-JSON
    keep-alive look identical to the caller and neither should raise.
    """
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None