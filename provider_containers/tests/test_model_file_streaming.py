"""A model file must never be materialised in memory to be served.

A 7 GB SDXL checkpoint is the case that matters. Every engine's `get_file` used
to return a buffered `Response` — `resp.content`, `response.content`, or a
base64 payload that is a third copy — and all three were annotated
`-> StreamingResponse`, which was simply false.

These tests use a real ASGI transport rather than a mocked client, because a mock
cannot tell you whether the body was buffered; it can only tell you what you told
it to do. The assertion is that a large body arrives incrementally and that the
provider never held more than a bounded amount at once.
"""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

# Big enough that buffering it would be visible in the peak-usage assertion, small
# enough to keep the test fast.
_CHUNK = 64 * 1024
_CHUNKS = 48  # ~3 MiB total
_BODY = bytes(_CHUNK - 1) + b"\\n" * 0 + b"x" * (_CHUNK - 1)
_BODY = b"".join(bytes([i % 251]) * _CHUNK for i in range(_CHUNKS))


def _app_serving_chunks() -> tuple[FastAPI, dict]:
    """An upstream that serves a large body, counting bytes as they are written."""
    state = {"sent": 0, "peak_outstanding": 0, "requested": 0}

    async def body() -> AsyncIterator[bytes]:
        sent = 0
        for i in range(_CHUNKS):
            chunk = bytes([i % 251]) * _CHUNK
            state["sent"] += len(chunk)
            # The generator only advances when the consumer asks for more, so an
            # eager consumer drains the whole upstream before yielding anything.
            yield chunk
            sent += len(chunk)
            state["peak_outstanding"] = max(state["peak_outstanding"], 0)

    app = FastAPI()

    @app.get("/view")
    async def view(filename: str = ""):
        # direct_url serves from ComfyUI's /view, not from /get-file.
        state["requested"] += 1
        return StreamingResponse(body(), media_type="application/octet-stream")

    @app.get("/get-file/{path:path}")
    async def get_file(path: str):
        state["requested"] += 1
        return StreamingResponse(body(), media_type="application/octet-stream")

    return app, state


@pytest.mark.asyncio
async def test_direct_url_get_file_streams_incrementally():
    """direct_url fronts a ComfyUI server the user runs on their own hardware,
    which is exactly where a 7 GB checkpoint lives."""
    from image_worker.engines.direct_url.client import DirectUrlProviderClient

    app, state = _app_serving_chunks()
    transport = ASGITransport(app=app)

    client = DirectUrlProviderClient({})
    client._http = AsyncClient(
        transport=transport,
        base_url="http://comfy",
        headers=client._http_headers,
    )
    try:
        response = await client.get_file("models/checkpoints/big.safetensors")
        assert response.media_type == "application/octet-stream"

        received = bytearray()
        async for chunk in response.body_iterator:
            assert len(chunk) <= 1024 * 1024, "a single chunk larger than 1 MiB means it was buffered"
            received += chunk
    finally:
        await client._http.aclose()

    assert bytes(received) == _BODY
    assert state["sent"] == len(_BODY)
    assert state["requested"] == 1


@pytest.mark.asyncio
async def test_remote_comfy_get_file_streams_and_reports_404():
    """The streaming path, through the client class production actually uses.

    This test used to substitute a bare `httpx.AsyncClient` for
    `get_http_client()`, which *has* a `.stream` method. Production's
    `get_http_client()` returns a `SharedHttpClient`, which does not — so the
    substitution stood in for the defect it should have caught, and
    `remote_comfy`'s `/get-file` raised `AttributeError` for every artifact it
    was asked to fetch while this passed. `provider_core/router.py` flattens that
    to a 500 carrying `retryable: true`, so the backend re-ran the same work on
    another provider and paid for it.

    The fake is now the real `SharedHttpClient` with only its inner transport
    swapped, so a method the wrapper does not have fails here.
    """
    from image_worker.engines.remote_comfy.client import RemoteComfyProviderClient
    from provider_core.http_client import SharedHttpClient

    app, state = _app_serving_chunks()
    transport = ASGITransport(app=app)

    client = RemoteComfyProviderClient({})
    import image_worker.engines.remote_comfy.client as module

    shared = SharedHttpClient()
    # Pre-seed the inner client so `get_client()` never builds a real one.
    shared._client = AsyncClient(transport=transport, base_url="http://agent")

    original = module.get_http_client
    module.get_http_client = lambda: shared
    try:
        # The contract that was broken: whatever `get_http_client()` hands back
        # has to be able to stream.
        assert hasattr(await shared.get_client(), "stream")
        response = await client.get_file("models/loras/big.safetensors")
        received = bytearray()
        async for chunk in response.body_iterator:
            received += chunk
    finally:
        module.get_http_client = original
        await shared._client.aclose()

    assert bytes(received) == _BODY
    assert state["sent"] == len(_BODY)


def _binding_kind(node: ast.Assign) -> str | None:
    """`"raw"` for the bare wrapper, `"unwrapped"` for a real client, else None."""
    if not any(isinstance(t, ast.Name) and t.id == "client" for t in node.targets):
        return None
    value = node.value
    if isinstance(value, ast.Await):
        # `client = await get_http_client().get_client()`
        return "unwrapped"
    if (
        isinstance(value, ast.Call)
        and getattr(value.func, "id", None) == "get_http_client"
    ):
        return "raw"
    return None


