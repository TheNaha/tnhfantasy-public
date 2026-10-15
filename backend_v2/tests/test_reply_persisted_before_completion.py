"""A job must not go COMPLETED before its chat reply is a row.

The reply used to be written by the event bus consumer, which is downstream of
a fire-and-forget task (`start_background_task(complete_when_ready())`) and a
10 000-deep in-memory buffer that evicts. A dropped JOB_COMPLETED meant a paid
reply existed nowhere: the text was shown to the user, then vanished on reload,
recoverable only by `POST /api/jobs/reconcile-chat-replies` — an endpoint with
no frontend consumer and no scheduler caller.

`finalize_persisted_job_outputs` now writes the chat reply before calling
`complete_job`, so the invariant "job COMPLETED => its reply is a row" holds at
the point of completion. The consumer still runs when the event arrives and
skips on the source-job-id stamp both paths share, so this is not a second write.

The residual window is now the duration of one write rather than the whole
generation.
"""

import pytest


@pytest.fixture
def chat_job(session):
    from core.entities import Chat, Job, JobStatus

    chat = Chat(id="chat-durability", character_id=None)
    session.add(chat)
    session.flush()
    job = Job(
        id="job-durability",
        task_type="llm",
        status=JobStatus.POST_PROCESSING,
        workflow={"messages": []},
        metadata_={"chat_id": "chat-durability"},
        outputs=[{"role": "assistant", "content": "A reply that must survive."}],
    )
    session.add(job)
    session.commit()
    return chat, job


def _message_exists(engine, chat_id: str) -> bool:
    from sqlmodel import Session, select

    from core.entities import Message

    with Session(engine) as s:
        return bool(s.exec(select(Message).where(Message.chat_id == chat_id)).first())


class TestTheWriteIsIdempotent:
    async def test_a_second_delivery_does_not_duplicate(self, session, chat_job):
        """The event bus still delivers the same job afterwards.

        This is what makes the durable write safe: both paths run the same code,
        and the guard is the shared `source_job_id` stamp — the same field
        `find_unpersisted_chat_replies` uses to decide a reply was never written.
        """
        from sqlmodel import Session, select

        from core.entities import Message

        from services.world_integration_service import (
            _handle_chat_reply,
            _reply_already_stamped,
        )

        chat, job = chat_job
        job_data = {
            "id": job.id,
            "metadata": {"chat_id": "chat-durability"},
            "outputs": job.outputs,
        }

        assert _reply_already_stamped(session, job.id) is False

        await _handle_chat_reply(job_data)
        await _handle_chat_reply(job_data)  # the event bus's second delivery
        await _handle_chat_reply(job_data)  # and a reconcile replay

        with Session(session.get_bind()) as check:
            msgs = check.exec(select(Message).where(Message.chat_id == "chat-durability")).all()
        assert len(msgs) == 1, f"duplicated reply: {len(msgs)} rows"
        assert msgs[0].content == "A reply that must survive."
        assert _reply_already_stamped(session, job.id) is True

    async def test_the_stamp_is_the_same_one_reconcile_reads(self, session, chat_job):
        """The guard and the recovery query must agree on one field.

        If they disagreed, the write would be duplicated on every replay — or,
        worse, the recovery would keep reporting a reply that exists as lost and
        resurrect it at the end of the chat.
        """
        from services.world_integration_service import SOURCE_JOB_ID_METADATA_KEY

        chat, job = chat_job
        await __import__(
            "services.world_integration_service", fromlist=["_handle_chat_reply"]
        )._handle_chat_reply(
            {
                "id": job.id,
                "metadata": {"chat_id": "chat-durability"},
                "outputs": job.outputs,
            }
        )

        from sqlmodel import Session, select

        from core.entities import Message

        with Session(session.get_bind()) as check:
            msg = check.exec(select(Message).where(Message.chat_id == "chat-durability")).one()
        assert msg.message_metadata[SOURCE_JOB_ID_METADATA_KEY] == job.id


class TestFinalizationWritesTheReply:
    """The durable write must be IN finalization, not only in the consumer.

    The idempotency test above is satisfied by the consumer alone, so it cannot
    see the regression that matters: a reply written only off the event bus is
    still one dropped JOB_COMPLETED away from being paid for and stored
    nowhere. Asserted structurally on the AST, because the write sits inside a
    closure and the test cannot drive a real LLM provider.
    """

    def test_complete_when_ready_writes_before_complete_job(self):
        import ast
        import inspect

        from services import job_processing

        # Locate the closure `complete_when_ready` inside the source.
        source = inspect.getsource(job_processing.finalize_persisted_job_outputs)
        tree = ast.parse(source)

        writes, completes = [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = ast.unparse(node.func)
                # The dispatch table entry, not the handler name: the durable
                # write is now `_EVENT_DISPATCH[type](payload, session)`, which
                # covers replies, narrations and chat images.
                if "_EVENT_DISPATCH" in called:
                    writes.append(node.lineno)
                if called == "complete_job":
                    completes.append(node.lineno)

        assert writes, "finalize_persisted_job_outputs never writes the chat artefact"
        assert completes, "no complete_job call found"
        assert min(writes) < min(completes), (
            "the chat artefact must be written before the job goes COMPLETED, so "
            "COMPLETED implies it is durable"
        )

    def test_the_write_is_gated_on_the_artefact_job_type(self):
        """Not every job produces a chat artefact; the write must be selective.

        Image and TTS jobs go through the same finalization, and writing a
        narrator paragraph for one would either no-op or insert a wrong row.

        The gate is the `_PRECOMPLETION_PERSISTED_TYPES` set, not a literal
        string compare. That is the whole point of the change: a second copy of
        "which kinds get a durable write" is the shape that left narrator and
        chat_image out for as long as they were.
        """
        import inspect

        from services import job_processing

        source = inspect.getsource(job_processing.finalize_persisted_job_outputs)
        assert "_PRECOMPLETION_PERSISTED_TYPES" in source, (
            "the durable write is not gated on the set of artefact job types"
        )
        assert 'event_extra.get("type")' in source, (
            "the gate must read the resolved event type off event_extra"
        )
