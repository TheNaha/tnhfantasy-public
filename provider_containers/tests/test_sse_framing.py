"""SSE framing, shared by the three LLM engines.

Each engine carried its own copy of `if line.startswith("data: "): data_str =
line[6:]`, and all three dropped a frame the spec allows. `provider_core/sse.py`
now owns the framing; these tests pin the rule rather than any one engine's
wiring.
"""

import json

import pytest

from provider_core.sse import (
    SSECancelled,
    iter_sse_data,
    parse_sse_json,
    sse_payload,
)


class FakeResponse:
    """The one method `iter_sse_data` uses from a streaming response.

    Takes the whole frame list, blank-line separators and all: a real SSE server
    terminates every event with a blank line, and that is what tells the parser
    where one frame ends. The tests below therefore pass frames the way a server
    emits them.
    """

    def __init__(self, lines):
        self.lines = list(lines)

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class FakeTracker:
    def __init__(self, cancelled=False):
        self.cancelled = cancelled
        self.probes = 0

    async def is_cancelled(self, job_id):
        self.probes += 1
        return self.cancelled


class TestSsePayload:
    """`data:` framing. The bug: only the space-bearing form was accepted."""

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            # The regression: SSE permits `data:{...}` with no space. The old
            # `startswith("data: ")` rejected it, so the frame was lost whole,
            # mid-stream, with no error — a truncated answer.
            ("data:{}", "{}"),
            ("data: {\"a\": 1}", "{\"a\": 1}"),
            # Multiple spaces are legal too.
            ("data:    {}", "{}"),
            # The sentinel, both spellings — compared as a payload now, which is
            # what makes `data:[DONE]` terminate the way `data: [DONE]` did.
            ("data: [DONE]", "[DONE]"),
            ("data:[DONE]", "[DONE]"),
        ],
    )
    def test_data_frame_payloads(self, line, expected):
        assert sse_payload(line) == expected

    def test_a_no_space_frame_keeps_its_first_byte(self):
        """The specific failure mode: `line[6:]` would have eaten the `{`."""
        payload = sse_payload('data:{"choices":[]}')
        assert payload.startswith("{"), "the opening brace was consumed as if it were a space"
        assert json.loads(payload) == {"choices": []}

    @pytest.mark.parametrize(
        "line",
        ["", "   ", "event: message", ": keep-alive comment", "id: 7", "retry: 1000"],
    )
    def test_non_data_lines_are_skipped(self, line):
        assert sse_payload(line) is None


class TestIterSseData:
    @pytest.mark.asyncio
    async def test_yields_payloads_in_order(self):
        resp = FakeResponse(
            [
                "event: message",
                "",
                'data: {"n": 1}',
                "",
                ": keep-alive",
                "",
                'data: {"n": 2}',
                "",
            ]
        )
        out = [p async for p in iter_sse_data(resp)]
        assert [json.loads(p)["n"] for p in out] == [1, 2]

    @pytest.mark.asyncio
    async def test_done_sentinel_ends_the_stream_in_both_spellings(self):
        for sentinel in ("data: [DONE]", "data:[DONE]"):
            resp = FakeResponse(['data: {"n": 1}', "", sentinel, "", 'data: {"n": 2}', ""])
            out = [p async for p in iter_sse_data(resp)]
            assert [json.loads(p)["n"] for p in out] == [1], sentinel

    @pytest.mark.asyncio
    async def test_cancellation_is_observed_and_stops_the_stream(self):
        """The probe each of the three copies re-implemented, once."""
        tracker = FakeTracker(cancelled=True)
        seen = []

        async def _on_cancelled():
            seen.append("cancelled")

        resp = FakeResponse(['data: {"n": 1}', "", 'data: {"n": 2}', ""])
        out = [
            p
            async for p in iter_sse_data(
                resp, job_id="j1", job_tracker=tracker, on_cancelled=_on_cancelled
            )
        ]
        # The probe runs on the first frame, before that frame is yielded, so no
        # *vendor* content comes out — matching what each engine did.
        #
        # What DOES come out is an `SSECancelled` carrying whatever `on_cancelled`
        # built. This used to be `assert out == []`: the probe called
        # `await on_cancelled()` and discarded the return value, so the frame the
        # engines had just constructed was dropped and their `async for` simply
        # ended — into the post-loop `yield TaskEvent(event="completed")`. A
        # cancelled LLM job was recorded as a success with a half-written
        # assistant message committed to the chat. See `provider_core.sse`.
        assert [p for p in out if not isinstance(p, SSECancelled)] == []
        assert sum(isinstance(p, SSECancelled) for p in out) == 1
        assert seen == ["cancelled"]
        assert tracker.probes == 1

    @pytest.mark.asyncio
    async def test_cancelled_flag_on_a_later_frame_stops_after_that_frame(self):
        class CancelSecond(FakeTracker):
            async def is_cancelled(self, job_id):
                self.probes += 1
                return self.probes > 1

        tracker = CancelSecond()
        seen = []

        async def _on_cancelled():
            seen.append("cancelled")

        resp = FakeResponse(
            ['data: {"n": 1}', "", 'data: {"n": 2}', "", 'data: {"n": 3}', ""]
        )
        out = [
            p
            async for p in iter_sse_data(
                resp, job_id="j1", job_tracker=tracker, on_cancelled=_on_cancelled
            )
        ]
        payloads = [p for p in out if not isinstance(p, SSECancelled)]
        assert [json.loads(p)["n"] for p in payloads] == [1]
        assert sum(isinstance(p, SSECancelled) for p in out) == 1
        assert seen == ["cancelled"]

    @pytest.mark.asyncio
    async def test_no_tracker_means_no_probe(self):
        resp = FakeResponse(['data: {"n": 1}', ""])
        out = [p async for p in iter_sse_data(resp, job_id="j1")]
        assert len(out) == 1


