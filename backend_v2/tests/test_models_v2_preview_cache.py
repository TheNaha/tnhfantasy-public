from pathlib import Path

from api.routes import models_v2


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


def test_fetch_civitai_preview_caches_by_version_and_image_index(monkeypatch, tmp_path):
    monkeypatch.setattr(models_v2, "PREVIEW_CACHE_DIR", str(tmp_path))

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

    monkeypatch.setattr(models_v2.requests, "get", fake_get)

    image_data, content_type = models_v2.fetch_civitai_preview(100, version_id=222, image_index=2)

    assert image_data == b"third-image"
    assert content_type == "image/webp"
    assert calls == [
        "https://civitai.com/api/v1/models/100",
        "https://img.example.com/third.jpg",
    ]

    # Cached fetch should not hit network again.
    cached_data, cached_content_type = models_v2.fetch_civitai_preview(100, version_id=222, image_index=2)
    assert cached_data == b"third-image"
    assert cached_content_type == "image/webp"
    assert len(calls) == 2

    assert (Path(tmp_path) / "100_222_2.img").exists()
    assert (Path(tmp_path) / "100_222_2.img.meta").exists()


def test_fetch_civitai_preview_falls_back_to_first_version_and_clamps_image_index(monkeypatch, tmp_path):
    monkeypatch.setattr(models_v2, "PREVIEW_CACHE_DIR", str(tmp_path))

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

    monkeypatch.setattr(models_v2.requests, "get", fake_get)

    # version_id is unknown, so route should fallback to first available version.
    # image_index is out of range, so it should clamp to the last available image.
    image_data, content_type = models_v2.fetch_civitai_preview(77, version_id=999, image_index=9)

    assert image_data == b"second-image"
    assert content_type == "image/jpeg"
    assert calls == [
        "https://civitai.com/api/v1/models/77",
        "https://img.example.com/b.jpg",
    ]
