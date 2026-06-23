import asyncio
from pathlib import Path

import pytest
import httpx

from services import model_preview_service as models_router
from services import external_model_service
from api.routes.models.preview import get_model_preview_image
from infrastructure.request_dedup import clear_dedup_cache


class _DummyResponse:
    def __init__(self, *, json_data=None, content=b"", headers=None, status_code=200):
        self._json_data = json_data
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


class _DummyAsyncClient:
    def __init__(self, route_handler):
        self.route_handler = route_handler

    async def get(self, url, timeout=0):
        return self.route_handler(url, timeout)


@pytest.mark.asyncio
async def test_fetch_civitai_preview_caches_by_version_and_image_index(monkeypatch, tmp_path):
    monkeypatch.setattr(models_router, "PREVIEW_CACHE_DIR", str(tmp_path))

    calls = []

    def fake_get(url, timeout=0):
        calls.append(url)

        if url == "https://civitai.com/api/v1/models/100":
            return _DummyResponse(
                json_data={
                    "modelVersions": [
                        {
                            "id": 222,
                            "images": [
                                {"type": "video", "url": "https://img.example.com/video.mp4"},
                                {"type": "image", "url": "https://img.example.com/first.jpg"},
                                {"url": "https://img.example.com/second.jpg"},
                                {"type": "image", "url": "https://img.example.com/third.jpg"},
                            ],
                        }
                    ]
                }
            )

        if url == "https://img.example.com/third.jpg":
            return _DummyResponse(content=b"third-image", headers={"Content-Type": "image/webp"})

        raise AssertionError(f"Unexpected URL requested: {url}")

    dummy_client = _DummyAsyncClient(fake_get)
    monkeypatch.setattr(models_router, "get_http_client", lambda: dummy_client)
    monkeypatch.setattr(external_model_service, "get_http_client", lambda: dummy_client)

    image_data, content_type, cache_hit = await models_router.fetch_civitai_preview(100, version_id=222, image_index=2)

    assert image_data == b"third-image"
    assert content_type == "image/webp"
    assert cache_hit is False
    assert calls == [
        "https://civitai.com/api/v1/models/100",
        "https://img.example.com/third.jpg",
    ]

    # Cached fetch should not hit network again.
    cached_data, cached_content_type, cached_hit = await models_router.fetch_civitai_preview(100, version_id=222, image_index=2)
    assert cached_data == b"third-image"
    assert cached_content_type == "image/webp"
    assert cached_hit is True
    assert len(calls) == 2

    assert (Path(tmp_path) / "100_222_2.img").exists()
    assert (Path(tmp_path) / "100_222_2.img.meta").exists()


@pytest.mark.asyncio
async def test_fetch_civitai_preview_falls_back_to_first_version_and_clamps_image_index(monkeypatch, tmp_path):
    monkeypatch.setattr(models_router, "PREVIEW_CACHE_DIR", str(tmp_path))

    calls = []

    def fake_get(url, timeout=0):
        calls.append(url)

        if url == "https://civitai.com/api/v1/models/77":
            return _DummyResponse(
                json_data={
                    "modelVersions": [
                        {
                            "id": 1,
                            "images": [
                                {"type": "image", "url": "https://img.example.com/a.jpg"},
                                {"type": "image", "url": "https://img.example.com/b.jpg"},
                            ],
                        }
                    ]
                }
            )

        if url == "https://img.example.com/b.jpg":
            return _DummyResponse(content=b"second-image", headers={"Content-Type": "image/jpeg"})

        raise AssertionError(f"Unexpected URL requested: {url}")

    dummy_client = _DummyAsyncClient(fake_get)
    monkeypatch.setattr(models_router, "get_http_client", lambda: dummy_client)
    monkeypatch.setattr(external_model_service, "get_http_client", lambda: dummy_client)

    # version_id is unknown, so route should fallback to first available version.
    # image_index is out of range, so it should clamp to the last available image.
    image_data, content_type, cache_hit = await models_router.fetch_civitai_preview(77, version_id=999, image_index=9)

    assert image_data == b"second-image"
    assert content_type == "image/jpeg"
    assert cache_hit is False
    assert calls == [
        "https://civitai.com/api/v1/models/77",
        "https://img.example.com/b.jpg",
    ]