class TestAMultiLineFrameIsOneFrame:
    """The defect: consecutive `data:` lines are ONE frame, joined with `\\n`.

    The parser yielded each `data:` line on its own, so a frame split across two
    lines arrived as two half-frames. Both fail `json.loads`, so a conforming
    frame is dropped whole, mid-answer, with nothing logged:

        payloads: ['{"choices":[{"delta":', '{"content":"Hi"}}]}']
        parsed:   [None, None]

    vLLM's multi-line JSON writer emits exactly this, and the joined payload is
    the single object it was always meant to be — JSON treats a newline as
    ordinary whitespace, which is why joining is not merely lossless but correct.
    """

    @pytest.mark.asyncio
    async def test_the_auditors_reproduction_now_parses(self):
        resp = FakeResponse(
            [
                'data: {"choices":[{"delta":',
                'data: {"content":"Hi"}}]}',
                "",
            ]
        )
        payloads = [p async for p in iter_sse_data(resp)]

        assert len(payloads) == 1, f"the frame was split: {payloads}"
        parsed = parse_sse_json(payloads[0])
        assert parsed is not None, f"still unparseable: {payloads[0]!r}"
        assert parsed["choices"][0]["delta"]["content"] == "Hi"

    @pytest.mark.asyncio
    async def test_three_lines_join_into_one_payload(self):
        resp = FakeResponse(
            [
                'data: {"choices":[{"delta":',
                'data:  {"content":',
                'data: "Hi"}}]}',
                "",
            ]
        )
        payloads = [p async for p in iter_sse_data(resp)]
        assert len(payloads) == 1, payloads
        assert parse_sse_json(payloads[0])["choices"][0]["delta"]["content"] == "Hi"

    @pytest.mark.asyncio
    async def test_a_multi_line_frame_probes_cancellation_once(self):
        """Two `data:` lines are one frame, so one probe — not two.

        Probing per line would let a job cancel itself halfway through a single
        vendor frame and truncate that frame's content.
        """
        tracker = FakeTracker(cancelled=True)

        resp = FakeResponse(
            ['data: {"choices":[{"delta":', 'data: {"content":"Hi"}}]}', ""]
        )
        out = [
            p
            async for p in iter_sse_data(resp, job_id="j1", job_tracker=tracker)
        ]
        # The truncated frame is never yielded. A cancellation marker IS, so the
        # caller can close the job out as cancelled rather than falling through
        # to its post-loop "completed".
        assert [p for p in out if not isinstance(p, SSECancelled)] == []
        assert sum(isinstance(p, SSECancelled) for p in out) == 1
        assert tracker.probes == 1, tracker.probes

    @pytest.mark.asyncio
    async def test_a_multi_line_frame_does_not_leak_into_the_next_one(self):
        resp = FakeResponse(
            [
                'data: {"n": 1,',
                'data: "part": "a"}',
                "",
                'data: {"n": 2}',
                "",
            ]
        )
        payloads = [p async for p in iter_sse_data(resp)]
        assert [json.loads(p)["n"] for p in payloads] == [1, 2]
        assert json.loads(payloads[0])["part"] == "a"

    @pytest.mark.asyncio
    async def test_the_final_frame_survives_a_missing_trailing_blank_line(self):
        """A server that closes the connection without a last blank line loses the
        last delta otherwise — the answer is truncated at whatever token came
        second-to-last."""
        resp = FakeResponse(['data: {"n": 1}', "", 'data: {"n": 2}'])
        out = [p async for p in iter_sse_data(resp)]
        assert [json.loads(p)["n"] for p in out] == [1, 2]

    @pytest.mark.asyncio
    async def test_done_without_a_leading_blank_line_still_terminates(self):
        """`[DONE]` is compared per line, so a vendor that omits the separator
        before the sentinel does not have its last frame merged into it."""
        resp = FakeResponse(['data: {"n": 1}', "", 'data: {"n": 2}', "data: [DONE]", "", 'data: {"n": 3}', ""])
        out = [p async for p in iter_sse_data(resp)]
        assert [json.loads(p)["n"] for p in out] == [1, 2]

    @pytest.mark.asyncio
    async def test_a_bare_data_line_yields_nothing(self):
        """A frame with no payload is skipped here, not handed on as `""`.

        `openai_compat` logged `logger.error("Failed to decode JSON: ")` for it
        while anthropic and google skipped it silently. One behaviour, wanted by
        all three.
        """
        resp = FakeResponse(["data:", "", 'data: {"n": 1}', ""])
        out = [p async for p in iter_sse_data(resp)]
        assert [json.loads(p)["n"] for p in out] == [1]
        assert "" not in out


