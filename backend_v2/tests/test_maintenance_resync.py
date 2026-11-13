"""
`POST /api/v2/models/maintenance/resync-all` → `run_background_resync`.

The button refreshes each installed model's metadata from CivitAI (name,
description, stats, tags, version sizes) so nothing in the database goes stale.
It used to fetch five models concurrently with no rate-limit handling, which
hammered CivitAI and got rate-limited. It now fetches strictly one at a time,
and a 429 is backed off (honoring `Retry-After`) and retried until the limit
clears.
"""

import pytest
from contextlib import asynccontextmanager

from api.routes.models import maintenance


class FakeResponse:
    def __init__(self, status_code, headers=None, json_data=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json = json_data or {}

    def json(self):
        return self._json


class FakeHttpClient:
    """Consumes response-makers from a queue, one per GET, recording URLs."""

    def __init__(self, makers):
        self.makers = list(makers)
        self.calls = []
        self.headers_passed = []

    async def get(self, url, headers=None, timeout=None, **kwargs):
        self.calls.append(url)
        self.headers_passed.append(headers)
        if not self.makers:
            return FakeResponse(500)
        return self.makers.pop(0)()


@asynccontextmanager
async def fake_session_context(session):
    yield session


def make_model(session, civitai_id, name="Test Model", description="A model"):
    from core.entities import ModelV2

    model = ModelV2(
        name=name,
        type="Checkpoint",
        directory="checkpoints",
        civitai_model_id=civitai_id,
        description=description,
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    return model


def civitai_payload(name="Synced Model", tags=None, downloads=100):
    return {
        "id": 99999,
        "name": name,
        "description": "Fresh metadata from CivitAI",
        "nsfw": False,
        "creator": {"username": "creator"},
        "stats": {
            "downloadCount": downloads,
            "thumbsUpCount": 10,
            "thumbsDownCount": 0,
            "commentCount": 0,
        },
        "tags": tags or ["anime"],
        "modelVersions": [],
    }


@pytest.mark.asyncio
async def test_resync_processes_models_one_at_a_time_and_applies_metadata(session, monkeypatch):
    m1 = make_model(session, 100, "Model One")
    m2 = make_model(session, 101, "Model Two")

    client = FakeHttpClient([
        lambda: FakeResponse(200, json_data=civitai_payload("Synced One")),
        lambda: FakeResponse(200, json_data=civitai_payload("Synced Two")),
    ])
    broadcasts = []
    slept = []

    def fake_get_http_client():
        return client

    async def fake_broadcast(event_type, data):
        broadcasts.append((event_type, data))

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(maintenance, "get_http_client", fake_get_http_client)
    monkeypatch.setattr(maintenance, "broadcast_to_all", fake_broadcast)
    monkeypatch.setattr(maintenance, "get_session_context", lambda: fake_session_context(session))
    monkeypatch.setattr(maintenance.asyncio, "sleep", fake_sleep)

    results = await maintenance.run_background_resync()

    assert results["success"] == 2
    assert results["failed"] == 0
    # Strictly sequential: one URL at a time, never concurrent.
    assert client.calls == [
        "https://civitai.com/api/v1/models/100",
        "https://civitai.com/api/v1/models/101",
    ]

    # Metadata applied to the database.
    session.refresh(m1)
    session.refresh(m2)
    assert m1.name == "Synced One"
    assert m2.name == "Synced Two"
    assert m1.stats_downloads == 100

    # Progress broadcasted per model.
    statuses = [b[1].get("status") for b in broadcasts]
    assert statuses[0] == "started"
    assert statuses[-1] == "completed"
    assert statuses.count("processing") >= 2


@pytest.mark.asyncio
async def test_resync_retries_429_until_clear_then_succeeds(session, monkeypatch):
    m = make_model(session, 200, "Rate Limited Model")

    # First two attempts are rate limited, the third succeeds.
    client = FakeHttpClient([
        lambda: FakeResponse(429, {"Retry-After": "0"}, json_data=None),
        lambda: FakeResponse(429, {"Retry-After": "0"}, json_data=None),
        lambda: FakeResponse(200, json_data=civitai_payload("After Retry")),
    ])
    broadcasts = []
    slept = []

    def fake_get_http_client():
        return client

    async def fake_broadcast(event_type, data):
        broadcasts.append((event_type, data))

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(maintenance, "get_http_client", fake_get_http_client)
    monkeypatch.setattr(maintenance, "broadcast_to_all", fake_broadcast)
    monkeypatch.setattr(maintenance, "get_session_context", lambda: fake_session_context(session))
    monkeypatch.setattr(maintenance.asyncio, "sleep", fake_sleep)

    results = await maintenance.run_background_resync()

    assert results["success"] == 1
    assert results["failed"] == 0
    # Retried twice (two 429s) before succeeding.
    assert client.calls == [
        "https://civitai.com/api/v1/models/200",
        "https://civitai.com/api/v1/models/200",
        "https://civitai.com/api/v1/models/200",
    ]
    assert slept == [0.0, 0.0]

    session.refresh(m)
    assert m.name == "After Retry"

    # The rate-limited retry was surfaced to the UI.
    assert any("rate limited" in (b[1].get("current_model") or "") for b in broadcasts)


@pytest.mark.asyncio
async def test_resync_exhausts_retries_on_persistent_429(session, monkeypatch):
    m = make_model(session, 300, "Never Clears")

    client = FakeHttpClient([
        lambda: FakeResponse(429, {"Retry-After": "0"}, json_data=None)
        for _ in range(maintenance.RESYNC_MAX_RETRIES)
    ])
    slept = []

    def fake_get_http_client():
        return client

    async def fake_broadcast(event_type, data):
        pass

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(maintenance, "get_http_client", fake_get_http_client)
    monkeypatch.setattr(maintenance, "broadcast_to_all", fake_broadcast)
    monkeypatch.setattr(maintenance, "get_session_context", lambda: fake_session_context(session))
    monkeypatch.setattr(maintenance.asyncio, "sleep", fake_sleep)

    results = await maintenance.run_background_resync()

    assert results["failed"] == 1
    assert results["success"] == 0
    assert len(results["errors"]) == 1
    assert results["errors"][0]["model_id"] == str(m.id)
    # Retried the configured maximum, no more.
    assert len(client.calls) == maintenance.RESYNC_MAX_RETRIES
    assert len(slept) == maintenance.RESYNC_MAX_RETRIES


@pytest.mark.asyncio
async def test_resync_no_models(session, monkeypatch):
    async def fake_get_http_client():
        return FakeHttpClient([])

    broadcasts = []

    async def fake_broadcast(event_type, data):
        broadcasts.append((event_type, data))

    monkeypatch.setattr(maintenance, "get_http_client", fake_get_http_client)
    monkeypatch.setattr(maintenance, "broadcast_to_all", fake_broadcast)
    monkeypatch.setattr(maintenance, "get_session_context", lambda: fake_session_context(session))

    results = await maintenance.run_background_resync()

    assert results == {"success": 0, "failed": 0, "errors": []}
    assert len(broadcasts) == 0


@pytest.mark.asyncio
async def test_resync_non_429_error_fails_without_retry(session, monkeypatch):
    m = make_model(session, 400, "Hard Error")

    client = FakeHttpClient([lambda: FakeResponse(500, json_data=None)])
    slept = []

    def fake_get_http_client():
        return client

    async def fake_broadcast(event_type, data):
        pass

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(maintenance, "get_http_client", fake_get_http_client)
    monkeypatch.setattr(maintenance, "broadcast_to_all", fake_broadcast)
    monkeypatch.setattr(maintenance, "get_session_context", lambda: fake_session_context(session))
    monkeypatch.setattr(maintenance.asyncio, "sleep", fake_sleep)

    results = await maintenance.run_background_resync()

    assert results["failed"] == 1
    assert results["success"] == 0
    # Non-429 errors are not retried.
    assert client.calls == [f"https://civitai.com/api/v1/models/{m.civitai_model_id}"]
    assert results["errors"][0]["model_id"] == str(m.id)
    assert slept == []


@pytest.mark.asyncio
async def test_resync_synchronizes_all_version_images(session, monkeypatch):
    from core.entities import ModelImage, ModelVersion
    from sqlmodel import select

    m = make_model(session, 500, "Image Sync Model")
    version = ModelVersion(
        model_id=m.id,
        civitai_version_id=5001,
        name="v1.0",
        is_default=True,
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    # Initial image seed
    img0 = ModelImage(
        version_id=version.id,
        url="https://image.civitai.com/x/img0.webp",
        sort_order=0,
    )
    session.add(img0)
    session.commit()

    payload = civitai_payload("Image Sync Model")
    payload["modelVersions"] = [
        {
            "id": 5001,
            "name": "v1.0",
            "images": [
                {"url": "https://image.civitai.com/x/img0.webp", "hash": "h0", "width": 512, "height": 512},
                {"url": "https://image.civitai.com/x/img1.webp", "hash": "h1", "width": 1024, "height": 1024},
                {"url": "https://image.civitai.com/x/img2.webp", "hash": "h2", "width": 768, "height": 768},
            ],
        }
    ]

    client = FakeHttpClient([lambda: FakeResponse(200, json_data=payload)])

    async def fake_broadcast(evt, data):
        pass

    monkeypatch.setattr(maintenance, "get_http_client", lambda: client)
    monkeypatch.setattr(maintenance, "broadcast_to_all", fake_broadcast)
    monkeypatch.setattr(maintenance, "get_session_context", lambda: fake_session_context(session))

    results = await maintenance.run_background_resync()
    assert results["success"] == 1

    images = session.exec(
        select(ModelImage).where(ModelImage.version_id == version.id).order_by(ModelImage.sort_order)
    ).all()

    assert len(images) == 3
    urls = [img.url for img in images]
    assert urls == [
        "https://image.civitai.com/x/img0.webp",
        "https://image.civitai.com/x/img1.webp",
        "https://image.civitai.com/x/img2.webp",
    ]
    # Check that metadata on existing image was updated
    assert images[0].blurhash == "h0"
    assert images[0].width == 512
    # Check that new images have their metadata
    assert images[1].blurhash == "h1"
    assert images[1].width == 1024
    assert images[2].blurhash == "h2"
    assert images[2].width == 768


@pytest.mark.asyncio
async def test_resync_falls_back_to_civitai_red_on_404(session, monkeypatch):
    m = make_model(session, 600, "Red Domain Model")

    # civitai.com returns 404, civitai.red returns 200
    client = FakeHttpClient([
        lambda: FakeResponse(404),
        lambda: FakeResponse(200, json_data=civitai_payload("Red Synced Model")),
    ])

    monkeypatch.setenv("CIVITAI_TOKEN", "test-secret-token")
    async def fake_broadcast(evt, data):
        pass

    monkeypatch.setattr(maintenance, "get_http_client", lambda: client)
    monkeypatch.setattr(maintenance, "broadcast_to_all", fake_broadcast)
    monkeypatch.setattr(maintenance, "get_session_context", lambda: fake_session_context(session))

    results = await maintenance.run_background_resync()
    assert results["success"] == 1
    assert results["failed"] == 0

    session.refresh(m)
    assert m.name == "Red Synced Model"

    assert client.calls == [
        "https://civitai.com/api/v1/models/600",
        "https://civitai.red/api/v1/models/600",
    ]
    # Verify Authorization header was passed
    assert client.headers_passed[0] == {
        "User-Agent": "TNHFantasy/1.0",
        "Authorization": "Bearer test-secret-token",
    }


@pytest.mark.asyncio
async def test_run_randomized_background_resync_samples_and_updates_stats(session, monkeypatch):
    for i in range(10):
        make_model(session, 1000 + i, f"Random Model {i}")

    calls = []

    class RecordingClient:
        async def get(self, url, headers=None, timeout=None, **kwargs):
            calls.append(url)
            return FakeResponse(200, json_data=civitai_payload("Random Synced Model", downloads=999))

    client = RecordingClient()

    async def fake_broadcast(evt, data):
        pass

    monkeypatch.setattr(maintenance, "get_http_client", lambda: client)
    monkeypatch.setattr(maintenance, "broadcast_to_all", fake_broadcast)
    monkeypatch.setattr(maintenance, "get_session_context", lambda: fake_session_context(session))

    # Run randomized resync with batch_size=3
    res = await maintenance.run_randomized_background_resync(batch_size=3)
    assert res["success"] == 3
    assert len(calls) == 3

    # Verify status snapshot
    status = maintenance.get_resync_status()
    assert status["mode"] == "random"
    assert status["total"] == 3
    assert status["results"]["success"] == 3


@pytest.mark.asyncio
async def test_resync_rolls_back_failed_commit_so_later_models_succeed(session, monkeypatch):
    m1 = make_model(session, 2001, "Fails Commit")
    m2 = make_model(session, 2002, "Succeeds After Rollback")

    client = FakeHttpClient([
        lambda: FakeResponse(200, json_data=civitai_payload("Updated One")),
        lambda: FakeResponse(200, json_data=civitai_payload("Updated Two")),
    ])
    orig_commit = session.commit
    commit_calls = 0

    def flaky_commit():
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 1:
            raise RuntimeError("simulated commit error")
        return orig_commit()

    async def fake_broadcast(evt, data):
        pass

    monkeypatch.setattr(maintenance, "get_http_client", lambda: client)
    monkeypatch.setattr(maintenance, "broadcast_to_all", fake_broadcast)
    monkeypatch.setattr(maintenance, "get_session_context", lambda: fake_session_context(session))
    monkeypatch.setattr(session, "commit", flaky_commit)

    results = await maintenance.run_background_resync()
    assert results["failed"] == 1
    assert results["success"] == 1
    session.refresh(m2)
    assert m2.name == "Updated Two"
    assert m1.id != m2.id


def test_resync_all_route_starts_background_task_on_event_loop(client, session, monkeypatch):
    make_model(session, 3001, "Route Triggered Model")
    started = []

    def fake_start_background_task(coro, **kwargs):
        coro.close()
        started.append(kwargs.get("task_name"))
        return None

    monkeypatch.setattr("infrastructure.background_tasks.start_background_task", fake_start_background_task)
    resp = client.post("/api/v2/models/maintenance/resync-all", json={"mode": "full"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "processing"
    assert body["count"] == 1
    assert started == ["civitai_resync_full"]
