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

    async def get(self, url, timeout=None):
        self.calls.append(url)
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
