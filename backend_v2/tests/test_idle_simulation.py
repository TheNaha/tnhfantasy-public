# Tests for the idle simulation service (agent_simulation.py)

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from core.entities import Character, Chat, Job, JobStatus
from services import agent_simulation


@pytest.fixture
def chat_with_character(session):
    """Create a character + dormant idle-enabled chat for tick tests."""
    char = Character(name="Lyra Vale")
    session.add(char)
    session.commit()
    session.refresh(char)

    chat = Chat(
        name="Idle Chat",
        character_id=char.id,
        idle_sim_enabled=True,
        chat_type="chat",
        updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat


def _make_chat(session, *, idle_sim_enabled=True, updated_delta_minutes=120, character_id=None):
    chat = Chat(
        name="Idle Chat",
        character_id=character_id,
        idle_sim_enabled=idle_sim_enabled,
        chat_type="chat",
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=updated_delta_minutes),
    )
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat


def _make_job(session, chat_id, *, status=JobStatus.PENDING):
    job = Job(
        task_type="llm",
        workflow={},
        metadata_={"chat_id": chat_id, "type": "chat_reply", "workspace": "chat"},
        status=status,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _install_tick_mocks(monkeypatch, session, context_result=("", [])):
    """Point the tick's locally-imported dependencies at the test session."""
    from infrastructure import deps as infrastructure_deps
    from services import context_builder as cb
    from services import job_queue as jq

    @asynccontextmanager
    async def fake_session_context():
        yield session

    async def fake_build_context(messages, **kwargs):
        return context_result

    monkeypatch.setattr(infrastructure_deps, "get_session_context", fake_session_context)
    monkeypatch.setattr(cb, "build_chat_context_async", fake_build_context)
    monkeypatch.setattr(jq.queue_manager, "enqueue", AsyncMock())

    import config as app_config
    original_config = app_config.get_config
    monkeypatch.setattr(app_config, "get_config", lambda: {
        **original_config(),
        "ai": {**original_config().get("ai", {}), "idleSimEnabled": True},
    })

    return jq.queue_manager.enqueue


@pytest.mark.asyncio
async def test_tick_spawns_job_for_dormant_chat(session, monkeypatch, chat_with_character):
    chat = chat_with_character

    enqueue = _install_tick_mocks(
        monkeypatch, session,
        context_result=("You are Lyra.", [{"role": "user", "content": "hi"}]),
    )

    spawned = await agent_simulation.run_idle_simulation_tick()

    assert spawned == 1
    assert enqueue.call_count == 1
    job_id = enqueue.call_args.args[0]
    assert enqueue.call_args.kwargs["task_type"] == "llm"

    job = session.get(Job, job_id)
    assert job is not None
    assert job.task_type == "llm"
    assert job.metadata_.get("chat_id") == chat.id
    assert job.metadata_.get("source") == "idle_simulation"
    assert job.metadata_.get("idle_simulation") is True


@pytest.mark.asyncio
async def test_tick_skips_recently_active_chat(session, monkeypatch):
    _make_chat(session, updated_delta_minutes=5)

    enqueue = _install_tick_mocks(monkeypatch, session)

    spawned = await agent_simulation.run_idle_simulation_tick()

    assert spawned == 0
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_tick_skips_disabled_chat(session, monkeypatch):
    _make_chat(session, idle_sim_enabled=False)

    enqueue = _install_tick_mocks(monkeypatch, session)

    spawned = await agent_simulation.run_idle_simulation_tick()

    assert spawned == 0
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_tick_skips_chat_with_inflight_job(session, monkeypatch):
    chat = _make_chat(session)
    _make_job(session, chat.id, status=JobStatus.PENDING)

    enqueue = _install_tick_mocks(monkeypatch, session)

    spawned = await agent_simulation.run_idle_simulation_tick()

    assert spawned == 0
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_tick_skips_non_standard_chat_types(session, monkeypatch):
    session.add(Chat(
        name="Campaign",
        chat_type="campaign",
        idle_sim_enabled=True,
        updated_at=datetime.now(timezone.utc) - timedelta(hours=4),
    ))
    session.commit()

    enqueue = _install_tick_mocks(monkeypatch, session)

    spawned = await agent_simulation.run_idle_simulation_tick()

    assert spawned == 0
    enqueue.assert_not_called()