class TestPayloadWhitespaceIsNotRewritten:
    def test_a_trailing_space_survives(self):
        """`.strip()` on the whole line ate bytes the sender wrote.

        Whitespace is legal inside a JSON document, so removing it changes the
        payload rather than tidying it. Only the line terminator is framing.
        """
        assert sse_payload('data: {"a": 1} ') == '{"a": 1} '
        assert sse_payload('data: {"a": 1}\n') == '{"a": 1}'

    def test_leading_whitespace_is_still_stripped_from_the_payload(self):
        """The optional space after the colon is framing, not content."""
        assert sse_payload("data:   {\"a\": 1}") == '{"a": 1}'


class TestParseSseJson:
    def test_parses_an_object(self):
        assert parse_sse_json('{"a": 1}') == {"a": 1}

    @pytest.mark.parametrize("payload", ["", "not json", "{", "[1, 2]"])
    def test_non_object_or_broken_payloads_are_none_not_exceptions(self, payload):
        """Every engine wrapped its own `json.loads` in `except JSONDecodeError`.

        A truncated frame must stay indistinguishable from a vendor keep-alive,
        so this returns None rather than raising.
        """
        assert parse_sse_json(payload) is None


class TestEnginesUseTheSharedParser:
    """The three engines must not reintroduce a private `startswith("data: ")`.

    A transcribing test — "assert the file contains `removeprefix`" — would pass
    while a fourth copy sat next to it. This states the property instead: no
    engine may slice a `data:` line itself.
    """

    ENGINES = (
        "llm_worker/engines/openai_compat/client.py",
        "llm_worker/engines/anthropic/client.py",
        "llm_worker/engines/google/client.py",
    )

    @pytest.mark.parametrize("relpath", ENGINES)
    def test_no_hand_rolled_data_prefix_handling(self, relpath):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / relpath).read_text()
        assert 'startswith("data: ' not in source, (
            f"{relpath} re-implements the SSE frame prefix; use provider_core.sse"
        )
        assert "line[6:]" not in source, f"{relpath} slices the data: prefix by offset"

    @pytest.mark.parametrize("relpath", ENGINES)
    def test_each_engine_imports_the_shared_helper(self, relpath):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / relpath).read_text()
        assert "iter_sse_data" in source, f"{relpath} does not use the shared parser"


