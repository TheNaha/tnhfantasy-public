"""A model file must never be materialised in memory just to be served.

`HttpFileProxy.get_file` returns `bytes`, and that is a second full copy of
whatever the provider sends: the worker holds it, the response holds it, and on the
base64 JSON path the engines still use for small payloads there is a 1.33x string
on top. A 7 GB SDXL checkpoint cannot survive it.

So `stream_file` is the path for anything large, and `get_file` refuses past
`MAX_INLINE_FILE_BYTES` with a `FileTooLargeError` rather than trying and failing
in a way that looks like an OOM.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

from infrastructure.providers.base import MAX_INLINE_FILE_BYTES
from infrastructure.providers.provider_registry import (
    FileTooLargeError,
    HttpFileProxy,
    _STREAM_CHUNK_BYTES,
)


def _upstream() -> tuple[FastAPI, dict]:
    app = FastAPI()
    state = {"served": 0}

    async def body():
        # 3 MiB, in 1 MiB chunks, so a buffered reader is obvious.
        for _ in range(3):
            chunk = b"y" * (1024 * 1024)
            state["served"] += len(chunk)
            yield chunk

    @app.get("/get-file/{path:path}")
    async def get_file(path: str):
        return StreamingResponse(body(), media_type="application/octet-stream")

    return app, state


@pytest.mark.asyncio
async def test_stream_file_yields_the_body_in_bounded_chunks(monkeypatch):
    app, state = _upstream()
    import infrastructure.providers.provider_registry as registry

    real_client = AsyncClient(transport=ASGITransport(app=app))
    monkeypatch.setattr(registry, "get_http_client", lambda: real_client)

    proxy = HttpFileProxy("p1", {}, "http://provider")
    received = bytearray()
    async for chunk in proxy.stream_file("models/checkpoints/big.safetensors"):
        assert len(chunk) <= _STREAM_CHUNK_BYTES
        received += chunk
    await real_client.aclose()

    assert len(received) == 3 * 1024 * 1024
    assert state["served"] == len(received)


@pytest.mark.asyncio
async def test_get_file_refuses_a_file_past_the_inline_limit(monkeypatch):
    app, _ = _upstream()
    declared = MAX_INLINE_FILE_BYTES + 1

    class _Transport(ASGITransport):
        async def handle_async_request(self, request):
            response = await super().handle_async_request(request)
            response.headers["content-length"] = str(declared)
            return response

    real_client = AsyncClient(transport=_Transport(app=app))
    import infrastructure.providers.provider_registry as registry

    monkeypatch.setattr(registry, "get_http_client", lambda: real_client)

    proxy = HttpFileProxy("p1", {}, "http://provider")
    with pytest.raises(FileTooLargeError) as excinfo:
        await proxy.get_file("models/checkpoints/huge.safetensors")
    await real_client.aclose()

    assert "stream_file" in str(excinfo.value)


@pytest.mark.asyncio
async def test_get_file_still_serves_a_small_file(monkeypatch):
    """The bytes API is not dead — sidecars and thumbnails go through it."""
    app = FastAPI()

    @app.get("/get-file/{path:path}")
    async def get_file(path: str):
        return {"content_base64": "aGVsbG8="}

    real_client = AsyncClient(transport=ASGITransport(app=app))
    import infrastructure.providers.provider_registry as registry

    monkeypatch.setattr(registry, "get_http_client", lambda: real_client)

    proxy = HttpFileProxy("p1", {}, "http://provider")
    assert await proxy.get_file("models/x.json") == b"hello"
    await real_client.aclose()


def test_http_file_proxy_implements_the_abstract_contract():
    """It never inherited FileProxyProvider, so the ABC was documentation rather
    than a contract and nothing checked that `stream_file` existed."""
    from infrastructure.providers.base import FileProxyProvider

    assert issubclass(HttpFileProxy, FileProxyProvider)
    assert not HttpFileProxy.__abstractmethods__