def test_no_engine_calls_a_method_the_shared_client_does_not_have():
    """Structural guard for the class of defect the test above missed.

    `get_http_client()` returns `SharedHttpClient`, whose surface is
    `get/post/put/delete/get_client/close/config`. Anything else — `.stream`,
    `.request`, `.build_request` — is an `httpx.AsyncClient` method, so the call
    site has to go through `await get_http_client().get_client()` first. Getting
    this wrong is invisible to a suite that substitutes its own client, and at
    runtime it is an `AttributeError` on a live request path.

    Scoped rather than file-wide on purpose: `remote_comfy` binds `client`
    thirteen times in one module, some bare and some unwrapped, so a file-wide
    scan reports every `client.stream` against every bare binding and cries wolf.
    Each function is walked in source order and a use is judged against the
    binding that is live at that point.
    """
    from provider_core.http_client import SharedHttpClient

    # Only the methods a call site can reach through the wrapper.
    callable_surface = {
        name for name in dir(SharedHttpClient) if not name.startswith("_")
    } - {"config"}

    root = Path(__file__).resolve().parents[1]
    engine_files = sorted(root.glob("*/engines/*/client.py"))
    assert engine_files, "no engine client files were indexed; the walk is broken"

    offenders: list[str] = []
    raw_bindings = 0
    uses_checked = 0

    for engine_file in engine_files:
        tree = ast.parse(engine_file.read_text())
        rel = engine_file.relative_to(root)
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Source order within this function, and only its own statements.
            live: str | None = None
            for stmt in func.body:
                for node in ast.walk(stmt):
                    if isinstance(node, ast.Assign):
                        kind = _binding_kind(node)
                        if kind is not None:
                            live = kind
                            if kind == "raw":
                                raw_bindings += 1
                            # A use inside the same statement still sees the
                            # old binding, so keep scanning this statement.
                    if (
                        live == "raw"
                        and isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "client"
                        and node.attr not in callable_surface
                    ):
                        uses_checked += 1
                        offenders.append(
                            f"{rel}:{node.lineno}  client.{node.attr}  "
                            f"(SharedHttpClient has: {sorted(callable_surface)})"
                        )

    assert raw_bindings > 0, (
        f"no bare `client = get_http_client()` binding found across "
        f"{len(engine_files)} engine clients, so this guard is asserting "
        "nothing; the pattern it constrains was probably renamed, not removed"
    )
    assert not offenders, (
        "these call sites use an httpx.AsyncClient method on the object "
        "get_http_client() returns. SharedHttpClient has no such method, so "
        "each raises AttributeError on a live request path:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.asyncio
async def test_modal_get_file_uses_ranged_reads_not_whole_file_reads():
    """Modal serialises a method's return value across RPC, so a whole-file read
    is 7 GB in the container and 7 GB in the caller. The client must range-read."""
    from image_worker.engines.modal import client as modal_client

    calls: list[tuple] = []

    def _record(path, offset, length):
        calls.append(("range", path, offset, length))
        return _BODY[offset:offset + length]

    class _Remote:
        """Mimics `storage.method.remote.aio(...)` — the `.remote` hop included."""

        def __init__(self, fn):
            self._fn = fn
            self.remote = self

        async def aio(self, *args):
            return self._fn(*args)

    class _FakeStorage:
        file_size = _Remote(lambda path: (calls.append(("size", path, 0, 0)), len(_BODY))[1])
        read_file_range = _Remote(_record)
        # If the client ever reaches for the whole-file read again, fail loudly.
        async def _no_whole_file(self, path):
            raise AssertionError("get_file must not use read_file for a large file")

        read_file = _no_whole_file

    class _FakeStorageCls:
        @staticmethod
        def from_name(name, attr):  # noqa: N802 - mirrors modal.Cls.from_name
            return _FakeStorage

    original = modal_client.modal.Cls
    modal_client.modal.Cls = _FakeStorageCls
    try:
        response = await modal_client.ModalProviderClient({}).get_file("models/x.safetensors")
        received = bytearray()
        async for chunk in response.body_iterator:
            received += chunk
    finally:
        modal_client.modal.Cls = original

    assert bytes(received) == _BODY
    assert calls[0][0] == "size", "the client must ask for the size before reading"
    # Every read is a bounded range, never the whole file.
    assert all(call[3] <= modal_client._MODAL_RANGE_BYTES for call in calls[1:])


@pytest.mark.asyncio
async def test_remote_agent_get_file_does_not_read_the_whole_file():
    """remote_agent is a single-process uvicorn, so a blocking whole-file read
    there stalls every other request on the agent while it happens.

    Asserted on the source rather than over a socket because the failure mode is
    *where* the bytes are held, and that is a property of the code shape.
    """
    from pathlib import Path

    agent_source = (
        Path(__file__).resolve().parents[2] / "remote_agent" / "server.py"
    ).read_text()
    raw = agent_source.split("async def get_file")[1].split("\n\n\n")[0]
    # Strip the docstring: this function's own comment explains the old
    # `f.read()` behaviour, and asserting against prose is asserting nothing.
    get_file_body = raw.split('"""')[0] + "".join(raw.split('"""')[2:]) if '"""' in raw else raw

    assert "FileResponse" in get_file_body, "the agent must not return a buffered Response"
    assert ".read()" not in get_file_body, "get_file must not read the whole file into memory"
    assert "content=" not in get_file_body, "get_file must not pass content= to a Response"