@pytest.mark.asyncio
async def test_get_model_preview_image_deduplicates_concurrent_fetches(monkeypatch):
    clear_dedup_cache()
    calls = 0

    async def fake_fetch(_model_id, _version_id=None, _image_index=0, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return b"img", "image/jpeg", False

    monkeypatch.setattr(models_router, "fetch_civitai_preview", fake_fetch)

    await asyncio.gather(
        get_model_preview_image(11, version_id=22, image_index=0),
        get_model_preview_image(11, version_id=22, image_index=0),
    )

    assert calls == 1


@pytest.mark.asyncio
async def test_fetch_civitai_preview_skips_network_after_recent_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(models_router, "PREVIEW_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(models_router, "PREVIEW_FAILURE_TTL_SECONDS", 600)

    calls = []

    def fake_get(url, timeout=0):
        calls.append(url)
        raise RuntimeError("network down")

    dummy_client = _DummyAsyncClient(fake_get)
    monkeypatch.setattr(models_router, "get_http_client", lambda: dummy_client)
    monkeypatch.setattr(external_model_service, "get_http_client", lambda: dummy_client)

    first_data, first_content_type, first_cache_hit = await models_router.fetch_civitai_preview(987654, image_index=0)
    second_data, second_content_type, second_cache_hit = await models_router.fetch_civitai_preview(987654, image_index=0)

    assert first_data is None
    assert first_content_type is None
    assert first_cache_hit is False
    assert second_data is None
    assert second_content_type is None
    assert second_cache_hit is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fetch_civitai_preview_skips_retries_after_model_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(models_router, "PREVIEW_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(models_router, "PREVIEW_NOT_FOUND_TTL_SECONDS", 3600)

    calls = []

    def fake_get(url, timeout=0):
        calls.append(url)
        request = httpx.Request("GET", url)
        response = httpx.Response(status_code=404, request=request)
        raise httpx.HTTPStatusError("404 Not Found", request=request, response=response)

    dummy_client = _DummyAsyncClient(fake_get)
    monkeypatch.setattr(models_router, "get_http_client", lambda: dummy_client)
    monkeypatch.setattr(external_model_service, "get_http_client", lambda: dummy_client)

    first_data, first_content_type, first_cache_hit = await models_router.fetch_civitai_preview(579645, image_index=0)
    second_data, second_content_type, second_cache_hit = await models_router.fetch_civitai_preview(579645, image_index=0)

    assert first_data is None
    assert first_content_type is None
    assert first_cache_hit is False
    assert second_data is None
    assert second_content_type is None
    assert second_cache_hit is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_prefetch_stale_model_previews_warms_selected_candidates(monkeypatch):
    monkeypatch.setattr(models_router, "PREVIEW_PREFETCH_ENABLED", True)
    monkeypatch.setattr(models_router, "PREVIEW_PREFETCH_JITTER_SECONDS", 0.0)
    monkeypatch.setattr(models_router, "PREVIEW_PREFETCH_ITEM_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(models_router, "PREVIEW_PREFETCH_MAX_CANDIDATES", 10)
    monkeypatch.setattr(models_router, "PREVIEW_PREFETCH_BATCH_SIZE", 2)
    monkeypatch.setattr(models_router, "PREVIEW_PREFETCH_STALE_AFTER_SECONDS", 3600)

    monkeypatch.setattr(models_router, "_list_civitai_model_ids_for_prefetch", lambda: [101, 102, 103])
    monkeypatch.setattr(models_router, "_select_stale_prefetch_candidates", lambda *_args: [101, 103])

    calls = []

    async def fake_fetch(model_id, version_id=None, image_index=0, force_refresh=False):
        calls.append((model_id, version_id, image_index, force_refresh))
        return b"img", "image/jpeg", False

    monkeypatch.setattr(models_router, "fetch_civitai_preview", fake_fetch)

    result = await models_router.prefetch_stale_model_previews()

    assert result["status"] == "ok"
    assert result["selected"] == 2
    assert result["warmed"] == 2
    assert result["misses"] == 0
    assert calls == [
        (101, None, 0, True),
        (103, None, 0, True),
    ]


@pytest.mark.asyncio
async def test_prefetch_stale_model_previews_returns_disabled_when_off(monkeypatch):
    monkeypatch.setattr(models_router, "PREVIEW_PREFETCH_ENABLED", False)

    result = await models_router.prefetch_stale_model_previews()

    assert result == {"status": "disabled"}
