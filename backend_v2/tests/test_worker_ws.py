import ast
import asyncio
import re
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from api.routes.worker_ws import (
    INBOUND_HANDLERS,
    dispatch_job_to_worker,
    is_worker_connected,
    request_worker_job_cancel,
    worker_websocket,
)
from core.entities import JobStatus
from core.exceptions import NotFoundError
from infrastructure.worker_registry import (
    INBOUND_MESSAGES,
    OUTBOUND_MESSAGES,
    WORKER_MESSAGE_TYPES,
    CancelJobMessage,
    ConnectedMessage,
    ConnectedWorker,
    HeartbeatAckMessage,
    JobDispatchMessage,
    JobProgressMessage,
    PendingModelsMessage,
    ProtocolErrorMessage,
    connected_workers,
    parse_worker_message,
    pending_job_futures,
)
from services.provider_client import ProviderCallError


class DummyWebSocket:
    def __init__(self, messages=None):
        self._messages = list(messages or [])
        self.accepted = False
        self.closed = None
        self.sent = []

    async def close(self, code: int, reason: str = ""):
        self.closed = (code, reason)

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_json(self):
        if self._messages:
            return self._messages.pop(0)
        raise WebSocketDisconnect(code=1000)


@pytest.fixture(autouse=True)
def clear_connected_workers():
    connected_workers.clear()
    pending_job_futures.clear()
    yield
    connected_workers.clear()
    pending_job_futures.clear()


def _fake_session_context(session=None):
    @asynccontextmanager
    async def _ctx():
        yield session if session is not None else MagicMock()
    return _ctx()


def _owned_session(provider_id="provider-a"):
    """A session whose session.get(Job, ...) resolves to a job owned by `provider_id`.

    _worker_owns_job is called before every job_* message is processed, and it
    now requires an exact provider match.  Previously a bare MagicMock slipped
    through an unreachable `isinstance(job, Job)` fallthrough, so tests passed
    without ever declaring job ownership.
    """
    session = MagicMock()
    session.get.return_value = SimpleNamespace(provider_id=provider_id)
    return session


@pytest.mark.asyncio
async def test_worker_websocket_closes_when_provider_missing():
    websocket = DummyWebSocket()
    provider_service = AsyncMock()
    provider_service.get_provider.side_effect = NotFoundError("Provider", "missing")

    with patch("api.routes.worker_ws.get_session_context", side_effect=_fake_session_context), \
         patch("services.provider_service.ProviderService", return_value=provider_service):
        await worker_websocket(websocket, "missing", "token")

    assert websocket.accepted is False
    assert websocket.closed == (4001, "Provider not found")


