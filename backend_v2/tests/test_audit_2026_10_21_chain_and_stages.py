"""Regression tests for audit-2026-10-21 findings 7 and 9: the
`secondary_character` chain branch dropped the agent variant, and one
`except Exception` wrapped the whole stage walk.

Finding 7: `chain_stage` resolved the agent and Laya's chosen variant, and
the `narrator` and `character` branches used all three of them — the variant
overlay in the prompt, the agent's sampler overrides, and `selected_variant`
in the job metadata. The `secondary_character` branch used NONE of them, so
in a group chat the secondary always spoke with the base card, however Laya
had routed the turn.

Finding 9: the post-turn walk from the audit to the chain was wrapped in ONE
`except Exception`. A failure in the audit deleted the illustration, the
Statekeeper, the memory extraction AND the autonomous chain for that turn,
and the single WARNING that recorded it named no stage.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, select

from core.entities import (
    AgentProfile,
    AgentPromptVariant,
    Character,
    Chat,
    Job,
    Message,
    MessageKind,
    MessageRole,
)
from services.decision_schema import DirectorDecisionResult
from services.job_service import JobService


def _audit_decision(**overrides) -> DirectorDecisionResult:
    defaults = dict(
        next_speaker="character",
        selected_agent="character",
        agent_slug="character",
        is_complete=True,
        should_run_updater=False,
        triggered_gates=[],
        updater_gates={},
        should_trigger_image=False,
        continue_chain_probability=0.0,
        workflow_stage="audit",
    )
    defaults.update(overrides)
    return DirectorDecisionResult(**defaults)


@pytest.fixture
def no_enqueue(monkeypatch):
    """Keep the queue manager out of the test."""
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr("services.job_queue.queue_manager.enqueue", enqueue)
    return enqueue


class _RecordingLogger:
    """Capture the structured log calls a module makes.

    The logger is structlog, wired to stdout, so pytest's `caplog` does not
    see it. Replacing the module's logger object is the reliable way to see
    what it was told.
    """

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _record(event, **kwargs):
            self.calls.append((name, event, kwargs))

        return _record


def _seed_chat(session: Session, **overrides):
    """A chat with a character, a user turn and a character turn."""
    char = Character(id=str(uuid.uuid4()), name="Aria", description="A courier")
    session.add(char)
    session.commit()

    chat = Chat(
        id=str(uuid.uuid4()),
        name="Scene",
        character_id=char.id,
        persona_name="Player",
        director_enabled=True,
        allow_narration=True,
        allow_image_generation=True,
        **overrides,
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
    session.add(
        Message(
            id=str(uuid.uuid4()),
            chat_id=chat.id,
            role=MessageRole.CHAR,
            kind=MessageKind.CHAR,
            content="North, before the bridge burns.",
        )
    )
    session.commit()
    session.refresh(chat)
    return chat, char


def _seed_secondary(session: Session) -> Character:
    secondary = Character(
        id=str(uuid.uuid4()), name="Borin", description="A smuggler at the gate"
    )
    session.add(secondary)
    session.commit()
    session.refresh(secondary)
    return secondary


def _seed_agent(session: Session, slug: str, variant_slug: str, template: str):
    """An agent with one variant, the way the Studio creates them."""
    profile = AgentProfile(
        id=str(uuid.uuid4()),
        slug=slug,
        name=slug,
        agent_type="generation",
        description=f"Plays the {slug}",
        system_prompt_template=f"You are the base {slug}.",
        model_target="rp",
        is_builtin=False,
        enabled=True,
    )
    session.add(profile)
    session.commit()

    variant = AgentPromptVariant(
        id=str(uuid.uuid4()),
        agent_id=profile.id,
        slug=variant_slug,
        name=variant_slug,
        description="A variant",
        system_prompt_template=template,
        is_active=False,
        temperature=0.42,
    )
    session.add(variant)
    session.commit()
    session.refresh(variant)
    return profile, variant


def _chain_the_turn(monkeypatch, *, speaker: str, variant: str | None = None):
    """Make Laya continue the chain towards `speaker`."""
    chain = _audit_decision(
        workflow_stage="chaining",
        next_speaker=speaker,
        continue_chain_probability=0.95,
    )
    triage = _audit_decision(
        workflow_stage="triage",
        next_speaker=speaker,
        selected_variant=variant,
    )
    monkeypatch.setattr(
        "services.decision_service.DecisionService.evaluate_turn_chaining",
        AsyncMock(return_value=chain),
    )
    monkeypatch.setattr(
        "services.decision_service.DecisionService.evaluate_pre_generation_triage",
        AsyncMock(return_value=triage),
    )


class TestTheSecondaryCharacterBranchCarriesTheVariant:
    async def test_the_selected_variant_reaches_the_prompt(
        self, session, no_enqueue, monkeypatch
    ):
        from services.pipeline_stages import chain_stage

        secondary = _seed_secondary(session)
        _seed_agent(session, "secondary_character", "sidelong", "SIDE VARIANT for {{char}}")
        chat, char = _seed_chat(session, additional_character_ids=[secondary.id])
        _chain_the_turn(monkeypatch, speaker="secondary_character", variant="sidelong")

        await chain_stage(
            {
                "session": session,
                "job_service": JobService(session),
                "chat_id": chat.id,
                "character_id": char.id,
                "last_speaker": "character",
                "current_turns": 1,
                "max_turns": 4,
                "autonomy_level": "balanced",
            }
        )

        jobs = session.exec(select(Job).where(Job.task_type == "llm")).all()
        assert len(jobs) == 1, "the chain did not enqueue the secondary's turn"
        assert "SIDE VARIANT" in json.dumps(jobs[0].workflow), (
            "the variant never reached the prompt"
        )

    async def test_the_selected_variant_reaches_the_metadata(
        self, session, no_enqueue, monkeypatch
    ):
        from services.pipeline_stages import chain_stage

        secondary = _seed_secondary(session)
        _seed_agent(session, "secondary_character", "sidelong", "SIDE VARIANT for {{char}}")
        chat, char = _seed_chat(session, additional_character_ids=[secondary.id])
        _chain_the_turn(monkeypatch, speaker="secondary_character", variant="sidelong")

        await chain_stage(
            {
                "session": session,
                "job_service": JobService(session),
                "chat_id": chat.id,
                "character_id": char.id,
                "last_speaker": "character",
                "current_turns": 1,
                "max_turns": 4,
                "autonomy_level": "balanced",
            }
        )

        jobs = session.exec(select(Job).where(Job.task_type == "llm")).all()
        assert jobs[0].metadata_["selected_variant"] == "sidelong"

    async def test_the_agents_sampler_overrides_reach_the_workflow(
        self, session, no_enqueue, monkeypatch
    ):
        """The variant's temperature, the way the `character` branch does it."""
        from services.pipeline_stages import chain_stage

        secondary = _seed_secondary(session)
        _seed_agent(session, "secondary_character", "sidelong", "SIDE VARIANT for {{char}}")
        chat, char = _seed_chat(session, additional_character_ids=[secondary.id])
        _chain_the_turn(monkeypatch, speaker="secondary_character", variant="sidelong")

        await chain_stage(
            {
                "session": session,
                "job_service": JobService(session),
                "chat_id": chat.id,
                "character_id": char.id,
                "last_speaker": "character",
                "current_turns": 1,
                "max_turns": 4,
                "autonomy_level": "balanced",
            }
        )

        jobs = session.exec(select(Job).where(Job.task_type == "llm")).all()
        assert jobs[0].workflow["temperature"] == pytest.approx(0.42)

    async def test_the_character_branch_still_carries_the_variant(
        self, session, no_enqueue, monkeypatch
    ):
        """The branch that already worked must keep working."""
        from services.pipeline_stages import chain_stage

        _seed_agent(session, "character", "sharper", "CHAR VARIANT for {{char}}")
        chat, char = _seed_chat(session)
        _chain_the_turn(monkeypatch, speaker="character", variant="sharper")

        await chain_stage(
            {
                "session": session,
                "job_service": JobService(session),
                "chat_id": chat.id,
                "character_id": char.id,
                "last_speaker": "character",
                "current_turns": 1,
                "max_turns": 4,
                "autonomy_level": "balanced",
            }
        )

        jobs = session.exec(select(Job).where(Job.task_type == "llm")).all()
        assert "CHAR VARIANT" in json.dumps(jobs[0].workflow)
        assert jobs[0].metadata_["selected_variant"] == "sharper"


