import io
import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from image_worker.comfy.workflow_executor import (
    IMAGE_FETCH_FILESYSTEM,
    IMAGE_FETCH_VIEW_API,
    execute_comfy_workflow,
)


class _FakeWebSocket:
    def __init__(self, messages, connection_closed_exc):
        self._messages = list(messages)
        self._connection_closed_exc = connection_closed_exc
        self.closed = False

    async def recv(self):
        if self._messages:
            return self._messages.pop(0)
        raise self._connection_closed_exc("stream ended")

    async def close(self):
        self.closed = True


class _SlowWebSocket:
    def __init__(self, sleep_seconds=3600):
        self.sleep_seconds = sleep_seconds
        self.closed = False

    async def recv(self):
        await asyncio.sleep(self.sleep_seconds)

    async def close(self):
        self.closed = True


class _FakeWebSocketsModule:
    class exceptions:
        class ConnectionClosed(Exception):
            pass

    def __init__(self, websocket):
        self._websocket = websocket

    async def connect(self, _url):
        return self._websocket



class _FakeAsyncClient:
    def __init__(self, fake_urlopen):
        self.fake_urlopen = fake_urlopen
    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc, tb): pass
    async def post(self, url, json=None, timeout=None, **kwargs):
        import urllib.request, urllib.error
        req = urllib.request.Request(url, data=b"fake")
        try:
            res = self.fake_urlopen(req, timeout)
            res.json = lambda: __import__('json').loads(res.read())
            res.raise_for_status = lambda: None
            return res
        except urllib.error.HTTPError as e:
            import httpx
            class MockResponse:
                text = e.fp.read().decode('utf-8') if hasattr(e.fp, 'read') else str(e)
            error = httpx.HTTPStatusError("error", request=httpx.Request("POST", url), response=MockResponse())
            raise error

    async def get(self, url, params=None, timeout=None, **kwargs):
        if params:
            import urllib.parse
            url += "?" + urllib.parse.urlencode(params)
        res = self.fake_urlopen(url, timeout)
        res.json = lambda: __import__('json').loads(res.read())
        res.content = res.read()
        res.raise_for_status = lambda: None
        return res

class _BytesResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


async def _collect_updates(generator):
    updates = []
    async for update in generator:
        updates.append(update)
    return updates


@pytest.mark.asyncio
async def test_execute_comfy_workflow_filesystem_mode_streams_contract(monkeypatch, tmp_path):
    prompt_id = "prompt-filesystem"
    output_dir = tmp_path / "output"
    temp_dir = tmp_path / "temp"
    output_dir.mkdir()
    temp_dir.mkdir()
    image_path = output_dir / "result.png"
    image_path.write_bytes(b"image-bytes")

    websocket = _FakeWebSocket(
        messages=[
            json.dumps({"type": "executing", "data": {"prompt_id": prompt_id, "node": "5"}}),
            json.dumps({"type": "progress", "data": {"prompt_id": prompt_id, "value": 1, "max": 3}}),
            json.dumps({"type": "executing", "data": {"prompt_id": prompt_id, "node": None}}),
        ],
        connection_closed_exc=_FakeWebSocketsModule.exceptions.ConnectionClosed,
    )
    fake_websockets = _FakeWebSocketsModule(websocket)
    monkeypatch.setattr(
        "image_worker.comfy.workflow_executor._get_websockets_module",
        lambda: fake_websockets,
    )

    def fake_urlopen(target, timeout=None):
        del timeout
        if isinstance(target, urllib.request.Request):
            assert target.full_url.endswith("/prompt")
            return _BytesResponse(json.dumps({"prompt_id": prompt_id}).encode("utf-8"))

        assert f"/history/{prompt_id}" in target
        history_payload = {
            prompt_id: {
                "outputs": {
                    "node-1": {
                        "images": [
                            {
                                "filename": "result.png",
                                "type": "output",
                            }
                        ]
                    }
                }
            }
        }
        return _BytesResponse(json.dumps(history_payload).encode("utf-8"))

    monkeypatch.setattr("image_worker.comfy.workflow_executor.get_http_client", lambda: _FakeAsyncClient(fake_urlopen))

    updates = await _collect_updates(
        execute_comfy_workflow(
            workflow_json={"nodes": {}},
            port=8188,
            image_fetch_mode=IMAGE_FETCH_FILESYSTEM,
            output_dir=str(output_dir),
            temp_dir=str(temp_dir),
        )
    )

    statuses = [update["status"] for update in updates]
    assert statuses == ["queued", "executing", "progress", "success"]
    assert updates[-1]["images"][0]["filename"] == "result.png"
    assert updates[-1]["images"][0]["data"] == "aW1hZ2UtYnl0ZXM="
    assert websocket.closed is True


