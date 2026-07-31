import pytest
from unittest.mock import patch, MagicMock, AsyncMock, ANY
from api.routes.websocket import WebSocketManager, connect, disconnect, subscribe, unsubscribe, cancel_job, connected_clients
from core.events import Event, EventType

@pytest.fixture
def mock_sio():
    with patch("api.routes.websocket.sio") as mock:
        mock.emit = AsyncMock()
        mock.enter_room = AsyncMock()
        mock.leave_room = AsyncMock()
        yield mock

@pytest.fixture
def manager():
    return WebSocketManager()

@pytest.mark.asyncio
async def test_manager_start_stop_broadcasting(manager, mock_sio):
    # Mock event_bus.subscribe_multiple
    with patch("core.events.event_bus.subscribe_multiple") as mock_sub:
        async def mock_gen(topics, max_queue_size=100):
            # Yield one event then stop
            yield Event(type=EventType.JOB_PROGRESS, data={"id": "1"})

        mock_sub.side_effect = mock_gen

        # Start broadcasting in background
        task = asyncio.create_task(manager.start_broadcasting())
        await asyncio.sleep(0.01) # Give it time to run

        assert manager._running is True

        # Stop
        await manager.stop_broadcasting()
        assert manager._running is False
        await task

@pytest.mark.asyncio
async def test_connect(mock_sio):
    sid = "test_sid"
    await connect(sid, {})
    assert sid in connected_clients
    mock_sio.emit.assert_called_with('connected', ANY, room=sid)

@pytest.mark.asyncio
async def test_disconnect(mock_sio):
    sid = "test_sid"
    connected_clients[sid] = {"room1"}
    await disconnect(sid)
    assert sid not in connected_clients
    mock_sio.leave_room.assert_called_with(sid, "room1")

@pytest.mark.asyncio
async def test_subscribe(mock_sio):
    sid = "test_sid"
    connected_clients[sid] = set()
    await subscribe(sid, {"topic": "job"})
    assert "job" in connected_clients[sid]
    mock_sio.enter_room.assert_called_with(sid, "job")

@pytest.mark.asyncio
async def test_subscribe_multiple(mock_sio):
    sid = "test_sid"
    connected_clients[sid] = set()
    await subscribe(sid, {"topics": ["job", "download"]})
    assert "job" in connected_clients[sid]
    assert "download" in connected_clients[sid]
    assert mock_sio.enter_room.call_count == 2

@pytest.mark.asyncio
async def test_unsubscribe(mock_sio):
    sid = "test_sid"
    connected_clients[sid] = {"job"}
    await unsubscribe(sid, {"topic": "job"})
    assert "job" not in connected_clients[sid]
    mock_sio.leave_room.assert_called_with(sid, "job")

@pytest.mark.asyncio
async def test_cancel_job_missing_id(mock_sio):
    sid = "test_sid"
    await cancel_job(sid, {})
    mock_sio.emit.assert_called_with('error', {'message': 'job_id required'}, room=sid)

import asyncio

@pytest.mark.asyncio
@patch("services.job_queue.job_queue")
@patch("services.job_service.JobService")
@patch("infrastructure.database.get_session_context")
async def test_cancel_job_pending(mock_get_session, mock_job_service_cls, mock_job_queue, mock_sio):
    sid = "test_sid"
    job_id = "job1"

    # Mock job queue says job is NOT active (so it's pending)
    mock_job_queue.is_job_active.return_value = False

    # Mock session context
    mock_session = AsyncMock()
    mock_get_session.return_value.__aenter__.return_value = mock_session

    # Mock JobService
    mock_job_service = AsyncMock()
    mock_job_service_cls.return_value = mock_job_service

    mock_job = MagicMock()
    mock_job.status.value = 'pending'
    mock_job_service.get_job.return_value = mock_job

    await cancel_job(sid, {"job_id": job_id})

    mock_job_service.update_job.assert_called_once()
    mock_sio.emit.assert_called_with('cancel_job_ack', ANY, room=sid)

@pytest.mark.asyncio
@patch("services.job_queue.job_queue")
@patch("services.job_service.JobService")
@patch("services.provider_service.ProviderService")
@patch("api.deps.get_http_client")
@patch("infrastructure.database.get_session_context")
async def test_cancel_job_active(mock_get_session, mock_get_http, mock_provider_service_cls, mock_job_service_cls, mock_job_queue, mock_sio):
    sid = "test_sid"
    job_id = "job1"

    # Mock job active
    mock_job_queue.is_job_active.return_value = True

    # Mock session
    mock_session = AsyncMock()
    mock_get_session.return_value.__aenter__.return_value = mock_session

    # Mock JobService
    mock_job_service = AsyncMock()
    mock_job_service_cls.return_value = mock_job_service
    mock_job = MagicMock()
    mock_job.provider_id = "p1"
    mock_job_service.get_job.return_value = mock_job

    # Mock ProviderService
    mock_provider_service = AsyncMock()
    mock_provider_service_cls.return_value = mock_provider_service
    mock_provider = MagicMock()
    mock_provider.id = "p1"
    mock_provider.type = "modal"
    mock_provider.container_config = {"container_name": "c1"}
    mock_provider_service.get_provider.return_value = mock_provider

    # Mock HTTP client
    mock_http = AsyncMock()
    mock_http.post.return_value.status_code = 200
    mock_get_http.return_value = mock_http

    await cancel_job(sid, {"job_id": job_id})

    mock_http.post.assert_called_once()
    mock_job_service.update_job.assert_called_once()
    mock_sio.emit.assert_called_with('cancel_job_ack', ANY, room=sid)


@pytest.mark.asyncio
async def test_request_replay(mock_sio):
    sid = "test_sid"
    from core.events import Event, EventType
    event1 = Event(type=EventType.JOB_CREATED, data={"i": 1})
    event1.sequence_number = 1
    event2 = Event(type=EventType.JOB_COMPLETED, data={"i": 2})
    event2.sequence_number = 2
    
    with patch("core.events.event_bus.get_replay_buffer") as mock_get_replay:
        mock_get_replay.return_value = [event1, event2]
        
        from api.routes.websocket import request_replay
        await request_replay(sid, {"last_sequence_number": 1})
        mock_sio.emit.assert_called_with(
            "replay_events",
            {"events": [event2.to_dict()]},
            room=sid
        )


@pytest.mark.asyncio
async def test_request_replay_missing_last_sequence_number(mock_sio):
    sid = "test_sid"
    from api.routes.websocket import request_replay
    await request_replay(sid, {})
    mock_sio.emit.assert_called_with("error", {"message": "last_sequence_number is required"}, room=sid)


@pytest.mark.asyncio
async def test_request_replay_invalid_last_sequence_number(mock_sio):
    sid = "test_sid"
    from api.routes.websocket import request_replay
    await request_replay(sid, {"last_sequence_number": "not_an_int"})
    mock_sio.emit.assert_called_with("error", {"message": "last_sequence_number must be an integer"}, room=sid)