class TestOneFailingStageDoesNotCancelTheOthers:
    async def test_a_failing_audit_leaves_the_rest_of_the_turn_alone(
        self, session, no_enqueue, monkeypatch
    ):
        """The whole point of the fix.

        The audit is the FIRST stage of the walk, so before the fix a failure
        there meant the illustration, the Statekeeper, the memory extraction
        and the autonomous chain all never ran — for a turn that had already
        been paid for and saved.
        """
        from services import job_processing, pipeline_stages

        chat, char = _seed_chat(session)

        async def _boom(ctx):
            raise RuntimeError("the audit exploded")

        monkeypatch.setattr("services.pipeline_stages.audit_stage", _boom)

        # Record the stages the walk reaches AFTER the failing one.
        visited: list[str] = []
        for name in ("illustrate_stage", "update_stage", "chain_stage"):
            original = getattr(pipeline_stages, name)

            def _make(original=original, name=name):
                async def _inner(ctx):
                    visited.append(name)
                    return await original(ctx)

                return _inner

            monkeypatch.setattr(f"services.pipeline_stages.{name}", _make())

        _chain_the_turn(monkeypatch, speaker="character")

        memory_calls: list[dict] = []

        async def _record_memory(**kwargs):
            memory_calls.append(kwargs)
            return "memory-job"

        monkeypatch.setattr(
            "services.memory_extraction.enqueue_memory_extraction", _record_memory
        )
        monkeypatch.setattr(
            "services.job_processing.finalize_persisted_job_outputs",
            AsyncMock(return_value=None),
        )

        job_service = JobService(session)
        job = await job_service.create_job(
            task_type="llm",
            workflow={"messages": [], "type": "chat_reply"},
            metadata={
                "chat_id": chat.id,
                "character_id": char.id,
                "type": "chat_reply",
                "source": "chat_reply",
                "workspace": "chat",
            },
        )

        await job_processing._finalize_llm_job(
            job=job,
            job_id=job.id,
            job_service=job_service,
            load_balancer=None,
            provider_id="test-provider",
            final_result={
                "status": "success",
                "outputs": [{"role": "assistant", "content": "North, then."}],
            },
            outputs=[{"role": "assistant", "content": "North, then."}],
        )

        assert visited == ["illustrate_stage", "update_stage", "chain_stage"], (
            f"the walk stopped at the failing stage, reached {visited!r}"
        )
        assert memory_calls, "the memory extraction was cancelled by the audit failure"

    async def test_the_chain_still_runs_after_a_failing_audit(
        self, session, no_enqueue, monkeypatch
    ):
        from services import job_processing

        chat, char = _seed_chat(session)

        async def _boom(ctx):
            raise RuntimeError("the audit exploded")

        monkeypatch.setattr("services.pipeline_stages.audit_stage", _boom)
        _chain_the_turn(monkeypatch, speaker="character")
        monkeypatch.setattr(
            "services.job_processing.finalize_persisted_job_outputs",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "services.memory_extraction.enqueue_memory_extraction",
            AsyncMock(return_value="memory-job"),
        )

        job_service = JobService(session)
        job = await job_service.create_job(
            task_type="llm",
            workflow={"messages": [], "type": "chat_reply"},
            metadata={
                "chat_id": chat.id,
                "character_id": char.id,
                "type": "chat_reply",
                "source": "chat_reply",
                "workspace": "chat",
            },
        )

        await job_processing._finalize_llm_job(
            job=job,
            job_id=job.id,
            job_service=job_service,
            load_balancer=None,
            provider_id="test-provider",
            final_result={
                "status": "success",
                "outputs": [{"role": "assistant", "content": "North, then."}],
            },
            outputs=[{"role": "assistant", "content": "North, then."}],
        )

        jobs = session.exec(select(Job).where(Job.task_type == "llm")).all()
        followups = [j for j in jobs if j.id != job.id]
        assert followups, "the autonomous chain was cancelled by the audit failure"
        assert followups[0].metadata_["autonomous_turn_count"] == 2

    async def test_the_failing_stage_is_named_in_the_log(
        self, session, no_enqueue, monkeypatch
    ):
        """A log line that names no stage cannot be acted on."""
        from services import job_processing

        recorder = _RecordingLogger()
        monkeypatch.setattr("services.job_processing.logger", recorder)

        chat, char = _seed_chat(session)

        async def _boom(ctx):
            raise RuntimeError("the audit exploded")

        monkeypatch.setattr("services.pipeline_stages.audit_stage", _boom)
        _chain_the_turn(monkeypatch, speaker="character")
        monkeypatch.setattr(
            "services.job_processing.finalize_persisted_job_outputs",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "services.memory_extraction.enqueue_memory_extraction",
            AsyncMock(return_value="memory-job"),
        )

        job_service = JobService(session)
        job = await job_service.create_job(
            task_type="llm",
            workflow={"messages": [], "type": "chat_reply"},
            metadata={
                "chat_id": chat.id,
                "character_id": char.id,
                "type": "chat_reply",
                "source": "chat_reply",
                "workspace": "chat",
            },
        )

        await job_processing._finalize_llm_job(
            job=job,
            job_id=job.id,
            job_service=job_service,
            load_balancer=None,
            provider_id="test-provider",
            final_result={
                "status": "success",
                "outputs": [{"role": "assistant", "content": "North, then."}],
            },
            outputs=[{"role": "assistant", "content": "North, then."}],
        )

        stage_failures = [
            kwargs
            for _level, event, kwargs in recorder.calls
            if event == "post_turn_pipeline_stage_failed"
        ]
        assert stage_failures, "the failing stage was not logged at all"
        assert stage_failures[0]["stage"] == "audit"