class TestNoSpaceFrameReachesTheClient:
    """End to end through a real engine, because the unit test above only proves
    the helper.

    The user-visible symptom was an assistant answer truncated at whatever token
    the vendor happened to emit without a space, with nothing logged. Asserting
    the text arrives is the only version of this that is about the defect.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "frame",
        ['data:{"choices":[{"delta":{"content":"Hel"}}]}', 'data: {"choices":[{"delta":{"content":"Hel"}}]}'],
        ids=["no-space", "with-space"],
    )
    async def test_openai_compat_streams_a_no_space_frame(self, monkeypatch, frame):
        from llm_worker.engines.openai_compat.client import OpenAICompatProviderClient
        from provider_core.models import InferenceRequest

        client = OpenAICompatProviderClient(provider_id="test", runtime_config={})

        class Resp(FakeResponse):
            def raise_for_status(self):
                pass

        class Ctx:
            async def __aenter__(self):
                return Resp([frame, "", 'data:{"choices":[{"delta":{"content":"lo"}}]}', "", "data: [DONE]", ""])

            async def __aexit__(self, *args):
                return False

        class Http:
            def stream(self, *a, **kw):
                return Ctx()

        class HttpClient:
            async def get_client(self):
                return Http()

        import llm_worker.engines.openai_compat.client as mod

        monkeypatch.setattr(mod, "get_http_client", lambda: HttpClient())

        response = await client.inference(
            InferenceRequest(messages=[{"role": "user", "content": "Hi"}], model="m", job_id="j-sse")
        )
        body = "".join([c async for c in response.body_iterator])
        events = [json.loads(line) for line in body.strip().split("\n") if line.strip()]

        assert [e["event"] for e in events] == ["delta", "delta", "completed"], (
            "a frame the spec permits was dropped mid-stream"
        )
        assert "".join(e["text"] for e in events if e["event"] == "delta") == "Hello"


class TestAMultiLineFrameReachesTheClient:
    """The multi-line case, end to end, because that is the whole symptom.

    An auditor's reproduction of the defect against the shared module alone:

        multi-line frame payloads: ['{"choices":[{"delta":', '{"content":"Hi"}}]}']
        parsed:                    [None, None]

    Both halves failed `json.loads`, so the frame was dropped and the answer came
    back empty. This drives the real engine so the assertion is about the text the
    user receives, not about a helper's return value.
    """

    @pytest.mark.asyncio
    async def test_openai_compat_streams_a_multi_line_frame(self, monkeypatch):
        from llm_worker.engines.openai_compat.client import OpenAICompatProviderClient
        from provider_core.models import InferenceRequest

        client = OpenAICompatProviderClient(provider_id="test", runtime_config={})

        lines = [
            'data: {"choices":[{"delta":',
            'data: {"content":"Hel"}}]}',
            "",
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            "",
            "data: [DONE]",
            "",
        ]

        class Resp(FakeResponse):
            def raise_for_status(self):
                pass

        class Ctx:
            async def __aenter__(self):
                return Resp(lines)

            async def __aexit__(self, *args):
                return False

        class Http:
            def stream(self, *a, **kw):
                return Ctx()

        class HttpClient:
            async def get_client(self):
                return Http()

        import llm_worker.engines.openai_compat.client as mod

        monkeypatch.setattr(mod, "get_http_client", lambda: HttpClient())

        response = await client.inference(
            InferenceRequest(messages=[{"role": "user", "content": "Hi"}], model="m", job_id="j-sse")
        )
        body = "".join([c async for c in response.body_iterator])
        events = [json.loads(line) for line in body.strip().split("\n") if line.strip()]

        assert "".join(e["text"] for e in events if e["event"] == "delta") == "Hello", (
            f"the split frame was dropped, so the answer was truncated: {events}"
        )
        assert [e["event"] for e in events] == ["delta", "delta", "completed"]


class TestABareDataFrameIsNotAnEngineError:
    """`openai_compat` logged `logger.error("Failed to decode JSON: ")` for an empty
    payload while anthropic and google skipped it silently. One behaviour."""

    @pytest.mark.asyncio
    async def test_openai_compat_does_not_log_an_error_for_an_empty_frame(
        self, monkeypatch, caplog
    ):
        import logging

        from llm_worker.engines.openai_compat.client import OpenAICompatProviderClient
        from provider_core.models import InferenceRequest

        client = OpenAICompatProviderClient(provider_id="test", runtime_config={})

        class Resp(FakeResponse):
            def raise_for_status(self):
                pass

        class Ctx:
            async def __aenter__(self):
                return Resp(
                    ["data:", "", 'data: {"choices":[{"delta":{"content":"Hi"}}]}', "", "data: [DONE]", ""]
                )

            async def __aexit__(self, *args):
                return False

        class Http:
            def stream(self, *a, **kw):
                return Ctx()

        class HttpClient:
            async def get_client(self):
                return Http()

        import llm_worker.engines.openai_compat.client as mod

        monkeypatch.setattr(mod, "get_http_client", lambda: HttpClient())

        errors = []

        class _Collect(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    errors.append(record.getMessage())

        handler = _Collect()
        client.logger.addHandler(handler)
        previous = client.logger.level
        client.logger.setLevel(logging.DEBUG)
        try:
            response = await client.inference(
                InferenceRequest(
                    messages=[{"role": "user", "content": "Hi"}], model="m", job_id="j-sse"
                )
            )
            body = "".join([c async for c in response.body_iterator])
        finally:
            client.logger.removeHandler(handler)
            client.logger.setLevel(previous)

        assert errors == [], f"an empty frame was logged as an error: {errors}"
        events = [json.loads(line) for line in body.strip().split("\n") if line.strip()]
        assert "".join(e["text"] for e in events if e["event"] == "delta") == "Hi"