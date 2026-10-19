"""End-to-end tests for the 3-stage multi-agent pipeline and 16-field gating."""

from __future__ import annotations

import pytest
from sqlmodel import Session

from core.entities import AgentProfile, Character, Chat
from services.decision_service import DecisionService
from services.updater_service import (
    apply_updater_result,
    build_state_updater_prompt,
    seed_initial_state_snapshot,
)


@pytest.mark.asyncio
async def test_pre_generation_triage_with_custom_agents(session: Session):
    # 1. Register custom agent profile
    custom = AgentProfile(
        id="agent-alchemist",
        slug="alchemist",
        name="Royal Alchemist",
        agent_type="specialist",
        description="Master apothecary providing detailed chemical and potion analysis.",
        system_prompt_template="You are the Royal Alchemist analyzing reagents.",
        model_target="rp",
        is_builtin=False,
        enabled=True,
    )
    session.add(custom)
    session.commit()

    service = DecisionService(session)
    triage = await service.evaluate_pre_generation_triage(
        character_name="Elysia",
        user_name="Player",
        story_location="Apothecary Lab",
        story_time="Dusk",
        state_snapshot={
            "character_skills": ["Arcane Magic", "Alchemy"],
            "user_skills": ["Field Medicine"],
            "fate_check_enabled": True,
            "fate_difficulty": "moderate",
        },
        recent_messages=[
            {"role": "user", "content": "I need an antidote for this nightshade poison immediately!"}
        ],
    )

    assert triage.workflow_stage == "triage"
    assert triage.selected_agent in ("character", "narrator", "alchemist")
    assert triage.pacing_directive in (
        "continue_conversation",
        "sensory_detail",
        "escalate_tension",
        "advance_time_or_scene",
        "de_escalate_reflect",
    )
    # Fate check matched Alchemy or Field Medicine
    assert len(triage.matched_skills) >= 1
    assert triage.fate_outcome in (
        "critical_success",
        "success",
        "success_with_cost",
        "complication",
        "failure",
    )
    assert triage.fate_directive is not None


@pytest.mark.asyncio
async def test_post_generation_audit_and_completion_detection(session: Session):
    service = DecisionService(session)

    # Incomplete prose (ends on a dangling conjunction / preposition)
    incomplete_text = "The castle gates creaked open, revealing a shadowed figure who whispered into the dark and"
    audit_inc = await service.evaluate_post_generation_audit(
        generated_text=incomplete_text,
        character_name="Elysia",
        user_name="Player",
        story_location="Castle Gates",
        story_time="Midnight",
        state_snapshot={"completion_policy": "syntax"},
        recent_messages=[],
    )
    assert audit_inc.workflow_stage == "audit"
    assert audit_inc.is_complete is False

    # Complete prose
    complete_text = "The castle gates creaked open, revealing a shadowed figure who whispered into the dark. 'Welcome home.'"
    audit_comp = await service.evaluate_post_generation_audit(
        generated_text=complete_text,
        character_name="Elysia",
        user_name="Player",
        story_location="Castle Gates",
        story_time="Midnight",
        state_snapshot={"completion_policy": "syntax"},
        recent_messages=[],
    )
    assert audit_comp.is_complete is True


@pytest.mark.asyncio
async def test_turn_chaining_evaluation(session: Session):
    service = DecisionService(session)
    chaining = await service.evaluate_turn_chaining(
        last_speaker="character",
        character_name="Elysia",
        user_name="Player",
        story_location="Tavern",
        story_time="Evening",
        state_snapshot={},
        recent_messages=[
            {"role": "char", "content": "*Elysia drops her glass as an arrow shatters the window!* Get down!"}
        ],
        allow_narration=True,
    )
    assert chaining.workflow_stage == "chaining"
    assert 0.0 <= chaining.continue_chain_probability <= 1.0
    assert chaining.next_speaker in ("character", "narrator", "user", "secondary_character", "alchemist")


def test_updater_service_scoped_16_gates(session: Session):
    # Test prompt generation scoped to specific gates
    prompt = build_state_updater_prompt(
        character_name="Elysia",
        user_name="Player",
        current_location="Whispering Woods",
        current_time="Night",
        state_snapshot={
            "emotional_tone": "Tense",
            "character_mood": "Alert",
            "weather": "Foggy",
            "physical_condition": "Unharmed",
        },
        recent_lines=["Player: Did you hear that rustling in the bushes?", "Elysia: Stay behind me. It's close."],
        triggered_gates=["gate_character_mood", "gate_weather_change", "gate_physical_condition"],
    )
    assert "character_mood" in prompt
    assert "weather" in prompt
    assert "physical_condition" in prompt
    assert "inventory_add" not in prompt  # inventory gate was NOT triggered

    # Test snapshot seeding
    snap = seed_initial_state_snapshot()
    assert "physical_condition" in snap
    assert "weather" in snap
    assert "quests_and_goals" in snap
    assert "social_status" in snap

    # Test applying deltas to chat
    char = Character(name="Elysia", visual_tags=["silver hair", "blue eyes"])
    session.add(char)
    session.commit()

    chat = Chat(name="Test Chat", character_id=char.id, state_snapshot=snap)
    session.add(chat)
    session.commit()

    raw_json = """
    {
      "character_mood": "Fierce & determined",
      "emotional_tone": "Electrifying tension",
      "weather": "Thunderstorm",
      "physical_condition": "Scratched forearm, winded",
      "quests_and_goals": ["Survive the beast ambushing the camp", "Find the herbalist"],
      "social_status": "Respected vanguard",
      "inventory_add": ["Silver Dagger"],
      "scene_summary": "Elysia and Player brace against the prowling shadow."
    }
    """
    res = apply_updater_result(
        session,
        chat_id=chat.id,
        character_id=char.id,
        raw_text=raw_json,
        triggered_gates=["gate_character_mood", "gate_scene_tone", "gate_weather_change", "gate_physical_condition", "gate_quests_and_goals", "gate_inventory_or_items"],
    )
    assert res["applied"] is True
    updated_snap = res["state_snapshot"]
    assert updated_snap["character_mood"] == "Fierce & determined"
    assert updated_snap["emotional_tone"] == "Electrifying tension"
    assert updated_snap["weather"] == "Thunderstorm"
    assert updated_snap["physical_condition"] == "Scratched forearm, winded"
    assert "Silver Dagger" in updated_snap["inventory"]
    assert len(updated_snap["quests_and_goals"]) == 2