class TestTheDurableMemoryGateIsStillHonoured:
    """The isolation must not turn the gate off.

    An audit that FAILED is not an audit that said "no durable memory": the
    first is a missing answer and the second is a decision. The fallback for
    a missing answer must not swallow the decision.
    """

    async def _run_turn(self, session, monkeypatch, *, audit):
        from services import job_processing

        chat, char = _seed_chat(session)

        async def _audit_stage(ctx):
            ctx["audit_decision"] = audit
            return ctx["audit_decision"]

        monkeypatch.setattr("services.pipeline_stages.audit_stage", _audit_stage)
        _chain_the_turn(monkeypatch, speaker="character")
        monkeypatch.setattr(
            "services.job_processing.finalize_persisted_job_outputs",
            AsyncMock(return_value=None),
        )

        memory_calls: list[dict] = []

        async def _record_memory(**kwargs):
            memory_calls.append(kwargs)
            return "memory-job"

        monkeypatch.setattr(
            "services.memory_extraction.enqueue_memory_extraction", _record_memory
        )

        job_service = JobService(session)
        job = await job_service.create_job(
            task_type="llm",
            workflow={"messages": [], "type": "chat_reply"},
            metadata={
                "chat_id": chat.id,
                "character_id": char.id,
                "type": "chat_reply",
                "source": "chat_reply",
                "workspace": "chat",
            },
        )

        await job_processing._finalize_llm_job(
            job=job,
            job_id=job.id,
            job_service=job_service,
            load_balancer=None,
            provider_id="test-provider",
            final_result={
                "status": "success",
                "outputs": [{"role": "assistant", "content": "North, then."}],
            },
            outputs=[{"role": "assistant", "content": "North, then."}],
        )
        return memory_calls

    async def test_a_gate_that_did_not_fire_still_blocks_the_extraction(
        self, session, no_enqueue, monkeypatch
    ):
        memory_calls = await self._run_turn(
            session,
            monkeypatch,
            audit=_audit_decision(updater_gates={}),
        )
        assert memory_calls == [], "the durable-memory gate was ignored"

    async def test_a_fired_gate_still_triggers_the_extraction(
        self, session, no_enqueue, monkeypatch
    ):
        memory_calls = await self._run_turn(
            session,
            monkeypatch,
            audit=_audit_decision(updater_gates={"gate_durable_memory": 0.9}),
        )
        assert memory_calls, "a fired durable-memory gate did not extract"
