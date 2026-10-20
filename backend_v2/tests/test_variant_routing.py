"""Laya's routing decision has to reach the model.

Laya is the Director: it routes a turn to an agent and it picks that agent's
sub-variant — the character agent has a "tense" / "tender" / "playful" one,
the narrator a "combat" / "quiet" / "travel" one. The whole point of the
sub-variant system is that Laya finds the best agent with the best prompt.

It did not. Laya was asked the variant question, Laya answered, and the
answer was dropped on the normal chat path: `resolve_agent` was called
without `variant_slug`, and the character branch never resolved an agent
profile at all. Six seeded variants existed and none of them could change a
prompt a user would see.

The chain path had the mirror-image bug: it passed the *character card's*
slug where the *agent's* slug was wanted, so the variant question was never
asked — and the variant it did resolve was written to
`workflow["character_system_prompt"]`, a key no engine reads.

These tests pin the whole route: the question is asked, the answer is
applied, the character card survives the overlay, and `{{char}}` is rendered.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from sqlmodel import Session

from core.entities import (
    AgentProfile,
    AgentPromptVariant,
    Character,
    Chat,
    Message,
    MessageKind,
    MessageRole,
)


def _seed_agent(session: Session, slug: str, name: str, template: str) -> AgentProfile:
    profile = AgentProfile(
        id=str(uuid.uuid4()),
        slug=slug,
        name=name,
        agent_type="generation",
        description=f"{name} profile",
        system_prompt_template=template,
        model_target="rp",
        is_builtin=False,
        enabled=True,
    )
    session.add(profile)
    session.commit()
    return profile


def _seed_variant(
    session: Session,
    agent_id: str,
    slug: str,
    template: str,
    *,
    is_active: bool = True,
    hint: str = "Use when the scene calls for it.",
) -> AgentPromptVariant:
    # `selection_hint` is not optional in practice: `get_agent_variant_options`
    # only offers a variant that has a hint or a description, so a variant
    # without one can never be selected by Laya — it is invisible to the
    # routing that is supposed to choose it.
    variant = AgentPromptVariant(
        id=str(uuid.uuid4()),
        agent_id=agent_id,
        slug=slug,
        name=slug,
        system_prompt_template=template,
        description="",
        selection_hint=hint,
        tags=[],
        is_active=is_active,
        is_builtin=False,
    )
    session.add(variant)
    session.commit()
    return variant


def _seed_chat(session: Session, character: Character) -> Chat:
    chat = Chat(
        id=str(uuid.uuid4()),
        name="Scene",
        character_id=character.id,
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


def _system_text(workflow: dict) -> str:
    """The concatenated system messages of a built workflow."""
    return "\n".join(
        m.get("content", "") for m in workflow.get("messages", []) if m.get("role") == "system"
    )


class TestAgentResolution:
    """`chats._resolve_actor_agent` — which agent, and which of its variants."""

    def test_layas_variant_is_resolved(self, session):
        from api.routes.world_vault.chats import _resolve_actor_agent

        profile = _seed_agent(session, "character", "Character", "You are the character.")
        _seed_variant(session, profile.id, "character-tense", "The moment is tense.")

        class _Req:
            narrate = False

        class _Chat:
            persona_name = "Player"
            story_location = ""
            story_time = ""

        resolved = _resolve_actor_agent(
            session,
            chat=_Chat(),
            request=_Req(),
            director_decision_dict={
                "selected_agent": "character",
                "selected_variant": "character-tense",
            },
            characters=None,
        )

        assert resolved["slug"] == "character"
        assert resolved["variant_slug"] == "character-tense"
        assert "tense" in (resolved["prompt"] or "")

    def test_a_variant_from_another_agent_does_not_apply(self, session):
        """A character variant is meaningless for the narrator.

        When the user forces a narration but Laya had chosen the character,
        the character's variant must not be applied to the narrator.
        `resolve_agent` scopes the variant lookup to the agent's own rows, so
        it falls back to the narrator's active variant.
        """
        from api.routes.world_vault.chats import _resolve_actor_agent

        char_profile = _seed_agent(session, "character", "Character", "You are the character.")
        _seed_variant(session, char_profile.id, "character-tense", "The moment is tense.")
        narrator = _seed_agent(session, "narrator", "Narrator", "You are the narrator.")
        _seed_variant(session, narrator.id, "narrator-quiet", "A quiet moment.")

        class _Req:
            narrate = True

        class _Chat:
            persona_name = "Player"
            story_location = ""
            story_time = ""

        resolved = _resolve_actor_agent(
            session,
            chat=_Chat(),
            request=_Req(),
            director_decision_dict={
                "selected_agent": "character",
                "selected_variant": "character-tense",
            },
            characters=None,
        )

        assert resolved["slug"] == "narrator"
        assert resolved["variant_slug"] != "character-tense"
        assert "tense" not in (resolved["prompt"] or "").lower()


class TestVariantOverlaySection:
    """The character variant is an overlay on the character card."""

    def test_the_overlay_is_its_own_section(self, session):
        from services.context_builder import build_system_prompt_sections

        char = Character(id=str(uuid.uuid4()), name="Aria", description="A courier")
        session.add(char)
        session.commit()

        sections = build_system_prompt_sections(
            session,
            characters=[char],
            agent_variant_prompt="The moment is tense.",
        )
        keys = [s["key"] for s in sections]
        assert "agent_variant" in keys

        overlay = next(s for s in sections if s["key"] == "agent_variant")
        assert overlay["content"] == "The moment is tense."
        assert overlay["source"] == "agent_variant"

    def test_the_overlay_sits_after_the_character_card(self, session):
        """The card says WHO the character is; the overlay says HOW to play
        them right now. Both are needed, and the card comes first."""
        from services.context_builder import build_system_prompt_sections

        char = Character(id=str(uuid.uuid4()), name="Aria", description="A courier")
        session.add(char)
        session.commit()

        sections = build_system_prompt_sections(
            session,
            characters=[char],
            agent_variant_prompt="The moment is tense.",
        )
        keys = [s["key"] for s in sections]
        assert keys.index("agent_variant") > keys.index(f"character_{char.id}")

    def test_no_overlay_means_no_section(self, session):
        from services.context_builder import build_system_prompt_sections

        char = Character(id=str(uuid.uuid4()), name="Aria", description="A courier")
        session.add(char)
        session.commit()

        sections = build_system_prompt_sections(session, characters=[char])
        assert "agent_variant" not in [s["key"] for s in sections]


class TestMainPathHonoursTheVariant:
    """The normal chat path — a user message — is where this matters most."""

    async def _send(self, session, client, chat, monkeypatch, decision):
        """Drive `_send_message` with Laya's decision stubbed in."""
        from api.routes.world_vault import chats as chats_mod

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_pre_generation_triage",
            AsyncMock(return_value=decision),
        )
        monkeypatch.setattr(
            "services.pipeline_runner.run_from",
            AsyncMock(
                return_value={
                    "director_decision_dict": decision.to_dict(),
                    "halt": False,
                }
            ),
        )
        from infrastructure.repositories.chat_repo import ChatRepository
        from infrastructure.repositories.message_repo import MessageRepository

        return await chats_mod._send_message(
            session,
            ChatRepository(session),
            MessageRepository(session),
            chat.id,
            _SendReq(),
        )

    async def test_the_characters_variant_reaches_the_prompt(self, session, client, monkeypatch):
        from services.decision_schema import DirectorDecisionResult

        profile = _seed_agent(session, "character", "Character", "You are the character.")
        _seed_variant(
            session,
            profile.id,
            "character-tense",
            "You are roleplaying as {{char}}. The moment is tense.",
        )

        char = Character(id=str(uuid.uuid4()), name="Aria", description="A courier")
        session.add(char)
        session.commit()
        chat = _seed_chat(session, char)

        decision = DirectorDecisionResult(
            next_speaker="character",
            selected_agent="character",
            selected_variant="character-tense",
            workflow_stage="triage",
        )

        sent = {}

        async def _fake_submit(session_, workflow, metadata, **kwargs):
            sent["workflow"] = workflow
            sent["metadata"] = metadata
            return _FakeJob()

        monkeypatch.setattr("api.routes.world_vault.chats.submit_llm_job", _fake_submit)

        await self._send(session, client, chat, monkeypatch, decision)

        assert sent, "no LLM job was submitted"
        system_text = _system_text(sent["workflow"])
        assert "The moment is tense" in system_text, (
            "Laya's chosen variant did not reach the character's system prompt"
        )
        # The character card must survive the overlay.
        assert "Aria" in system_text or "courier" in system_text.lower(), (
            "the character card was replaced by the variant overlay"
        )

    async def test_the_macro_is_rendered_not_emitted_literally(self, session, client, monkeypatch):
        from services.decision_schema import DirectorDecisionResult

        profile = _seed_agent(session, "character", "Character", "You are the character.")
        _seed_variant(
            session,
            profile.id,
            "character-playful",
            "You are roleplaying as {{char}}. Keep it playful.",
        )

        char = Character(id=str(uuid.uuid4()), name="Aria", description="A courier")
        session.add(char)
        session.commit()
        chat = _seed_chat(session, char)

        decision = DirectorDecisionResult(
            next_speaker="character",
            selected_agent="character",
            selected_variant="character-playful",
            workflow_stage="triage",
        )

        sent = {}

        async def _fake_submit(session_, workflow, metadata, **kwargs):
            sent["workflow"] = workflow
            sent["metadata"] = metadata
            return _FakeJob()

        monkeypatch.setattr("api.routes.world_vault.chats.submit_llm_job", _fake_submit)

        await self._send(session, client, chat, monkeypatch, decision)

        system_text = _system_text(sent["workflow"])
        assert "Aria" in system_text, "{{char}} was not rendered"
        assert "{{char}}" not in system_text, "{{char}} was emitted literally"


