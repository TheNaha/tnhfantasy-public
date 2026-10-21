"""Regression tests for audit-2026-10-21 finding 10: two routes ran blocking
database queries on the event loop.

`evaluate_chat_director` performed three queries (the chat, its character and
its recent messages) inline in an `async def`, and
`_cancel_inflight_chat_jobs` ran a `select(...).all()` the same way. Both
block the event loop for the duration of the query, which means every other
request in the process waits for them.

The neighbouring routes in the same file already used `asyncio.to_thread`;
these two did not.
"""

from __future__ import annotations

import threading
import uuid

from sqlmodel import Session

from core.entities import Chat, Message, MessageKind, MessageRole


def _seed_chat(session: Session) -> Chat:
    chat = Chat(
        id=str(uuid.uuid4()),
        name="Scene",
        persona_name="Player",
        director_enabled=True,
    )
    session.add(chat)
    session.commit()
    session.add(
        Message(
            id=str(uuid.uuid4()),
            chat_id=chat.id,
            role=MessageRole.USER,
            kind=MessageKind.USER,
            content="Where are we going?",
        )
    )
    session.commit()
    session.refresh(chat)
    return chat


class TestTheDirectorRouteDoesNotBlockTheLoop:
    def test_the_reads_run_on_another_thread(self, client, session, monkeypatch):
        """The reads must not happen on the thread the coroutine runs on."""
        from infrastructure.repositories.chat_repo import ChatRepository

        chat = _seed_chat(session)

        read_threads: list[threading.Thread] = []
        coroutine_threads: list[threading.Thread] = []

        original_get = ChatRepository.get

        def _get(self, *args, **kwargs):
            read_threads.append(threading.current_thread())
            return original_get(self, *args, **kwargs)

        monkeypatch.setattr(ChatRepository, "get", _get)

        async def _evaluate_scene(self, **kwargs):
            coroutine_threads.append(threading.current_thread())
            from services.decision_schema import DirectorDecisionResult

            return DirectorDecisionResult()

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_scene", _evaluate_scene
        )
        monkeypatch.setattr(
            "services.updater_service.record_director_decision",
            lambda *args, **kwargs: {},
        )

        response = client.post(f"/api/v2/chats/{chat.id}/director/evaluate", json={})
        assert response.status_code == 200, response.text

        assert read_threads, "the chat was never read"
        assert coroutine_threads, "the Director never ran"
        assert all(
            read is not coroutine for read in read_threads for coroutine in coroutine_threads
        ), "the chat was read on the event loop thread"


class TestTheCancelHelperDoesNotBlockTheLoop:
    async def test_the_query_runs_on_another_thread(self, session, monkeypatch):
        from api.routes.world_vault.chats import _cancel_inflight_chat_jobs

        query_threads: list[threading.Thread] = []
        original_exec = session.exec

        def _exec(*args, **kwargs):
            query_threads.append(threading.current_thread())
            return original_exec(*args, **kwargs)

        monkeypatch.setattr(session, "exec", _exec)

        cancelled = await _cancel_inflight_chat_jobs(
            session, "no-such-chat", reason="test"
        )

        assert cancelled == 0
        assert query_threads, "the query never ran"
        assert all(
            thread is not threading.current_thread() for thread in query_threads
        ), "the cancel query ran on the event loop thread"
