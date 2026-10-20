"""The roleplay chat pipeline's execution paths had no tests at all.

Three defects shipped green because the code that raised them was never
exercised:

  - `services/updater_service.py` called `build_llm_workflow()` with
    `temperature=` and `max_output_tokens=`, which its closed keyword-only
    signature does not accept. The `TypeError` escaped the function (the
    `try` in it only wraps the enqueue, not the build) and landed in the
    post-turn hook in `services/job_processing.py`, which swallowed it at
    DEBUG level. The Statekeeper never ran — and because the same hook
    aborts at that point, neither did memory extraction nor turn chaining.
  - `services/job_processing.py` imported `render_agent_template` from
    `services.agent_variants`, which does not define it (it lives in
    `services.chat_utils`). The `ImportError` killed the autonomous
    multi-turn chain and the continuation path.
  - `services/decision_service.py`'s generative fallback read an event
    dialect (`event == "token"`, `status == "success"`) that no engine
    emits, so the Director's Tier 3 always returned `None` and the cascade
    silently degraded to the deterministic heuristic.

`apply_updater_result` — the *apply* half of the Statekeeper — was covered.
The *enqueue* half, and the chain, and the fallback tier, were not. These
tests are the safety net for the pipeline: they exercise the stages, not
just the functions that store their results.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, select

from core.entities import (
    AgentProfile,
    Character,
    Chat,
    Job,
    Message,
    MessageKind,
    MessageRole,
    Provider,
)
from services.decision_schema import DirectorDecisionResult
from services.job_service import JobService


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


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


def _audit_decision(**overrides) -> DirectorDecisionResult:
    """An audit that says the reply is complete and nothing needs updating."""
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


# --------------------------------------------------------------------------
# Stage 4: the Statekeeper's enqueue half
# --------------------------------------------------------------------------


class TestStateUpdaterEnqueue:
    async def test_a_fired_gate_enqueues_a_state_updater_job(self, session, no_enqueue):
        """The half that was broken.

        `enqueue_state_updater_if_needed` built its workflow with
        `temperature=` and `max_output_tokens=`, which `build_llm_workflow`
        does not accept. The TypeError escaped the function before its
        `try` block and was swallowed by the post-turn hook, so the
        Statekeeper silently never ran and the chat's `state_snapshot` never
        changed.
        """
        from services.updater_service import enqueue_state_updater_if_needed

        chat, char = _seed_chat(session)

        decision = _audit_decision(
            should_run_updater=True,
            triggered_gates=["gate_character_mood"],
            updater_gates={"gate_character_mood": 0.9},
        )

        job_id = await enqueue_state_updater_if_needed(
            session,
            chat_id=chat.id,
            character_id=char.id,
            decision=decision,
            job_service=JobService(session),
        )

        assert job_id is not None, "the Statekeeper never enqueued a job"

        job = session.get(Job, job_id)
        assert job is not None
        assert job.task_type == "llm"
        assert job.metadata_["type"] == "state_updater"
        assert job.metadata_["source"] == "state_updater"
        assert job.metadata_["background"] is True
        assert job.metadata_["triggered_gates"] == ["gate_character_mood"]

        # The sampling has to travel in the workflow, not as loose kwargs.
        assert job.workflow["temperature"] == pytest.approx(0.2)
        assert job.workflow["max_output_tokens"] == 600

        no_enqueue.assert_awaited()

    async def test_the_gated_schema_excludes_the_gates_that_did_not_fire(self, session, no_enqueue):
        """A gate that did not fire may not put its field in the schema.

        The Updater is told which fields it may write by the schema itself,
        and the result is filtered again on the way in. A field from an
        unfired gate must not even be mentioned.
        """
        from services.updater_service import enqueue_state_updater_if_needed

        chat, char = _seed_chat(session)

        decision = _audit_decision(
            should_run_updater=True,
            triggered_gates=["gate_character_mood"],
            updater_gates={"gate_character_mood": 0.9},
        )

        job_id = await enqueue_state_updater_if_needed(
            session,
            chat_id=chat.id,
            character_id=char.id,
            decision=decision,
            job_service=JobService(session),
        )
        job = session.get(Job, job_id)
        prompt = job.workflow["messages"][1]["content"]

        assert "character_mood" in prompt
        assert "inventory_add" not in prompt, "an unfired gate's field reached the schema"
        assert "new_lore" not in prompt

    async def test_no_gates_means_no_job(self, session, no_enqueue):
        from services.updater_service import enqueue_state_updater_if_needed

        chat, char = _seed_chat(session)

        job_id = await enqueue_state_updater_if_needed(
            session,
            chat_id=chat.id,
            character_id=char.id,
            decision=_audit_decision(),
            job_service=JobService(session),
        )

        assert job_id is None
        no_enqueue.assert_not_awaited()

    async def test_the_extraction_sampling_wins_over_the_agent_profile(self, session, no_enqueue):
        """The Statekeeper's temperature is not the agent profile's.

        The Updater now resolves its `updater` agent profile and its active
        variant, so the agent's `sampler_overrides()` reach the workflow. A
        variant written for prose would otherwise run the JSON extractor at a
        creative temperature, and the extractor produces prose where the
        schema wants JSON. The extraction settings pin temperature and token
        ceiling; the agent's overrides fill in the rest.
        """
        from services.updater_service import enqueue_state_updater_if_needed

        chat, char = _seed_chat(session)

        profile = AgentProfile(
            id=str(uuid.uuid4()),
            slug="updater",
            name="Statekeeper",
            agent_type="state_update",
            description="Extracts state deltas",
            system_prompt_template="You are the Statekeeper.",
            model_target="util",
            is_builtin=False,
            enabled=True,
            temperature=0.9,
            top_p=0.95,
        )
        session.add(profile)
        session.commit()

        decision = _audit_decision(
            should_run_updater=True,
            triggered_gates=["gate_character_mood"],
            updater_gates={"gate_character_mood": 0.9},
        )

        job_id = await enqueue_state_updater_if_needed(
            session,
            chat_id=chat.id,
            character_id=char.id,
            decision=decision,
            job_service=JobService(session),
        )
        job = session.get(Job, job_id)

        assert job.workflow["temperature"] == pytest.approx(0.2), (
            "the agent profile's temperature overrode the JSON extractor's"
        )
        assert job.workflow["max_output_tokens"] == 600
        # The agent's own sampling still applies where the extractor does not
        # pin a value.
        assert job.workflow["top_p"] == pytest.approx(0.95)
        # And the agent's prompt is used, with the JSON-only requirement
        # appended so a prompt rewrite cannot break the contract.
        system_prompt = job.workflow["messages"][0]["content"]
        assert "Statekeeper" in system_prompt
        assert "JSON" in system_prompt


# --------------------------------------------------------------------------
# Stage 6: the autonomous multi-turn chain
# --------------------------------------------------------------------------


class TestAutonomousChain:
    async def test_a_continue_decision_enqueues_the_next_turn(self, session, no_enqueue, monkeypatch):
        """The chain stage raised ImportError on its first statement.

        `services/job_processing.py` imported `render_agent_template` from
        `services.agent_variants`, which does not define it. The function
        lives in `services.chat_utils`. The ImportError killed every
        autonomous chained turn, so the "up to 4 turns" budget was never
        spent.

        `current_turns` is the turn that JUST RAN; the chain creates the one
        after it. So a chain that runs after turn 1 creates turn 2.
        """
        from services.pipeline_stages import chain_stage

        chat, char = _seed_chat(session)

        chain = _audit_decision(
            workflow_stage="chaining",
            next_speaker="character",
            continue_chain_probability=0.95,
        )
        triage = _audit_decision(workflow_stage="triage", next_speaker="character")

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_turn_chaining",
            AsyncMock(return_value=chain),
        )
        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_pre_generation_triage",
            AsyncMock(return_value=triage),
        )

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

        no_enqueue.assert_awaited()
        jobs = session.exec(
            select(Job).where(Job.task_type == "llm")
        ).all()
        assert len(jobs) == 1, "the chain did not enqueue a follow-up turn"
        assert jobs[0].metadata_["autonomous_turn_count"] == 2
        assert jobs[0].metadata_["max_autonomous_turns"] == 4

    async def test_the_deferred_chain_payload_carries_the_turn_that_ran(
        self, session, no_enqueue, monkeypatch
    ):
        """The two chain paths must agree on what the turn number means.

        The payload the Statekeeper defers with used to carry
        `current_turns + 1` — the turn to CREATE — while the walk handed the
        chain the turn that RAN. The chain then wrote
        `autonomous_turn_count` unchanged, so on the direct path the counter
        never advanced.

        The payload now carries the turn that ran, and the chain adds one.
        """
        from services.pipeline_stages import update_stage

        chat, char = _seed_chat(session)
        ctx = {
            "session": session,
            "job_service": JobService(session),
            "chat": chat,
            "character": char,
            "chat_id": chat.id,
            "character_id": char.id,
            "audit_decision": _audit_decision(should_run_updater=False),
            "current_turns": 2,
            "last_speaker": "character",
            "job_meta": {},
        }
        await update_stage(ctx)

        payload = ctx.get("chain_payload")
        assert payload is not None, "the chain payload was not built"
        assert payload["turn"] == 2, (
            f"the payload must carry the turn that ran, got {payload['turn']!r}"
        )

    async def test_a_stop_decision_enqueues_nothing(self, session, no_enqueue, monkeypatch):
        from services.pipeline_stages import chain_stage

        chat, char = _seed_chat(session)

        chain = _audit_decision(
            workflow_stage="chaining",
            next_speaker="character",
            continue_chain_probability=0.05,
        )

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_turn_chaining",
            AsyncMock(return_value=chain),
        )

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

        no_enqueue.assert_not_awaited()

    async def test_yielding_to_the_user_enqueues_nothing(self, session, no_enqueue, monkeypatch):
        from services.pipeline_stages import chain_stage

        chat, char = _seed_chat(session)

        chain = _audit_decision(
            workflow_stage="chaining",
            next_speaker="user",
            continue_chain_probability=0.99,
        )

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_turn_chaining",
            AsyncMock(return_value=chain),
        )

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

        no_enqueue.assert_not_awaited()


    async def test_the_turn_budget_stops_the_chain(self, session, no_enqueue, monkeypatch):
        """The "up to 4 turns" budget has to stop the chain, not just be quoted.

        The gate lived in `update_stage` only, and `update_stage` only runs
        the chain when it DEFERS it - that is, when the Statekeeper ran. So
        the budget was enforced on the deferred path and not on the direct
        one, and the direct path is the common one: the audit decides the
        updater should not run, so `updater_job_id` is None, so the chain
        stage runs in the walk itself.

        On that path the chain had no turn limit at all, and the follow-up
        job it created carried `autonomous_turn_count` UNCHANGED - so the
        counter never advanced and the next turn read the same number.
        The chain could run for as long as the Director kept asking for
        another turn.
        """
        from services.pipeline_stages import chain_stage

        chat, char = _seed_chat(session)

        chain = _audit_decision(
            workflow_stage="chaining",
            next_speaker="character",
            continue_chain_probability=0.99,
        )
        triage = _audit_decision(workflow_stage="triage", next_speaker="character")

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_turn_chaining",
            AsyncMock(return_value=chain),
        )
        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_pre_generation_triage",
            AsyncMock(return_value=triage),
        )

        await chain_stage(
            {
                "session": session,
                "job_service": JobService(session),
                "chat_id": chat.id,
                "character_id": char.id,
                "last_speaker": "character",
                "current_turns": 4,
                "max_turns": 4,
                "autonomy_level": "balanced",
            }
        )

        no_enqueue.assert_not_awaited()
        jobs = session.exec(
            select(Job).where(Job.task_type == "llm")
        ).all()
        assert jobs == [], "the chain chained past its turn budget"

    async def test_strict_autonomy_never_chains(self, session, no_enqueue, monkeypatch):
        """Strict autonomy means the Director never takes another turn.

        The check was in `update_stage`, for the same reason as the turn
        budget: it only ran on the deferred path.
        """
        from services.pipeline_stages import chain_stage

        chat, char = _seed_chat(session)

        chain = _audit_decision(
            workflow_stage="chaining",
            next_speaker="character",
            continue_chain_probability=0.99,
        )
        triage = _audit_decision(workflow_stage="triage", next_speaker="character")

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_turn_chaining",
            AsyncMock(return_value=chain),
        )
        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_pre_generation_triage",
            AsyncMock(return_value=triage),
        )

        await chain_stage(
            {
                "session": session,
                "job_service": JobService(session),
                "chat_id": chat.id,
                "character_id": char.id,
                "last_speaker": "character",
                "current_turns": 1,
                "max_turns": 4,
                "autonomy_level": "strict",
            }
        )

        no_enqueue.assert_not_awaited()
        jobs = session.exec(
            select(Job).where(Job.task_type == "llm")
        ).all()
        assert jobs == [], "strict autonomy chained anyway"

    async def test_the_turn_counter_advances(self, session, no_enqueue, monkeypatch):
        """The follow-up turn has to know it is the next turn.

        The job the chain creates carried `autonomous_turn_count` unchanged,
        so the turn that read it saw the same number forever and the budget
        could never run out - the counter was the thing that was supposed
        to stop it.
        """
        from services.pipeline_stages import chain_stage

        chat, char = _seed_chat(session)

        chain = _audit_decision(
            workflow_stage="chaining",
            next_speaker="character",
            continue_chain_probability=0.99,
        )
        triage = _audit_decision(workflow_stage="triage", next_speaker="character")

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_turn_chaining",
            AsyncMock(return_value=chain),
        )
        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_pre_generation_triage",
            AsyncMock(return_value=triage),
        )

        await chain_stage(
            {
                "session": session,
                "job_service": JobService(session),
                "chat_id": chat.id,
                "character_id": char.id,
                "last_speaker": "character",
                "current_turns": 2,
                "max_turns": 4,
                "autonomy_level": "balanced",
            }
        )

        jobs = session.exec(
            select(Job).where(Job.task_type == "llm")
        ).all()
        assert len(jobs) == 1
        assert jobs[0].metadata_["autonomous_turn_count"] == 3, (
            "the follow-up turn does not know it is the next turn"
        )


# --------------------------------------------------------------------------
# The continuation path
# --------------------------------------------------------------------------


class TestContinuation:
    async def test_an_incomplete_reply_is_continued(self, session, no_enqueue, monkeypatch):
        """A reply cut off mid-thought must produce a continuation job.

        The continuation branch imported `render_agent_template` from the
        wrong module, so the branch raised ImportError and the reply simply
        stopped where it was cut off. The four-repeat threshold was
        evaluated and then thrown away.
        """
        from services import job_processing

        chat, char = _seed_chat(session)

        audit = _audit_decision(is_complete=False)
        triage = _audit_decision(workflow_stage="triage", next_speaker="character")

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_post_generation_audit",
            AsyncMock(return_value=audit),
        )
        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_pre_generation_triage",
            AsyncMock(return_value=triage),
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
            final_result={"status": "success", "outputs": [{"role": "assistant", "content": "I was about to say—"}]},
            outputs=[{"role": "assistant", "content": "I was about to say—"}],
        )

        no_enqueue.assert_awaited()
        jobs = session.exec(select(Job).where(Job.task_type == "llm")).all()
        continuations = [j for j in jobs if j.metadata_.get("source") == "continuation"]
        assert len(continuations) == 1, "the truncated reply was never continued"
        assert continuations[0].metadata_["continuation_count"] == 1
        assert continuations[0].metadata_["continuation_of_job_id"] == job.id

    async def test_a_complete_reply_is_not_continued(self, session, no_enqueue, monkeypatch):
        from services import job_processing

        chat, char = _seed_chat(session)

        monkeypatch.setattr(
            "services.decision_service.DecisionService.evaluate_post_generation_audit",
            AsyncMock(return_value=_audit_decision(is_complete=True)),
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
            final_result={"status": "success", "outputs": [{"role": "assistant", "content": "Done."}]},
            outputs=[{"role": "assistant", "content": "Done."}],
        )

        jobs = session.exec(select(Job).where(Job.task_type == "llm")).all()
        continuations = [j for j in jobs if j.metadata_.get("source") == "continuation"]
        assert not continuations

    async def test_the_budget_counts_attempts_not_continuations(self, session, no_enqueue, monkeypatch):
        """Four attempts, not one attempt plus four continuations.

        The check used to be `continuation_count < 4`, which is the original
        plus four continuations — five generations — while the manifest said
        "max_continuations: 4" and the UI said "4 repeats". The budget now
        counts attempts, and the name says so.
        """
        from core.pipeline_limits import MAX_CONTINUATION_ATTEMPTS
        from services import pipeline_stages

        chat, char = _seed_chat(session)

        # The third attempt (continuation_count == 2) may still continue.
        assert (2 + 1) < MAX_CONTINUATION_ATTEMPTS
        # The fourth (continuation_count == 3) may not.
        assert not ((3 + 1) < MAX_CONTINUATION_ATTEMPTS)

        # And the stage reads the same number the manifest publishes.
        from services.pipeline_runner import limit

        assert limit("audit", "max_continuation_attempts") == MAX_CONTINUATION_ATTEMPTS
        assert pipeline_stages._max_continuation_attempts() == MAX_CONTINUATION_ATTEMPTS


# --------------------------------------------------------------------------
# The Director's Tier 3
# --------------------------------------------------------------------------


class _FakeEngine:
    """An engine that emits the canonical TaskEvent dialect."""

    def __init__(self, events):
        self._events = events
        self.provider_id = "fake-engine"

    async def inference(self, workflow, timeout=None, **kwargs):
        for event in self._events:
            yield event


class TestDirectorGenerativeFallback:
    async def test_the_canonical_event_dialect_is_read(self, session, monkeypatch):
        """Tier 3 used to read an event dialect nothing emits.

        The loop looked for `event == "token"` and `status == "success"`.
        The engines emit `delta` and `completed`, so `full_text` stayed
        empty, Tier 3 returned None, and the cascade fell through to the
        deterministic heuristic on every single decision.
        """
        from services.decision_service import DecisionService

        provider = Provider(
            id="llm-provider",
            type="openai_compat",
            worker_type="llm",
            enabled=True,
            priority=1,
            config={},
        )
        session.add(provider)
        session.commit()

        payload = (
            '{"next_speaker": "narrator", "continue_chain": 0.4, '
            '"pacing_directive": "sensory_detail", "scene_tension": 3.5, '
            '"pacing_speed": 1.5, "emotional_tone": "mysterious_tense", '
            '"trigger_image": 0.1}'
        )

        engine = _FakeEngine(
            [
                {"event": "started", "job_id": "j1"},
                {"event": "delta", "job_id": "j1", "text": payload},
                {
                    "event": "completed",
                    "job_id": "j1",
                    "outputs": [{"role": "assistant", "content": payload}],
                },
            ]
        )

        monkeypatch.setattr(
            "services.engines.engine_factory.get_engine", lambda provider_id, prov: engine
        )
        monkeypatch.setattr(
            "services.llm_config.model_for_kind", lambda kind, pinned, sess: "test-model"
        )

        result = await DecisionService(session)._try_generative_util_fallback(
            context_text="A courier on a burning bridge.",
            has_secondary_character=False,
            allow_image_generation=True,
            allow_narration=True,
        )

        assert result is not None, "Tier 3 returned nothing on a canonical event stream"
        assert result.engine_used.startswith("util_llm_json:")
        assert result.next_speaker == "narrator"
        assert result.pacing_directive == "sensory_detail"

    async def test_an_unreadable_stream_still_falls_through(self, session, monkeypatch):
        """A provider that says nothing must not break the cascade."""
        from services.decision_service import DecisionService

        provider = Provider(
            id="llm-provider",
            type="openai_compat",
            worker_type="llm",
            enabled=True,
            priority=1,
            config={},
        )
        session.add(provider)
        session.commit()

        engine = _FakeEngine([{"event": "started", "job_id": "j1"}])
        monkeypatch.setattr(
            "services.engines.engine_factory.get_engine", lambda provider_id, prov: engine
        )
        monkeypatch.setattr(
            "services.llm_config.model_for_kind", lambda kind, pinned, sess: "test-model"
        )

        result = await DecisionService(session)._try_generative_util_fallback(
            context_text="A courier on a burning bridge.",
            has_secondary_character=False,
            allow_image_generation=True,
            allow_narration=True,
        )

        assert result is None


# --------------------------------------------------------------------------
# The manifest is authoritative
# --------------------------------------------------------------------------


class TestPipelineManifest:
    def test_every_stage_with_an_executor_resolves_to_a_coroutine(self):
        """A manifest that names a function nobody can call is a lie.

        The manifest used to be a description of a pipeline that lived
        somewhere else, so nothing checked that the two agreed. Now each
        stage names its executor and the runner resolves it by dotted path at
        call time — a typo in that path is a runtime error, so it has to be
        caught here.
        """
        from services.chat_pipeline import PIPELINE_STAGES
        from services.pipeline_runner import resolve_executor

        for stage in PIPELINE_STAGES:
            if not stage.executor:
                # `act` IS the generation — there is no function to call.
                assert stage.runs_as == "job"
                continue
            executor = resolve_executor(stage.id)
            assert executor is not None, f"stage {stage.id!r} names an executor it cannot resolve"
            assert asyncio.iscoroutinefunction(executor), (
                f"stage {stage.id!r} names a non-async executor"
            )

    def test_the_manifest_quotes_the_limits_the_code_uses(self):
        """`GET /llm/pipeline` must not report a number the pipeline ignores.

        The limits used to live in four places — the manifest, the entity
        column default, the executor's literals, and the decision schema's
        constants. They are now in `core/pipeline_limits`, and everything
        else imports them.
        """
        from core import pipeline_limits
        from services.chat_pipeline import get_pipeline_manifest

        limits = get_pipeline_manifest()["limits"]
        assert limits["max_autonomous_turns"] == pipeline_limits.MAX_AUTONOMOUS_TURNS
        assert limits["max_continuation_attempts"] == pipeline_limits.MAX_CONTINUATION_ATTEMPTS
        assert limits["max_agentic_images"] == pipeline_limits.MAX_AGENTIC_IMAGES
        assert limits["gate_threshold"] == pipeline_limits.UPDATER_GATE_THRESHOLD
        assert limits["image_threshold"] == pipeline_limits.IMAGE_TRIGGER_THRESHOLD

    def test_the_entity_default_comes_from_the_same_place(self):
        from core import pipeline_limits
        from core.entities import Chat

        assert Chat.model_fields["max_autonomous_turns"].default == pipeline_limits.MAX_AUTONOMOUS_TURNS

    def test_the_stage_order_is_the_order_the_code_runs(self):
        """The audit declares what follows it, and that is what runs.

        A truncated reply is continued and the turn ends there, so the
        continuation is a branch out of the audit rather than a sibling of
        it — which is why the audit's successors are illustrate, update and
        chain, in that order, and not the audit itself.
        """
        from services.pipeline_runner import stage

        assert stage("audit").next_stages == ("illustrate", "update", "chain", "user")
        assert stage("triage").next_stages == ("act",)
        assert stage("update").next_stages == ("chain", "user")

    def test_the_chain_defers_itself_when_the_statekeeper_ran(self):
        """The chain reads the state the Statekeeper just wrote.

        When the Statekeeper ran, the chain is deferred to the updater job's
        completion hook. Running it inline would read the pre-update
        snapshot, which is the stale read the deferral exists to prevent.
        """
        from services.pipeline_stages import chain_stage

        # `updater_job_id` set -> the chain declines.
        assert asyncio.run(
            chain_stage({"updater_job_id": "some-job-id"})
        ) is None


# --------------------------------------------------------------------------
# The agents introspection endpoint
# --------------------------------------------------------------------------


class TestAgentsWithVariants:
    def test_it_answers_when_agents_exist(self, session, client):
        """This route read `profile.avatar_path`, a column `AgentProfile` did
        not have, so it returned HTTP 500 for any deployment that had agents
        in the table. The existing test could not see it because it asserted
        `if body:` and the test database has no seeded agents, so the loop
        that raised never ran.

        The agent is seeded here on purpose.
        """
        session.add(
            AgentProfile(
                id=str(uuid.uuid4()),
                slug="scout",
                name="Field Scout",
                agent_type="generation",
                description="Ranges ahead of the party",
                system_prompt_template="You are a scout.",
                model_target="rp",
                is_builtin=False,
                enabled=True,
            )
        )
        session.commit()

        resp = client.get("/api/v2/llm/agents/with-variants")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body, "the seeded agent did not come back"
        agent = body[0]
        assert agent["slug"] == "scout"
        assert "variants" in agent
        assert "active_variant_slug" in agent
        assert "avatar_path" in agent, "the response builder still reads a missing column"

    def test_an_agent_update_accepts_an_avatar_path(self, session, client):
        """`PUT /agents/{id}` with an avatar_path raised a ValueError before
        the commit, so the whole update was lost — including the sibling
        fields sent alongside it.
        """
        profile = AgentProfile(
            id=str(uuid.uuid4()),
            slug="scribe",
            name="Scribe",
            agent_type="generation",
            description="Records what happened",
            system_prompt_template="You are a scribe.",
            model_target="rp",
            is_builtin=False,
            enabled=True,
        )
        session.add(profile)
        session.commit()

        resp = client.put(
            f"/api/v2/agents/{profile.id}",
            json={"avatar_path": "/tmp/scribe.png", "description": "Records everything"},
        )
        assert resp.status_code == 200, resp.text

        session.expire_all()
        reloaded = session.get(AgentProfile, profile.id)
        assert reloaded.avatar_path == "/tmp/scribe.png"
        assert reloaded.description == "Records everything", "the sibling field was lost too"

    def test_an_agent_update_accepts_the_slug_the_studio_sends(self, session, client):
        """The Agent Studio's slug field is editable and it sends the slug.

        The update model never declared it, so the backend dropped it
        silently and the user's new slug vanished on reload. Declaring it is
        also what makes `extra="forbid"` safe here: with the field absent,
        forbidding extras would have turned the Studio's own save into a 422.
        """
        profile = AgentProfile(
            id=str(uuid.uuid4()),
            slug="scribe",
            name="Scribe",
            agent_type="generation",
            description="Records what happened",
            system_prompt_template="You are a scribe.",
            model_target="rp",
            is_builtin=False,
            enabled=True,
        )
        session.add(profile)
        session.commit()

        resp = client.put(
            f"/api/v2/agents/{profile.id}",
            json={"slug": "chronicler", "name": "Chronicler"},
        )
        assert resp.status_code == 200, resp.text

        session.expire_all()
        reloaded = session.get(AgentProfile, profile.id)
        assert reloaded.slug == "chronicler"
        assert reloaded.name == "Chronicler"

    def test_a_builtin_agent_slug_cannot_be_changed(self, session, client):
        """A built-in agent is looked up by its slug, so the slug is contract."""
        profile = AgentProfile(
            id=str(uuid.uuid4()),
            slug="character",
            name="Character",
            agent_type="generation",
            description="The default",
            system_prompt_template="You are the character.",
            model_target="rp",
            is_builtin=True,
            enabled=True,
        )
        session.add(profile)
        session.commit()

        resp = client.put(f"/api/v2/agents/{profile.id}", json={"slug": "someone_else"})
        assert resp.status_code == 400, resp.text

        session.expire_all()
        assert session.get(AgentProfile, profile.id).slug == "character"

    def test_an_unknown_field_is_rejected_rather_than_dropped(self, session, client):
        """A typo'd field is a 422, not a silent no-op."""
        profile = AgentProfile(
            id=str(uuid.uuid4()),
            slug="scribe",
            name="Scribe",
            agent_type="generation",
            description="Records what happened",
            system_prompt_template="You are a scribe.",
            model_target="rp",
            is_builtin=False,
            enabled=True,
        )
        session.add(profile)
        session.commit()

        resp = client.put(f"/api/v2/agents/{profile.id}", json={"descripton": "typo"})
        assert resp.status_code == 422, resp.text
