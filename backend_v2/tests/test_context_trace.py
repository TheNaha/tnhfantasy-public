"""The per-exchange context trace: what a reply was actually told.

`SystemPromptPanel` already showed the system prompt and where each section came
from, and nothing showed the conversation. Which turns were sent, which were
labelled as narration, which was pruned to fit the budget — all invisible. A
reply that ignored something from three turns ago was indistinguishable from one
whose text had been trimmed out entirely, and the speaker labelling added in the
turn-mapping work could not be verified without reading the payload.

The trace is taken INSIDE the context build, before the internal
`_pinned` / `_kind` keys are stripped, and carried on the job onto the message
row. That ordering is the whole design: reconstructing it later would build
today's context, not the one that produced this reply.
"""

import pytest
from sqlmodel import Session, select

import infrastructure.database as infra_database

from core.entities import Character, Chat, Message, MessageRole
from services.context_builder import (
    TRACE_SECTION_LIMIT,
    TRACE_TURN_LIMIT,
    build_chat_context_with_sections,
    context_trace_digest,
)


@pytest.fixture
def wired_engine(engine, monkeypatch):
    monkeypatch.setattr(infra_database, "engine", engine)
    return engine


def _seeded(session):
    char = Character(name="Aria", description="A guard.")
    session.add(char)
    session.commit()
    session.refresh(char)
    chat = Chat(name="C", character_id=char.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return char, chat


def _trace(**overrides):
    base = dict(
        system_prompt="You are Aria.",
        sections=[{"label": "Character", "source": "character", "content": "Aria"}],
        turns=[],
        input_messages=[],
        speaker_names={},
        speaker_total=1,
        roleplay_config=None,
        max_context_tokens=4096,
    )
    base.update(overrides)
    return context_trace_digest(**base)


class TestDigestShape:
    def test_a_digest_carries_config_speakers_sections_and_turns(self):
        trace = _trace(
            turns=[
                {"role": "user", "content": "I knock.", "_pinned": False},
                {"role": "assistant", "content": "[Narration] Rain.", "_kind": "narrator", "_pinned": False},
            ],
            speaker_names={"c1": "Bram"},
            speaker_total=2,
        )
        assert trace["v"] == 1
        assert trace["config"]["narrator_prefix"] == "[Narration]"
        assert trace["speakers"] == {"count": 2, "named": ["Bram"]}
        assert [t["role"] for t in trace["turns"]] == ["user", "assistant"]
        assert [t["kind"] for t in trace["turns"]] == [None, "narrator"]
        assert trace["budget_tokens"] == 4096
        assert trace["system_prompt_chars"] == len("You are Aria.")

    def test_it_stores_sizes_not_text(self):
        """A digest, because this lives on a message row.

        A full copy of the payload would multiply every reply's storage by the
        length of the conversation. What the inspector answers — was the
        narration labelled, which turns existed, what was pruned — needs none of
        the words.
        """
        trace = _trace(turns=[{"role": "user", "content": "x" * 500, "_pinned": False}])
        assert trace["turns"][0]["chars"] == 500
        assert "x" * 100 not in repr(trace)

    def test_an_assistant_turn_gets_a_preview_so_a_digest_is_readable(self):
        """The preview is what makes a turn recognisable as Bram or a narration."""
        trace = _trace(
            turns=[{"role": "assistant", "content": "Bram: The door is barred.", "_pinned": False}]
        )
        assert trace["turns"][0]["label"] == "Bram: The door is barred."

    def test_user_turn_has_preview(self):
        trace = _trace(turns=[{"role": "user", "content": "I knock.", "_pinned": False}])
        assert trace["turns"][0]["label"] == "I knock."


    def test_world_state_is_expected_and_not_reported_as_dropped(self):
        """It is derived state, rebuilt on every build."""
        from core.entities import Message as _M

        msg = _M(chat_id="c", role=MessageRole.SYSTEM, content="dark")
        msg.message_metadata = {"source": "world_state"}
        trace = _trace(input_messages=[msg])
        assert trace["dropped"] == []

    def test_an_unexplained_message_is_reported_as_dropped(self):
        from core.entities import Message as _M

        msg = _M(chat_id="c", role=MessageRole.SYSTEM, content="something")
        msg.message_metadata = {"source": "injected"}
        trace = _trace(input_messages=[msg])
        assert trace["dropped"] == ["injected"]

    def test_truncation_is_declared_rather_than_looking_complete(self):
        trace = _trace(
            turns=[{"role": "user", "content": "x", "_pinned": False}] * (TRACE_TURN_LIMIT + 1)
        )
        assert trace["truncated"] is True
        assert len(trace["turns"]) == TRACE_TURN_LIMIT

    def test_sections_are_capped_too(self):
        trace = _trace(sections=[{"label": str(i), "content": "x"} for i in range(TRACE_SECTION_LIMIT + 5)])
        assert trace["truncated"] is True
        assert len(trace["sections"]) == TRACE_SECTION_LIMIT


class TestTraceIsCaptured:
    def test_a_trace_out_dict_is_filled_by_the_build(self, session, wired_engine):
        char, _chat = _seeded(session)

        trace = {}
        build_chat_context_with_sections(
            session,
            [{"role": "user", "content": "I knock."}],
            characters=[char],
            persona_name="Kai",
            trace_out=trace,
        )
        assert trace["v"] == 1
        assert trace["speakers"]["count"] == 1
        # The system prompt leads, which is the whole context; the conversation
        # follows it.
        assert [t["role"] for t in trace["turns"]] == ["system", "user"]

    def test_no_trace_out_means_no_overhead_and_no_change(self, session, wired_engine):
        """The out-param default must be inert for every existing caller."""
        char, _chat = _seeded(session)

        result = build_chat_context_with_sections(
            session, [{"role": "user", "content": "I knock."}], characters=[char]
        )
        assert len(result) == 3
        # Still the three-tuple it always was, and no trace leaked into the
        # payload the provider receives.
        assert result[1][-1] == {"role": "user", "content": "I knock."}
        assert all("_kind" not in m and "_pinned" not in m for m in result[1])


class TestTraceReachesTheMessage:
    def test_the_job_metadata_carries_it_and_the_handler_stamps_it(
        self, session, wired_engine
    ):
        import asyncio

        import services.world_integration_service as wis

        char, chat = _seeded(session)
        user = Message(chat_id=chat.id, role=MessageRole.USER, content="I knock.")
        session.add(user)
        session.commit()
        session.refresh(user)

        trace = _trace(
            turns=[{"role": "user", "content": "I knock.", "_pinned": False}],
            speaker_names={},
            speaker_total=1,
        )
        payload = {
            "id": "job-trace-1",
            "metadata": {
                "chat_id": chat.id,
                "character_id": char.id,
                "agentic": False,
                "context_trace": trace,
            },
            "outputs": [{"role": "assistant", "content": "The door opens."}],
        }

        asyncio.run(wis._handle_chat_reply(payload))

        with Session(wired_engine) as check:
            reply = check.exec(select(Message).where(Message.chat_id == chat.id)).all()[-1]
        assert reply.message_metadata.get("context_trace", {}).get("v") == 1
        assert reply.message_metadata["context_trace"]["turns"][0]["role"] == "user"

    def test_a_trace_with_no_version_is_ignored_rather_than_stored(
        self, session, wired_engine
    ):
        """A malformed blob must surface as a missing feature, not a UI crash."""
        import asyncio

        import services.world_integration_service as wis

        char, chat = _seeded(session)
        payload = {
            "id": "job-trace-2",
            "metadata": {
                "chat_id": chat.id,
                "character_id": char.id,
                # A dict from a future or older writer that this version cannot
                # interpret.
                "context_trace": {"something": "else"},
            },
            "outputs": [{"role": "assistant", "content": "Hello."}],
        }

        asyncio.run(wis._handle_chat_reply(payload))

        with Session(wired_engine) as check:
            reply = check.exec(select(Message).where(Message.chat_id == chat.id)).all()[-1]
        assert "context_trace" not in reply.message_metadata
