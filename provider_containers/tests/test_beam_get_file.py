"""`beam_app`'s `/get-file` and the Beam client's read of it (audit item 11).

The app did a blocking `open(full_path, "rb").read()` of the whole file inside
an `async def`, which blocks the storage deployment's event loop for the length
of the transfer and holds the entire file in RAM. The client then buffered that
body again and base64-decoded a third copy for the JSON variant.

Note the *auth* half of audit item 11 is UNVERIFIED from the repo: whether
beta9's gateway authenticates a deployment URL independently cannot be
determined from this codebase, so nothing here claims to have fixed it. What is
tested is the part that can be proven.
"""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException

from provider_core.http_client import (
    DEFAULT_GET_FILE_SIZE_CAP, get_file_size_cap, relay_bytes,
)


class _ChunkedResponse:
    """An httpx.Response whose body arrives in chunks, with no .content."""

    def __init__(self, chunks, headers=None, status_code=200):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.closed = False

    def aiter_bytes(self, chunk_bytes=None):
        async def gen():
            for chunk in self._chunks:
                yield chunk

        return gen()

    async def aclose(self):
        self.closed = True

    async def aread(self):
        return b"".join(self._chunks)


def _fake_http(response):
    http = MagicMock()
    http.send = AsyncMock(return_value=response)
    return http


def _client(monkeypatch, response, cap=None):
    import image_worker.engines.beam.client as beam_client

    client = beam_client.BeamProviderClient(runtime_config={})
    http = _fake_http(response)
    shared = MagicMock()
    shared.get_client = AsyncMock(return_value=http)
    monkeypatch.setattr(beam_client, "get_http_client", lambda: shared)
    if cap is not None:
        monkeypatch.setattr(beam_client, "get_file_size_cap", lambda: cap)
    return client, http


class TestRelayBytes:
    @pytest.mark.asyncio
    async def test_passes_chunks_through(self):
        response = _ChunkedResponse([b"a" * 10, b"b" * 10])
        out = [c async for c in relay_bytes(response, 1000, chunk_bytes=8)]
        assert b"".join(out) == b"a" * 10 + b"b" * 10
        assert response.closed, "the upstream must be released"

    @pytest.mark.asyncio
    async def test_enforces_the_ceiling(self):
        response = _ChunkedResponse([b"x" * 100, b"x" * 100])
        with pytest.raises(httpx.RequestError):
            [c async for c in relay_bytes(response, 150)]
        assert response.closed

    @pytest.mark.asyncio
    async def test_a_lying_content_length_is_caught_by_the_stream(self):
        response = _ChunkedResponse([b"x" * 5000], headers={"content-length": "10"})
        with pytest.raises(httpx.RequestError):
            [c async for c in relay_bytes(response, 100)]


class TestGetFileSizeCap:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("PROVIDER_GET_FILE_MAX_BYTES", raising=False)
        assert get_file_size_cap() == DEFAULT_GET_FILE_SIZE_CAP

    def test_override(self, monkeypatch):
        monkeypatch.setenv("PROVIDER_GET_FILE_MAX_BYTES", "1234")
        assert get_file_size_cap() == 1234

    def test_junk_override_falls_back(self, monkeypatch):
        monkeypatch.setenv("PROVIDER_GET_FILE_MAX_BYTES", "not-a-number")
        assert get_file_size_cap() == DEFAULT_GET_FILE_SIZE_CAP


class TestBeamClientGetFile:
    @pytest.mark.asyncio
    async def test_streams_rather_than_buffering(self, monkeypatch):
        response = _ChunkedResponse(
            [b"x" * 100, b"y" * 100],
            headers={"content-type": "application/octet-stream", "content-length": "200"},
        )
        client, _ = _client(monkeypatch, response)
        result = await client.get_file("models/a.safetensors")
        body = b"".join([chunk async for chunk in result.body_iterator])
        assert body == b"x" * 100 + b"y" * 100
        assert response.closed

    @pytest.mark.asyncio
    async def test_rejects_an_oversized_declared_length(self, monkeypatch):
        response = _ChunkedResponse(
            [b"x" * 10], headers={"content-type": "application/octet-stream", "content-length": "99999"}
        )
        client, _ = _client(monkeypatch, response, cap=100)
        with pytest.raises(HTTPException) as exc:
            await client.get_file("models/big.safetensors")
        assert exc.value.status_code == 413
        assert response.closed

    @pytest.mark.asyncio
    async def test_rejects_a_body_that_overshoots_without_a_length(self, monkeypatch):
        response = _ChunkedResponse(
            [b"x" * 4096], headers={"content-type": "application/octet-stream"}
        )
        client, _ = _client(monkeypatch, response, cap=100)
        result = await client.get_file("models/big.safetensors")
        with pytest.raises(httpx.RequestError):
            [chunk async for chunk in result.body_iterator]
        assert response.closed

    @pytest.mark.asyncio
    async def test_404_maps_to_404(self, monkeypatch):
        response = _ChunkedResponse([b""], status_code=404)
        client, _ = _client(monkeypatch, response)
        with pytest.raises(HTTPException) as exc:
            await client.get_file("models/missing")
        assert exc.value.status_code == 404
        assert response.closed

    @pytest.mark.asyncio
    async def test_5xx_maps_to_502(self, monkeypatch):
        response = _ChunkedResponse([b"boom"], status_code=503)
        client, _ = _client(monkeypatch, response)
        with pytest.raises(HTTPException) as exc:
            await client.get_file("models/a")
        assert exc.value.status_code == 502

    @pytest.mark.asyncio
    async def test_decodes_the_base64_variant_within_the_cap(self, monkeypatch):
        import base64

        body = b"hello-bytes"
        payload = {"content_base64": base64.b64encode(body).decode(), "media_type": "image/png"}
        response = _ChunkedResponse(
            [__import__("json").dumps(payload).encode()],
            headers={"content-type": "application/json"},
        )
        client, _ = _client(monkeypatch, response, cap=10_000)
        result = await client.get_file("output/a.png")
        assert result.body == body
        assert result.media_type == "image/png"

    @pytest.mark.asyncio
    async def test_refuses_a_oversized_base64_payload(self, monkeypatch):
        import base64
        import json as _json

        payload = {"content_base64": base64.b64encode(b"x" * 5000).decode()}
        response = _ChunkedResponse(
            [_json.dumps(payload).encode()], headers={"content-type": "application/json"}
        )
        client, _ = _client(monkeypatch, response, cap=100)
        with pytest.raises(HTTPException) as exc:
            await client.get_file("models/big")
        assert exc.value.status_code == 413


class TestBeamAppGetFileSource:
    def test_no_blocking_read_in_the_handler(self):
        """`open(...).read()` of the whole file inside `async def` blocked the
        storage container's event loop for the length of every transfer."""
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "image_worker/engines/beam/beam_app.py"
        ).read_text()
        tree = ast.parse(source)
        handlers = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_file"
        ]
        assert len(handlers) == 1
        handler = handlers[0]
        calls = [
            child
            for child in ast.walk(handler)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "open"
        ]
        assert not calls, "get_file still opens the file itself"
        returns = [
            child
            for child in ast.walk(handler)
            if isinstance(child, ast.Return) and isinstance(child.value, ast.Call)
        ]
        assert any(
            isinstance(r.value.func, ast.Name) and r.value.func.id == "FileResponse"
            for r in returns
        ), "get_file must stream with FileResponse"

    def test_the_app_imports_the_shared_cap(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "image_worker/engines/beam/beam_app.py"
        ).read_text()
        assert "get_file_size_cap" in source