class TestChainPathAsksTheRightQuestion:
    """The chain had the mirror-image bug."""

    async def test_the_chained_triage_asks_about_the_agent_not_the_card(self, session, monkeypatch):
        """The chain must ask about the AGENT that plays the character.

        This is correct today, but only by accident. The chain used to pass
        `char_obj.slug` — the character CARD's slug — guarded by
        `hasattr(char_obj, "slug")`. `Character` has no `slug` column, so
        SQLModel drops the attribute and the guard always fell through to
        "character", which is the agent slug. The moment a Character grows a
        slug field, the chain would start asking about the card and the
        variant question would silently disappear again.

        The test pins the question that is actually being asked, so the
        accident cannot become a bug unnoticed.
        """
        from services.decision_schema import DirectorDecisionResult
        from services import pipeline_stages

        profile = _seed_agent(session, "character", "Character", "You are the character.")
        _seed_variant(session, profile.id, "character-tense", "The moment is tense.")

        char = Character(id=str(uuid.uuid4()), name="Aria", description="A courier", slug="aria")
        session.add(char)
        session.commit()
        chat = _seed_chat(session, char)

        captured = {}

        async def _fake_triage(self, **kwargs):
            captured.update(kwargs)
            return DirectorDecisionResult(
                next_speaker="character",
                selected_agent="character",
                selected_variant="character-tense",
                workflow_stage="triage",
            )

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_pre_generation_triage",
            _fake_triage,
        )
        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_turn_chaining",
            AsyncMock(
                return_value=DirectorDecisionResult(
                    next_speaker="character",
                    selected_agent="character",
                    continue_chain_probability=0.95,
                    workflow_stage="chaining",
                )
            ),
        )

        class _JobService:
            def __init__(self, session_):
                self.session = session_

            async def create_job(self, *, task_type, workflow, metadata):
                class _J:
                    id = "job-1"
                return _J()

        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", AsyncMock())

        await pipeline_stages.chain_stage(
            {
                "session": session,
                "job_service": _JobService(session),
                "chat_id": chat.id,
                "character_id": char.id,
                "last_speaker": "character",
                "current_turns": 1,
                "max_turns": 4,
                "autonomy_level": "balanced",
            }
        )

        assert captured.get("primary_character_slug") == "character", (
            "the chained triage asked about the character card's slug, so no "
            "agent profile matched and no variant question was offered"
        )

        # And the options that question would offer are the agent's.
        from services.laya_questions import get_agent_variant_options

        options = get_agent_variant_options(session, "character")
        assert "character-tense" in options, (
            "the character agent's variants are not offered for selection"
        )

    async def test_the_chained_character_variant_reaches_the_prompt(self, session, monkeypatch):
        from services.decision_schema import DirectorDecisionResult
        from services import pipeline_stages

        profile = _seed_agent(session, "character", "Character", "You are the character.")
        _seed_variant(
            session,
            profile.id,
            "character-tense",
            "You are roleplaying as {{char}}. The moment is tense.",
        )

        char = Character(id=str(uuid.uuid4()), name="Aria", description="A courier")
        session.add(char)
        session.commit()
        chat = _seed_chat(session, chat_character=char) if False else _seed_chat(session, char)

        chain = DirectorDecisionResult(
            next_speaker="character",
            selected_agent="character",
            continue_chain_probability=0.95,
            workflow_stage="chaining",
        )
        triage = DirectorDecisionResult(
            next_speaker="character",
            selected_agent="character",
            selected_variant="character-tense",
            workflow_stage="triage",
        )

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_turn_chaining",
            AsyncMock(return_value=chain),
        )
        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_pre_generation_triage",
            AsyncMock(return_value=triage),
        )

        created = {}

        class _JobService:
            def __init__(self, session_):
                self.session = session_

            async def create_job(self, *, task_type, workflow, metadata):
                created["workflow"] = workflow
                created["metadata"] = metadata

                class _J:
                    id = "job-1"
                return _J()

        enq = AsyncMock()
        monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enq)

        await pipeline_stages.chain_stage(
            {
                "session": session,
                "job_service": _JobService(session),
                "chat_id": chat.id,
                "character_id": char.id,
                "last_speaker": "character",
                "current_turns": 1,
                "max_turns": 4,
                "autonomy_level": "balanced",
            }
        )

        assert created, "the chain did not create a job"
        system_text = _system_text(created["workflow"])
        assert "The moment is tense" in system_text, (
            "the chained turn lost the character variant"
        )
        assert "{{char}}" not in system_text


class _FakeJob:
    id = "fake-job"
    status = "pending"


class _SendReq:
    """The real request model, minus the fields this path does not read."""

    def __init__(self):
        from api.routes.world_vault.chats import SendMessageRequest

        self._req = SendMessageRequest(
            role=MessageRole.USER,
            content="Where are we going?",
        )

    def __getattr__(self, name):
        return getattr(self._req, name)