@pytest.mark.asyncio
async def test_execute_comfy_workflow_view_api_mode_streams_contract(monkeypatch):
    prompt_id = "prompt-view"
    websocket = _FakeWebSocket(
        messages=[json.dumps({"type": "executing", "data": {"prompt_id": prompt_id, "node": None}})],
        connection_closed_exc=_FakeWebSocketsModule.exceptions.ConnectionClosed,
    )
    fake_websockets = _FakeWebSocketsModule(websocket)
    monkeypatch.setattr(
        "image_worker.comfy.workflow_executor._get_websockets_module",
        lambda: fake_websockets,
    )

    view_urls = []

    def fake_urlopen(target, timeout=None):
        if isinstance(target, urllib.request.Request):
            assert target.full_url.endswith("/prompt")
            return _BytesResponse(json.dumps({"prompt_id": prompt_id}).encode("utf-8"))

        if f"/history/{prompt_id}" in target:
            history_payload = {
                prompt_id: {
                    "outputs": {
                        "node-2": {
                            "images": [
                                {
                                    "filename": "beam-image.png",
                                    "subfolder": "demo",
                                    "type": "output",
                                }
                            ]
                        }
                    }
                }
            }
            return _BytesResponse(json.dumps(history_payload).encode("utf-8"))

        if "/view?" in target:
            assert timeout == 30.0
            view_urls.append(target)
            return _BytesResponse(b"image-from-view")

        raise AssertionError(f"Unexpected URL: {target}")

    monkeypatch.setattr("image_worker.comfy.workflow_executor.get_http_client", lambda: _FakeAsyncClient(fake_urlopen))

    updates = await _collect_updates(
        execute_comfy_workflow(
            workflow_json={"nodes": {}},
            port=8188,
            image_fetch_mode=IMAGE_FETCH_VIEW_API,
        )
    )

    assert [update["status"] for update in updates] == ["queued", "success"]
    assert updates[-1]["images"][0]["filename"] == "beam-image.png"
    assert updates[-1]["images"][0]["data"] == "aW1hZ2UtZnJvbS12aWV3"
    assert view_urls, "expected at least one /view request"

    parsed = urllib.parse.urlparse(view_urls[0])
    query = urllib.parse.parse_qs(parsed.query)
    assert query["filename"] == ["beam-image.png"]
    assert query["subfolder"] == ["demo"]
    assert query["type"] == ["output"]


@pytest.mark.asyncio
async def test_execute_comfy_workflow_emits_execution_error_and_stops(monkeypatch):
    prompt_id = "prompt-error"
    websocket = _FakeWebSocket(
        messages=[json.dumps({"type": "execution_error", "data": {"message": "node failed"}})],
        connection_closed_exc=_FakeWebSocketsModule.exceptions.ConnectionClosed,
    )
    fake_websockets = _FakeWebSocketsModule(websocket)
    monkeypatch.setattr(
        "image_worker.comfy.workflow_executor._get_websockets_module",
        lambda: fake_websockets,
    )

    def fake_urlopen(target, timeout=None):
        del timeout
        if isinstance(target, urllib.request.Request):
            return _BytesResponse(json.dumps({"prompt_id": prompt_id}).encode("utf-8"))
        raise AssertionError("History endpoint should not be called after execution_error")

    monkeypatch.setattr("image_worker.comfy.workflow_executor.get_http_client", lambda: _FakeAsyncClient(fake_urlopen))

    updates = await _collect_updates(
        execute_comfy_workflow(
            workflow_json={"nodes": {}},
            port=8188,
            image_fetch_mode=IMAGE_FETCH_FILESYSTEM,
        )
    )

    assert [update["status"] for update in updates] == ["queued", "error"]
    assert "node failed" in updates[-1]["message"]
    assert websocket.closed is True


@pytest.mark.asyncio
async def test_execute_comfy_workflow_reports_prompt_rejection(monkeypatch):
    websocket = _FakeWebSocket(
        messages=[],
        connection_closed_exc=_FakeWebSocketsModule.exceptions.ConnectionClosed,
    )
    fake_websockets = _FakeWebSocketsModule(websocket)
    monkeypatch.setattr(
        "image_worker.comfy.workflow_executor._get_websockets_module",
        lambda: fake_websockets,
    )

    def fake_urlopen(target, timeout=None):
        del timeout
        if isinstance(target, urllib.request.Request):
            raise urllib.error.HTTPError(
                url=target.full_url,
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=io.BytesIO(b"invalid workflow"),
            )
        raise AssertionError("History endpoint should not be called after prompt rejection")

    monkeypatch.setattr("image_worker.comfy.workflow_executor.get_http_client", lambda: _FakeAsyncClient(fake_urlopen))

    updates = await _collect_updates(
        execute_comfy_workflow(
            workflow_json={"nodes": {}},
            port=8188,
            image_fetch_mode=IMAGE_FETCH_FILESYSTEM,
        )
    )

    assert len(updates) == 1
    assert updates[0]["status"] == "error"
    assert "invalid workflow" in updates[0]["message"]
    assert websocket.closed is True


@pytest.mark.asyncio
async def test_execute_comfy_workflow_reports_stalled_prompt(monkeypatch):
    prompt_id = "prompt-stalled"
    websocket = _SlowWebSocket()
    fake_websockets = _FakeWebSocketsModule(websocket)
    monkeypatch.setattr(
        "image_worker.comfy.workflow_executor._get_websockets_module",
        lambda: fake_websockets,
    )

    def fake_urlopen(target, timeout=None):
        del timeout
        if isinstance(target, urllib.request.Request):
            return _BytesResponse(json.dumps({"prompt_id": prompt_id}).encode("utf-8"))

        if f"/history/{prompt_id}" in target:
            return _BytesResponse(json.dumps({}).encode("utf-8"))

        raise AssertionError(f"Unexpected URL: {target}")

    monkeypatch.setattr("image_worker.comfy.workflow_executor.get_http_client", lambda: _FakeAsyncClient(fake_urlopen))

    updates = await _collect_updates(
        execute_comfy_workflow(
            workflow_json={"nodes": {}},
            port=8188,
            image_fetch_mode=IMAGE_FETCH_FILESYSTEM,
            stall_timeout_seconds=0.01,
        )
    )

    assert [update["status"] for update in updates] == ["queued", "error"]
    assert updates[-1].get("code") == 408
    assert updates[-1].get("details", {}).get("reason") == "workflow_stalled"
    assert websocket.closed is True
