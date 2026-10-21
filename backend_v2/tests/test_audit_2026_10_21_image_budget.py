"""Regression tests for audit-2026-10-21 findings 2 and 3: the "Agentic
Image Budget" did not constrain the Illustrator, and the number that budget
was defined in three places.

Finding 2 was two independent defects in one condition:

  (a) the running total was read from `agentic_image_count`, a job-metadata
      key NOTHING writes, so the total was always 0 and the budget never
      tripped;
  (b) the cap was read as `getattr(chat, "max_agentic_images", 2) or 2`, and
      the `or 2` turned an explicit 0 — the slider's "0 disables autonomous
      illustration" — back into 2.

Finding 3 was the copy: `core/pipeline_limits.py` defines
`MAX_AGENTIC_IMAGES`, the manifest reads it, and the executor and the
orchestrator each kept their own literal.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from sqlmodel import Session

from core.entities import Character, Chat
from services.decision_schema import DirectorDecisionResult


def _seed_chat(session: Session, **overrides) -> Chat:
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
    session.refresh(chat)
    return chat


def _audit(**overrides) -> DirectorDecisionResult:
    payload = {
        "is_complete": True,
        "pacing_directive": "calm",
        "next_speaker": "character",
        "should_trigger_image": True,
        "updater_gates": {},
        "selected_variant": None,
    }
    payload.update(overrides)
    return DirectorDecisionResult(**payload)


def _ctx(session: Session, chat: Chat, *, job_meta: dict | None = None) -> dict:
    return {
        "session": session,
        "chat": chat,
        "job": type("Job", (), {"id": "job-1"})(),
        "job_meta": job_meta if job_meta is not None else {},
        "audit_decision": _audit(),
        "character_id": chat.character_id,
        "job_service": object(),
        "chat_id": chat.id,
    }


@pytest.fixture
def illustrator_stub(monkeypatch):
    """Replace the Illustrator dispatch with a recorder.

    The stage's job is the DECISION to spend an image, not the dispatch
    itself, and the dispatch enqueues a real job.
    """
    calls: list[dict] = []

    async def _fake_enqueue(session, **kwargs):
        calls.append(kwargs)
        return f"illustrator-job-{len(calls)}"

    monkeypatch.setattr(
        "services.illustrator_service.enqueue_scene_illustration_job", _fake_enqueue
    )
    return calls


class TestTheIllustrateBudget:
    async def test_zero_disables_autonomous_illustration(self, session, illustrator_stub):
        """`0` is "off", not "unset".

        The slider's own tooltip says 0 disables autonomous illustration, and
        the column is nullable, so 0 is a value the user can genuinely set.
        """
        from services.pipeline_stages import illustrate_stage

        chat = _seed_chat(session, max_agentic_images=0)

        result = await illustrate_stage(_ctx(session, chat))

        assert result is None
        assert illustrator_stub == [], "an image was spent with a budget of 0"

    async def test_a_budget_of_one_allows_exactly_one_image(self, session, illustrator_stub):
        from services.pipeline_stages import illustrate_stage

        chat = _seed_chat(session, max_agentic_images=1)
        ctx = _ctx(session, chat)

        first = await illustrate_stage(ctx)
        assert first is not None
        assert len(illustrator_stub) == 1

    async def test_the_second_illustration_in_one_exchange_is_blocked(self, session, illustrator_stub):
        """The budget has to count the images this exchange already spent.

        The running total used to be read from `agentic_image_count`, a key
        nothing writes, so it was always 0 and the second image was always
        allowed.
        """
        from services.pipeline_stages import illustrate_stage

        chat = _seed_chat(session, max_agentic_images=1)
        ctx = _ctx(session, chat)

        assert await illustrate_stage(ctx) is not None

        # The same exchange, the next turn: the total has moved.
        second = await illustrate_stage(ctx)
        assert second is None
        assert len(illustrator_stub) == 1, "the budget did not stop the second image"

    async def test_the_running_total_is_written_back_where_the_next_turn_reads_it(
        self, session, illustrator_stub
    ):
        from services.orchestrator_service import IMAGE_TOOL_NAME, tool_counter_key
        from services.pipeline_stages import illustrate_stage

        chat = _seed_chat(session, max_agentic_images=2)
        ctx = _ctx(session, chat)

        await illustrate_stage(ctx)

        counter_key = tool_counter_key(IMAGE_TOOL_NAME)
        assert ctx["job_meta"][counter_key] == 1
        assert ctx[counter_key] == 1

    async def test_the_counter_is_the_key_the_budget_table_declares(self, session, illustrator_stub):
        """Not a second spelling of the same counter."""
        from services.orchestrator_service import IMAGE_TOOL_NAME, TOOL_BUDGETS, tool_counter_key
        from services.pipeline_stages import illustrate_stage

        chat = _seed_chat(session, max_agentic_images=1)
        ctx = _ctx(session, chat, job_meta={"agentic_image_jobs": 1})

        # The counter the agentic tool loop spends is the one the Illustrator
        # must respect: a chat cannot pay for two images, one from each path.
        assert TOOL_BUDGETS[IMAGE_TOOL_NAME][0] == "agentic_image_jobs"
        assert tool_counter_key(IMAGE_TOOL_NAME) == "agentic_image_jobs"

        assert await illustrate_stage(ctx) is None
        assert illustrator_stub == []

    async def test_a_chat_without_a_budget_uses_the_default(self, session, illustrator_stub):
        from core.pipeline_limits import MAX_AGENTIC_IMAGES
        from services.pipeline_stages import illustrate_stage

        chat = _seed_chat(session, max_agentic_images=None)
        ctx = _ctx(session, chat, job_meta={"agentic_image_jobs": MAX_AGENTIC_IMAGES - 1})

        assert await illustrate_stage(ctx) is not None

    async def test_the_budget_is_not_consumed_when_the_dispatch_fails(self, session, monkeypatch):
        """A failed dispatch did not spend the image, so it must not count."""
        from services.pipeline_stages import illustrate_stage

        async def _boom(session, **kwargs):
            raise RuntimeError("illustrator exploded")

        monkeypatch.setattr(
            "services.illustrator_service.enqueue_scene_illustration_job", _boom
        )

        chat = _seed_chat(session, max_agentic_images=1)
        ctx = _ctx(session, chat)

        assert await illustrate_stage(ctx) is None
        assert "agentic_image_jobs" not in ctx["job_meta"]


class TestTheBudgetIsDefinedOnce:
    """Finding 3: three copies of `MAX_AGENTIC_IMAGES = 2`."""

    def test_the_executor_and_the_orchestrator_read_the_manifests_number(self):
        from core.pipeline_limits import MAX_AGENTIC_IMAGES
        from services import orchestrator_service, pipeline_stages

        assert pipeline_stages.MAX_AGENTIC_IMAGES == MAX_AGENTIC_IMAGES
        assert orchestrator_service.MAX_AGENTIC_IMAGES_PER_EXCHANGE == MAX_AGENTIC_IMAGES

    def test_neither_module_declares_its_own_literal(self):
        """The number lives in `core/pipeline_limits` and nowhere else."""
        for relative in (
            "services/pipeline_stages.py",
            "services/orchestrator_service.py",
        ):
            source = Path(__file__).resolve().parents[1] / relative
            tree = ast.parse(source.read_text())
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and "AGENTIC_IMAGES" in target.id:
                        assert not isinstance(node.value, ast.Constant), (
                            f"{relative} assigns its own copy of {target.id}"
                        )

    def test_the_stage_no_longer_reads_a_key_nothing_writes(self):
        """`agentic_image_count` was the dead key the budget read.

        Checked as a string LITERAL inside the stage, so the comment that
        explains the defect does not count as a use of it.
        """
        source = (
            Path(__file__).resolve().parents[1] / "services" / "pipeline_stages.py"
        ).read_text()
        tree = ast.parse(source)
        stage_fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "illustrate_stage"
        )
        literals = {
            node.value
            for node in ast.walk(stage_fn)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert "agentic_image_count" not in literals