@pytest.mark.asyncio
async def test_worker_websocket_closes_when_token_is_invalid():
    websocket = DummyWebSocket()
    provider = SimpleNamespace(config={"worker_token": "expected-token"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider

    with patch("api.routes.worker_ws.get_session_context", side_effect=_fake_session_context), \
         patch("services.provider_service.ProviderService", return_value=provider_service):
        await worker_websocket(websocket, "provider-a", "bad-token")

    assert websocket.accepted is False
    assert websocket.closed == (4002, "Invalid token")


@pytest.mark.asyncio
async def _await_inline(coro, **kw):
    # Await the finalize coroutine inline so the test can assert completion
    # without racing the event loop teardown.
    await coro


async def test_worker_websocket_finalization_uses_output_filenames():
    outputs = [{"filename": "image-1.png", "relative_path": "2026/03/06/image-1.png", "subfolder": "2026/03/06"}]
    websocket = DummyWebSocket(
        messages=[
            {
                "type": "job_completed",
                "job_id": "job-1",
                "result": {"outputs": outputs},
            }
        ]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    finalize = AsyncMock()
    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service), \
         patch("services.job_processing.finalize_successful_job", finalize), \
         patch("services.asset_reconciler.reconcile_asset", MagicMock()), \
         patch("services.job_processing.wait_for_gallery_outputs", AsyncMock()):
        await worker_websocket(websocket, "provider-a", "token-1")
        await asyncio.sleep(0.05)

    assert websocket.accepted is True
    finalize.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_websocket_rejects_unpersisted_outputs():
    websocket = DummyWebSocket(
        messages=[
            {
                "type": "job_completed",
                "job_id": "job-2",
                "result": {"outputs": ["image-1.png"]},
            }
        ]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    job_service.update_job.assert_any_await(
        "job-2",
        status=JobStatus.FAILED,
        error="External worker outputs must be structured objects",
    )


@pytest.mark.asyncio
async def test_worker_websocket_normalizes_progress_updates():
    websocket = DummyWebSocket(
        messages=[
            {
                "type": "job_progress",
                "job_id": "job-3",
                "data": {
                    "progress": 42,
                    "message": "Rendering node 7",
                },
            }
        ]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    job_service.update_job.assert_awaited_with(
        "job-3",
        progress=42,
        overall_progress=42,
        message="Rendering node 7",
    )


@pytest.mark.asyncio
async def test_dispatch_job_to_worker_sends_job_and_waits_for_result():
    websocket = DummyWebSocket()
    connected_workers["provider-a"] = ConnectedWorker(websocket, "provider-a")

    dispatch_task = asyncio.create_task(
        dispatch_job_to_worker(
            "provider-a",
            {"id": "job-4", "workflow": {"1": {}}, "metadata": {}},
            timeout=1.0,
        )
    )
    await asyncio.sleep(0)

    future = pending_job_futures["job-4"]
    future.set_result({"__handled_by_external_worker": True, "outputs": []})

    result = await dispatch_task

    assert result["__handled_by_external_worker"] is True
    assert websocket.sent == [{
        "type": "job",
        "data": {"id": "job-4", "workflow": {"1": {}}, "metadata": {}},
    }]


@pytest.mark.asyncio
async def test_request_worker_job_cancel_sends_cancel_message():
    websocket = DummyWebSocket()
    connected_workers["provider-a"] = ConnectedWorker(websocket, "provider-a")

    cancelled = await request_worker_job_cancel("provider-a", "job-5")

    assert cancelled is True
    assert websocket.sent == [{
        "type": "cancel_job",
        "job_id": "job-5",
    }]


@pytest.mark.asyncio
async def test_dispatch_rejects_stale_worker_connection():
    websocket = DummyWebSocket()
    worker = ConnectedWorker(websocket, "provider-a")
    worker.last_heartbeat = worker.last_heartbeat - timedelta(seconds=120)
    connected_workers["provider-a"] = worker

    assert is_worker_connected("provider-a") is False

    with pytest.raises(ProviderCallError, match="No external worker connected"):
        await dispatch_job_to_worker(
            "provider-a",
            {"id": "job-6", "workflow": {"1": {}}, "metadata": {}},
            timeout=1.0,
        )


class TestCoercePercent:
    """jobs.progress is percent 0..100 with a CHECK constraint (migration 047).

    An out-of-range write raised IntegrityError inside the session context,
    which propagated to the socket-level handler and closed the whole worker
    socket, leaving the job non-terminal. _coerce_percent makes that
    impossible for both the canonical and the legacy payload shapes.
    """

    def test_clamps_legacy_fraction(self):
        from api.routes.worker_ws import _coerce_percent
        assert _coerce_percent(0.5) == 50
        assert _coerce_percent(0) == 0

    def test_passes_through_percent(self):
        from api.routes.worker_ws import _coerce_percent
        assert _coerce_percent(42) == 42
        assert _coerce_percent(42.9) == 42
        assert _coerce_percent(100) == 100

    def test_clamps_out_of_range(self):
        from api.routes.worker_ws import _coerce_percent
        assert _coerce_percent(150) == 100
        assert _coerce_percent(-5) == 0
        assert _coerce_percent(1e9) == 100

    def test_garbage_becomes_zero(self):
        from api.routes.worker_ws import _coerce_percent
        assert _coerce_percent("nonsense") == 0
        assert _coerce_percent(None) == 0
        assert _coerce_percent(float("nan")) == 0


@pytest.mark.asyncio
async def test_worker_cannot_claim_job_owned_by_another_provider():
    """A job must only accept events from the provider it was assigned to."""
    websocket = DummyWebSocket(
        messages=[
            {
                "type": "job_progress",
                "job_id": "job-owned-elsewhere",
                "data": {"progress": 50, "message": "nope"},
            }
        ]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    with patch(
        "api.routes.worker_ws.get_session_context",
        side_effect=lambda *a, **k: _fake_session_context(
            _owned_session(provider_id="provider-b")
        ),
    ), patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    job_service.update_job.assert_not_awaited()
    assert any(
        isinstance(sent, dict) and "not assigned" in str(sent.get("message", ""))
        for sent in websocket.sent
    )


@pytest.mark.asyncio
async def test_worker_cannot_claim_unassigned_job():
    """provider_id IS NULL must not make a job claimable by any worker."""
    websocket = DummyWebSocket(
        messages=[
            {
                "type": "job_completed",
                "job_id": "job-unassigned",
                "result": {"outputs": []},
            }
        ]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    finalize = AsyncMock()
    session = MagicMock()
    session.get.return_value = SimpleNamespace(provider_id=None)
    with patch(
        "api.routes.worker_ws.get_session_context",
        side_effect=lambda *a, **k: _fake_session_context(session),
    ), patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service), \
         patch("services.job_processing.finalize_successful_job", finalize):
        await worker_websocket(websocket, "provider-a", "token-1")

    finalize.assert_not_awaited()


# ============================================================================
# The declared protocol
# ============================================================================
#
# The wire format is frozen. These tests exist so that "the contract is declared
# once" and "nothing changed on the wire" are both enforced, rather than left to
# whoever reads the two halves of the socket next.

REFERENCE_CLIENT = Path(__file__).parent.parent / "scripts" / "external_worker_client.py"


class TestProtocolIsDeclaredOnce:
    """A message type must be declared in the contract AND handled/sent.

    Before the unification the handler branched on `data.get("type")` and the
    senders built dicts inline, so a type added on one side was invisible on the
    other. These assertions are what make that impossible.
    """

    def test_every_declared_inbound_type_has_a_handler(self):
        unhandled = set(INBOUND_MESSAGES.values()) - set(INBOUND_HANDLERS)
        assert unhandled == set(), f"declared but not dispatched: {unhandled}"

    def test_no_handler_for_an_undeclared_type(self):
        orphan = set(INBOUND_HANDLERS) - set(INBOUND_MESSAGES.values())
        assert orphan == set(), f"dispatched but not declared: {orphan}"

    def test_no_type_is_used_in_both_directions(self):
        assert set(INBOUND_MESSAGES) & set(OUTBOUND_MESSAGES) == set()

    def test_registry_keys_come_from_each_model_literal(self):
        for name, model in {**INBOUND_MESSAGES, **OUTBOUND_MESSAGES}.items():
            assert model.model_fields["type"].default == name, model.__name__

    def test_worker_message_types_is_the_union(self):
        assert WORKER_MESSAGE_TYPES == set(INBOUND_MESSAGES) | set(OUTBOUND_MESSAGES)


class TestWireFormatUnchanged:
    """Byte-for-byte the frames the backend sends, as they were before."""

    def test_outbound_models_serialise_to_the_legacy_dicts(self):
        assert ConnectedMessage(
            provider_id="p", message="Connected to ComfyUI backend"
        ).model_dump() == {
            "type": "connected",
            "provider_id": "p",
            "message": "Connected to ComfyUI backend",
        }
        assert PendingModelsMessage(models=[{"name": "m"}]).model_dump() == {
            "type": "pending_models",
            "models": [{"name": "m"}],
        }
        assert HeartbeatAckMessage().model_dump() == {"type": "heartbeat_ack"}
        assert ProtocolErrorMessage(message="boom").model_dump() == {
            "type": "error",
            "message": "boom",
        }
        assert JobDispatchMessage(
            data={"id": "job-1", "workflow": {"1": {}}, "metadata": {}}
        ).model_dump() == {
            "type": "job",
            "data": {"id": "job-1", "workflow": {"1": {}}, "metadata": {}},
        }
        assert CancelJobMessage(job_id="job-1").model_dump() == {
            "type": "cancel_job",
            "job_id": "job-1",
        }

    def test_type_is_the_first_key_of_every_frame(self):
        # JSON object order is not semantically meaningful, but the reference
        # client and the log lines it produces read the same way, and a
        # reordering here would be a gratuitous diff against the old literals.
        for name, model in OUTBOUND_MESSAGES.items():
            fields = list(model.model_fields)
            assert fields[0] == "type", f"{name}: {fields}"
            assert "type" in fields, name

    def test_reference_client_only_speaks_declared_types(self):
        """The working reference client must stay inside the declared contract.

        Its docstring is the protocol it implements, so read the types from
        there rather than restating them here — a type added to the client
        without a declaration fails this test.
        """
        source = REFERENCE_CLIENT.read_text()
        documented = ast.get_docstring(ast.parse(source)) or ""
        spoken = set(re.findall(r'"type":\s*"([a-z_]+)"', documented))
        assert spoken, "could not find the protocol block in the reference client"
        assert spoken <= set(WORKER_MESSAGE_TYPES), f"undeclared: {spoken - set(WORKER_MESSAGE_TYPES)}"
        # And the contract covers everything the client documents, in both
        # directions — otherwise a documented frame has no declaration to build
        # it from.
        assert set(WORKER_MESSAGE_TYPES) == spoken


class TestParseWorkerMessage:
    def test_parses_each_declared_inbound_type(self):
        for name, model in INBOUND_MESSAGES.items():
            assert parse_worker_message({"type": name}).type == name

    def test_canonical_task_event_progress(self):
        parsed = parse_worker_message(
            {"type": "job_progress", "job_id": "j1", "data": {"event": "progress", "value": 42}}
        )
        assert isinstance(parsed, JobProgressMessage)
        assert parsed.job_id == "j1"
        assert parsed.data == {"event": "progress", "value": 42}

    def test_legacy_progress_shape(self):
        parsed = parse_worker_message(
            {"type": "job_progress", "job_id": "j1", "data": {"progress": 42, "message": "node 7"}}
        )
        assert parsed.data == {"progress": 42, "message": "node 7"}

    @pytest.mark.parametrize(
        "frame,expected",
        [
            ({"type": "job_progress", "data": {"job_id": "in-data"}}, "in-data"),
            ({"type": "job_progress", "data": {"id": "as-id"}}, "as-id"),
            ({"type": "job_progress", "job_id": "top", "data": {"job_id": "in-data"}}, "top"),
        ],
    )
    def test_job_id_resolves_from_all_three_locations(self, frame, expected):
        assert parse_worker_message(frame).job_id == expected

    def test_non_dict_data_becomes_empty(self):
        # Pre-existing behaviour: a `data` that is not an object is ignored.
        assert parse_worker_message({"type": "job_progress", "data": "nope"}).data == {}

    def test_completed_and_failed_defaults(self):
        assert parse_worker_message({"type": "job_completed", "job_id": "j"}).result == {}
        assert parse_worker_message({"type": "job_failed", "job_id": "j"}).error == "Unknown error"

    def test_extra_fields_are_tolerated(self):
        parsed = parse_worker_message(
            {"type": "job_started", "job_id": "j", "worker_id": "w", "nested": {"a": 1}}
        )
        assert parsed.job_id == "j"

    @pytest.mark.parametrize(
        "frame",
        [
            {},                                    # no type
            {"type": None},
            {"type": "not_a_real_type"},
            {"type": "job_completed", "result": ["not-an-object"]},
            "not-a-dict",
            ["not-a-dict"],
        ],
    )
    def test_undeclared_or_malformed_frames_are_ignored_not_raised(self, frame):
        # The old if/elif chain fell through for an unrecognised `type` and kept
        # reading; a malformed frame must not take the socket down either.
        assert parse_worker_message(frame) is None


@pytest.mark.asyncio
async def test_worker_websocket_accepts_canonical_task_event_progress():
    """The canonical `{"event":"progress","value":N}` shape, end to end."""
    websocket = DummyWebSocket(
        messages=[
            {
                "type": "job_progress",
                "job_id": "job-canonical",
                "data": {"event": "progress", "value": 17},
            }
        ]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    job_service.update_job.assert_awaited_with(
        "job-canonical",
        progress=17,
        overall_progress=17,
    )


@pytest.mark.asyncio
async def test_worker_websocket_ignores_unknown_message_type():
    """An undeclared `type` must not disconnect the worker or touch any job."""
    websocket = DummyWebSocket(
        messages=[{"type": "who_knows", "job_id": "job-x"}, {"type": "heartbeat"}]
    )
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    job_service = AsyncMock()

    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("services.job_service.JobService", return_value=job_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    job_service.update_job.assert_not_awaited()
    # The frame after the unknown one was still processed.
    assert {"type": "heartbeat_ack"} in websocket.sent


@pytest.mark.asyncio
async def test_worker_websocket_heartbeat_ack_shape():
    websocket = DummyWebSocket(messages=[{"type": "heartbeat"}])
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider

    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    assert {"type": "heartbeat_ack"} in websocket.sent


@pytest.mark.asyncio
async def test_worker_websocket_welcome_frame_shape():
    websocket = DummyWebSocket()
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider

    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    assert websocket.sent[0] == {
        "type": "connected",
        "provider_id": "provider-a",
        "message": "Connected to ComfyUI backend",
    }


@pytest.mark.asyncio
async def test_no_pending_models_frame_on_connect_when_the_queue_is_empty():
    """The connect-time push is conditional; `get_pending_models` is not.

    A worker connecting with nothing to download gets only the welcome frame —
    it must not start receiving a `pending_models` frame the old handler never
    sent in that case.
    """
    websocket = DummyWebSocket()
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    model_service = MagicMock()
    model_service.get_pending_downloads.return_value = []

    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("api.routes.worker_ws.get_model_service_v2", return_value=model_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    assert [s["type"] for s in websocket.sent] == ["connected"]


@pytest.mark.asyncio
async def test_get_pending_models_always_answers_even_when_empty():
    websocket = DummyWebSocket(messages=[{"type": "get_pending_models"}])
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    model_service = MagicMock()
    model_service.get_pending_downloads.return_value = []

    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("api.routes.worker_ws.get_model_service_v2", return_value=model_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    assert {"type": "pending_models", "models": []} in websocket.sent


@pytest.mark.asyncio
async def test_pending_downloads_are_pushed_on_connect():
    websocket = DummyWebSocket()
    provider = SimpleNamespace(config={"worker_token": "token-1"})
    provider_service = AsyncMock()
    provider_service.get_provider.return_value = provider
    model_service = MagicMock()
    model_service.get_pending_downloads.return_value = [{"name": "sdxl.safetensors"}]

    with patch("api.routes.worker_ws.get_session_context", side_effect=lambda *a, **k: _fake_session_context(_owned_session())), \
         patch("services.provider_service.ProviderService", return_value=provider_service), \
         patch("api.routes.worker_ws.get_model_service_v2", return_value=model_service):
        await worker_websocket(websocket, "provider-a", "token-1")

    assert websocket.sent[1] == {
        "type": "pending_models",
        "models": [{"name": "sdxl.safetensors"}],
    }
