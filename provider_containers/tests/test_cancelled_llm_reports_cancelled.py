"""A cancelled LLM job must not be reported as `completed`.

`provider_core.sse.iter_sse_data` runs one cancellation probe per SSE frame. On a
hit it called `await on_cancelled()` — and threw the return value away.

Every LLM engine implements `on_cancelled` as a coroutine that *builds* the
frame:

    async def _cancelled() -> str:
        return TaskEvent(
            event="cancelled", job_id=job_id,
            outputs=[{"role": "assistant", "content": full_content, "cancelled": True}],
        ).to_ndjson()

So the frame was constructed, returned, and dropped. The `async for` in the
engine simply ended, and control fell through to the engine's post-loop
`yield TaskEvent(event="completed", ...)`. The backend's `_LLMReducer` decides
success from `outputs[0]["cancelled"]`
(`backend_v2/services/provider_client.py`), a key the completed frame does not
carry — so the job landed SUCCESS with a half-written assistant message
committed to the chat transcript.

Reproduced on the shared framing module before the fix, and by extension on all
three engines that use it (`openai_compat`, `anthropic`, `google`): events were
`['delta', 'delta', 'completed']` with
`{"role": "assistant", "content": "I love "}` and no cancellation marker.

The fix is `SSECancelled`, a distinct yielded type. A bare string would not do:
the engines parse each frame as a vendor payload, and a `cancelled` TaskEvent has
no `choices`, so it would have been skipped and the same fall-through would have
happened one layer down.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from provider_core.models import TaskEvent
from provider_core.sse import SSECancelled, iter_sse_data, parse_sse_json


class FakeResponse:
    def __init__(self, lines):
        self._lines = list(lines)

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeTracker:
    def __init__(self, cancelled=True):
        self._cancelled = cancelled
        self.probes = 0

    async def is_cancelled(self, job_id):
        self.probes += 1
        return self._cancelled


DELTAS = [
    'data: {"choices":[{"delta":{"content":"I love "}}]}',
    "",
    'data: {"choices":[{"delta":{"content":"this."}}]}',
    "",
    "data: [DONE]",
    "",
]


async def collect(resp, tracker, on_cancelled=None):
    return [
        frame
        async for frame in iter_sse_data(
            resp, job_id="job-1", job_tracker=tracker, on_cancelled=on_cancelled
        )
    ]


class TestCancellationIsReportedNotSwallowed:
    @pytest.mark.asyncio
    async def test_a_cancelled_frame_reaches_the_caller(self):
        partial = "I love "

        async def on_cancelled():
            return TaskEvent(
                event="cancelled",
                job_id="job-1",
                outputs=[{"role": "assistant", "content": partial, "cancelled": True}],
            ).to_ndjson()

        frames = await collect(FakeResponse(DELTAS), FakeTracker(), on_cancelled)

        markers = [f for f in frames if isinstance(f, SSECancelled)]
        assert len(markers) == 1, "the cancellation must be yielded, not discarded"
        assert markers[0].ndjson is not None, "the frame the engine built was dropped"

    @pytest.mark.asyncio
    async def test_the_backend_can_tell_cancelled_from_completed(self):
        """The decision the backend actually makes."""

        async def on_cancelled():
            return TaskEvent(
                event="cancelled",
                job_id="job-1",
                outputs=[{"role": "assistant", "content": "I love ", "cancelled": True}],
            ).to_ndjson()

        frames = await collect(FakeResponse(DELTAS), FakeTracker(), on_cancelled)
        marker = next(f for f in frames if isinstance(f, SSECancelled))

        payload = parse_sse_json(marker.ndjson)
        assert payload["event"] == "cancelled"
        assert payload["outputs"][0]["cancelled"] is True

        # And the completed frame — the one that used to be emitted instead —
        # does not carry the key, which is the whole bug.
        completed = TaskEvent(
            event="completed",
            job_id="job-1",
            outputs=[{"role": "assistant", "content": "I love "}],
        )
        assert "cancelled" not in json.loads(completed.to_ndjson())["outputs"][0]

    @pytest.mark.asyncio
    async def test_no_partial_vendor_frame_is_yielded_after_cancellation(self):
        frames = await collect(FakeResponse(DELTAS), FakeTracker(), lambda: None)
        assert [f for f in frames if not isinstance(f, SSECancelled)] == []

    @pytest.mark.asyncio
    async def test_an_uncancelled_stream_is_untouched(self):
        frames = await collect(FakeResponse(DELTAS), FakeTracker(cancelled=False))
        assert all(not isinstance(f, SSECancelled) for f in frames)
        assert [json.loads(f)["choices"][0]["delta"]["content"] for f in frames] == [
            "I love ",
            "this.",
        ]

    @pytest.mark.asyncio
    async def test_no_tracker_means_no_marker(self):
        frames = await collect(FakeResponse(DELTAS), None)
        assert all(not isinstance(f, SSECancelled) for f in frames)
        assert len(frames) == 2
