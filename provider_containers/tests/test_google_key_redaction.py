"""The Google LLM engine must not put its API key in a URL (audit item 24).

`llm_worker/engines/google/client.py` built

    .../streamGenerateContent?alt=sse&key={api_key}
    .../models?key={api_key}

A query string reaches proxy logs, httpx exception text (`raise_for_status`
embeds the request URL) and — because both the streaming and listing error
paths put `str(e)` into a `TaskEvent(message=...)` that is streamed to the
backend and persisted on the job — the job record.

Google documents the `x-goog-api-key` header as the preferred form, so the key
moved there. `redact_api_key` is the belt-and-braces second layer for anything
that reaches a message by another route.
"""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from llm_worker.engines.google.client import (
    GOOGLE_API_BASE, GOOGLE_API_KEY_HEADER, GoogleProviderClient, redact_api_key,
)
from provider_core.models import InferenceRequest

KEY = "AIzaSyTESTKEY-do-not-leak-1234567890"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", KEY)
    return GoogleProviderClient(provider_id="google-test", runtime_config={})


class _FakeStream:
    """Minimal stand-in for httpx's streaming response context manager."""

    def __init__(self, lines=(), raise_exc=None, status=200):
        self._lines = list(lines)
        self._raise = raise_exc
        self.status_code = status
        self.requests = []

    async def __aenter__(self):
        if self._raise is not None:
            raise self._raise
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("POST", f"{GOOGLE_API_BASE}/x")
            raise httpx.HTTPStatusError(
                f"Client error '{self.status_code} Forbidden' for url "
                f"'{GOOGLE_API_BASE}/models/gemini-2.5-flash:streamGenerateContent?key={KEY}'",
                request=request,
                response=MagicMock(status_code=self.status_code),
            )

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _patch_client(monkeypatch, stream):
    calls = []
    holder = MagicMock()

    async def get_client():
        return holder

    def _stream(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return stream

    holder.stream = _stream
    holder.get = AsyncMock()
    holder.calls = calls
    shared = MagicMock()
    shared.get_client = get_client
    monkeypatch.setattr(
        "llm_worker.engines.google.client.get_http_client", lambda: shared
    )
    return holder


class TestKeyIsNotInTheUrl:
    @pytest.mark.asyncio
    async def test_inference_sends_the_key_as_a_header(self, client, monkeypatch):
        stream = _FakeStream(lines=['data: {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}'])
        holder = _patch_client(monkeypatch, stream)

        response = await client.inference(
            InferenceRequest(messages=[{"role": "user", "content": "hi"}], model="gemini-2.5-flash")
        )
        body = "".join([chunk async for chunk in response.body_iterator])

        call = holder.calls[0]
        assert KEY not in call["url"]
        assert "key=" not in call["url"]
        assert call["url"] == f"{GOOGLE_API_BASE}/models/gemini-2.5-flash:streamGenerateContent?alt=sse"
        assert call["headers"][GOOGLE_API_KEY_HEADER] == KEY
        events = [json.loads(line) for line in body.strip().split("\n") if line.strip()]
        assert [e["event"] for e in events] == ["delta", "completed"]

    @pytest.mark.asyncio
    async def test_list_models_sends_the_key_as_a_header(self, client, monkeypatch):
        holder = _patch_client(monkeypatch, _FakeStream())
        response = MagicMock()
        response.json.return_value = {
            "models": [
                {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]}
            ]
        }
        holder.get = AsyncMock(return_value=response)

        payload = await client.list_models()
        args, kwargs = holder.get.call_args
        assert KEY not in args[0]
        assert "key=" not in args[0]
        assert kwargs["headers"][GOOGLE_API_KEY_HEADER] == KEY
        assert payload["files"] == [{"path": "gemini-2.5-pro", "name": "gemini-2.5-pro"}]


class TestKeyIsRedactedFromMessages:
    def test_redact_replaces_every_occurrence(self):
        assert redact_api_key(f"url?key={KEY}&x", KEY) == "url?key=***REDACTED***&x"

    def test_redact_is_a_noop_without_a_secret(self):
        assert redact_api_key("nothing here", "") == "nothing here"

    @pytest.mark.asyncio
    async def test_failed_event_message_never_contains_the_key(self, client, monkeypatch):
        """The failure text is persisted on the job, so it must be clean."""
        stream = _FakeStream(status=403)
        _patch_client(monkeypatch, stream)

        response = await client.inference(
            InferenceRequest(messages=[{"role": "user", "content": "hi"}], model="gemini-2.5-flash")
        )
        body = "".join([chunk async for chunk in response.body_iterator])
        event = json.loads(body.strip())

        assert event["event"] == "failed"
        assert event["retryable"] is True
        assert KEY not in body
        assert "***REDACTED***" in event["message"]

    @pytest.mark.asyncio
    async def test_list_models_failure_does_not_log_the_key(self, client, monkeypatch, caplog):
        import logging

        holder = _patch_client(monkeypatch, _FakeStream())
        holder.get = AsyncMock(side_effect=RuntimeError(f"boom ?key={KEY}"))

        with caplog.at_level(logging.WARNING):
            payload = await client.list_models()

        assert KEY not in caplog.text
        assert payload["status"] == "success"
        assert payload["files"], "the fallback list must still be returned"
