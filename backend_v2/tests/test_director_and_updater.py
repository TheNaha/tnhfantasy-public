"""Tests for the System 1 Decision Maker (Director) and Statekeeper (Updater)."""

import json
import pytest
from sqlmodel import Session, select

from core.entities import Character, Chat, Lorebook, LorebookEntry
from services.context_builder import build_system_prompt_sections
from services.decision_schema import (
    UPDATER_GATE_KEYS,
    DirectorDecisionResult,
    build_director_questions,
    format_director_context,
    heuristic_director_decision,
    parse_director_result,
    parse_generative_fallback_json,
)
from services.decision_service import DecisionService
from services.updater_service import apply_updater_result, record_director_decision


class TestDecisionSchema:
    def test_builds_all_13_typed_questions(self):
        questions = build_director_questions(has_secondary_character=True)
        by_key = {q["key"]: q for q in questions}
        expected_keys = {
            "next_speaker",
            "continue_chain",
            "pacing_directive",
            "scene_tension",
            "pacing_speed",
            "emotional_tone",
            "trigger_image",
            "image_focus",
            "character_expression",
            "gate_world_state",
            "gate_character_state",
            "gate_inventory_or_items",
            "gate_durable_memory",
            "gate_lore_discovery",
        }
        assert expected_keys.issubset(set(by_key.keys()))
        assert "secondary_character" in by_key["next_speaker"]["options"]

        single_questions = build_director_questions(has_secondary_character=False)
        single_by_key = {q["key"]: q for q in single_questions}
        assert "secondary_character" not in single_by_key["next_speaker"]["options"]

    def test_parses_laya_raw_output_and_triggers_updater_gates(self):
        raw = {
            "next_speaker": {
                "choice": "character",
                "probabilities": {"character": 0.82, "narrator": 0.12, "user": 0.06},
            },
            "continue_chain": {"probability": 0.74},
            "pacing_directive": {
                "choice": "escalate_tension",
                "probabilities": {"escalate_tension": 0.65, "continue_conversation": 0.35},
            },
            "scene_tension": {"score": 4.2},
            "pacing_speed": {"score": 2.5},
            "emotional_tone": {
                "choice": "dramatic_conflict",
                "probabilities": {"dramatic_conflict": 0.78, "warm_intimate": 0.22},
            },
            "trigger_image": {"probability": 0.72},
            "image_focus": {"choice": "character_portrait", "probabilities": {"character_portrait": 0.9}},
            "character_expression": {"choice": "surprised", "probabilities": {"surprised": 0.88}},
            "gate_world_state": {"probability": 0.81},
            "gate_character_state": {"probability": 0.22},
            "gate_inventory_or_items": {"probability": 0.71},
            "gate_durable_memory": {"probability": 0.64},
            "gate_lore_discovery": {"probability": 0.12},
        }
        res = parse_director_result(
            raw,
            engine_used="remote_laya_cpu:colab",
            model_id="laya_multilingual",
            latency_ms=34.5,
            allow_image_generation=True,
        )
        assert res.next_speaker == "character"
        assert res.pacing_directive == "escalate_tension"
        assert res.scene_tension == pytest.approx(4.2)
        assert res.emotional_tone == "dramatic_conflict"
        assert res.character_expression == "surprised"
        assert res.should_trigger_image is True
        assert res.should_run_updater is True
        assert res.updater_gates["gate_world_state"] == pytest.approx(0.81)
        assert res.updater_gates["gate_inventory_or_items"] == pytest.approx(0.71)
        assert "gate_world_state" in res.triggered_gates
        assert "gate_inventory_or_items" in res.triggered_gates
        assert hasattr(res, "affinity_delta")
        assert hasattr(res, "character_mood")

    def test_parses_generative_json_fallback(self):
        raw_text = """```json
        {
          "next_speaker": "narrator",
          "continue_chain": 0.4,
          "pacing_directive": "sensory_detail",
          "scene_tension": 3.5,
          "pacing_speed": 1.5,
          "emotional_tone": "mysterious_tense",
          "trigger_image": 0.75,
          "image_focus": "environment_wide",
          "character_expression": "surprised",
          "gate_world_state": 0.85,
          "gate_character_state": 0.2,
          "gate_inventory_or_items": 0.05,
          "gate_durable_memory": 0.65,
          "gate_lore_discovery": 0.1
        }
        ```"""
        parsed = parse_generative_fallback_json(raw_text)
        res = parse_director_result(
            parsed,
            engine_used="util_llm_json:default",
            model_id="gemma3_12b_heretic_util",
            latency_ms=120.0,
        )
        assert res.engine_used == "util_llm_json:default"
        assert res.next_speaker == "narrator"
        assert res.scene_tension == pytest.approx(3.5)
        assert res.should_run_updater is True
        assert "gate_world_state" in res.triggered_gates
        assert "gate_durable_memory" in res.triggered_gates

    def test_heuristic_fallback_detects_scene_deltas(self):
        ctx = format_director_context(
            character_name="Aria",
            user_name="Traveler",
            recent_messages=[
                {
                    "role": "user",
                    "content": "We walk into the tavern at nightfall and I hand you the ancient brass key.",
                }
            ],
            last_speaker="user",
        )
        res = heuristic_director_decision(
            ctx,
            last_speaker="user",
            has_secondary_character=False,
        )
        assert res.engine_used == "heuristic"
        assert res.updater_gates["gate_world_state"] >= 0.55
        assert res.updater_gates["gate_inventory_or_items"] >= 0.55
        assert res.should_run_updater is True


class TestDirectorCascadeAndUpdater:
    @pytest.mark.asyncio
    async def test_evaluate_scene_falls_back_cleanly(self, session: Session, monkeypatch):
        svc = DecisionService(session)

        # Force disabled mode test first
        res_disabled = await svc.evaluate_scene(
            character_name="Aria",
            recent_messages=[{"role": "user", "content": "Hello there!"}],
            last_speaker="user",
            model_override="disabled",
        )
        assert res_disabled.model_id == "disabled"
        assert res_disabled.engine_used == "disabled"
        assert res_disabled.next_speaker == "character"

        # Force cascade to heuristic when remote & local Laya are absent
        async def _no_tier(*args, **kwargs):
            return None

        monkeypatch.setattr(svc, "_try_remote_agent", _no_tier)
        monkeypatch.setattr(svc, "_try_local_laya", _no_tier)

        res_heur = await svc.evaluate_scene(
            character_name="Aria",
            recent_messages=[
                {"role": "user", "content": "We arrive at the tavern at sunset and take the ring."}
            ],
            last_speaker="user",
            model_override="laya_multilingual",
        )
        assert res_heur.engine_used == "heuristic"
        assert res_heur.should_run_updater is True

    def test_apply_updater_result_updates_chat_lore_and_memory(self, session: Session, monkeypatch):
        import services.updater_service as upd_mod

        monkeypatch.setattr(
            upd_mod,
            "create_memories_from_extraction",
            lambda s, cid, mems: len(mems),
        )

        lb = Lorebook(name="Test World Lore")
        session.add(lb)
        session.commit()
        session.refresh(lb)

        char = Character(name="Lyra", description="A rogue netrunner", lorebook_ids=[lb.id])
        session.add(char)
        session.commit()
        session.refresh(char)

        chat = Chat(
            name="Neon Heist",
            character_id=char.id,
            persona_name="Vex",
            active_lorebook_ids=[lb.id],
            director_enabled=True,
            state_snapshot={"inventory": ["Data Deck"]},
        )
        session.add(chat)
        session.commit()
        session.refresh(chat)

        decision = heuristic_director_decision(
            "We arrive at the vault.",
            last_speaker="character",
        )
        snap = record_director_decision(session, chat.id, decision)
        assert "last_director_decision" in snap

        updater_json = json.dumps(
            {
                "story_location": "Arasaka Sub-Vault",
                "story_time": "02:15 AM, Cyberspace Lockdown",
                "character_mood": "Focused and exhilarated",
                "character_outfit": "Stealth tactical suit",
                "current_activity": "Bypassing the ICE firewall",
                "relationship_status": "Trusted partners in crime",
                "inventory_add": ["Arasaka Master Shard"],
                "inventory_remove": [],
                "scene_summary": "Lyra and Vex breached the sub-vault and secured the master shard.",
                "new_memories": [
                    "Vex covered Lyra while she breached the Arasaka sub-vault ICE."
                ],
                "new_lore": [
                    {
                        "keys": ["Arasaka Sub-Vault", "Sub-Vault"],
                        "category": "location",
                        "content": "A subterranean cryogenic data vault beneath Sector 7.",
                    }
                ],
            }
        )

        summary = apply_updater_result(
            session,
            chat_id=chat.id,
            character_id=char.id,
            raw_text=updater_json,
            triggered_gates=list(UPDATER_GATE_KEYS),
        )
        assert summary["applied"] is True
        assert summary["memories_created"] == 1
        assert summary["lore_created"] == 1

        session.refresh(chat)
        assert chat.story_location == "Arasaka Sub-Vault"
        assert chat.story_time == "02:15 AM, Cyberspace Lockdown"
        assert chat.state_snapshot["character_mood"] == "Focused and exhilarated"
        assert chat.state_snapshot["character_outfit"] == "Stealth tactical suit"
        assert "Arasaka Master Shard" in chat.state_snapshot["inventory"]
        assert "Data Deck" in chat.state_snapshot["inventory"]

        entries = list(
            session.exec(
                select(LorebookEntry).where(LorebookEntry.lorebook_id == lb.id)
            ).all()
        )
        assert len(entries) == 1
        assert "Arasaka Sub-Vault" in entries[0].keys

    def test_context_builder_injects_state_snapshot_and_director_directive(self, session: Session):
        char = Character(name="Lyra", description="A rogue netrunner")
        sections = build_system_prompt_sections(
            session,
            character=char,
            state_snapshot={
                "character_mood": "Focused",
                "current_activity": "Decoding shard",
                "character_outfit": "Stealth suit",
                "relationship_status": "Allies",
                "inventory": ["Master Shard"],
                "scene_tension": 4.0,
                "emotional_tone": "mysterious_tense",
            },
            director_directive="Pacing Directive: escalate_tension | Scene Tension: 4.0/5",
        )
        labels = [s["label"] for s in sections]
        assert "Live State Snapshot (Statekeeper)" in labels
        assert "Director Pacing Directive (System 1)" in labels
        formatted = format_director_context(
            character_name="Lyra",
            recent_messages=[{"role": "user", "content": "Ready?"}],
            state_snapshot={"character_mood": "Focused"},
        )
        assert "Lyra" in formatted

    def test_record_director_decision_updates_affinity_and_mood(self, session: Session):
        char = Character(name="Kael", description="A knight")
        session.add(char)
        session.commit()
        chat = Chat(character_id=char.id, state_snapshot={"character_affinity": 50})
        session.add(chat)
        session.commit()

        decision = DirectorDecisionResult(
            affinity_delta=2,
            character_mood="warm_affectionate",
            scene_tension=2.0,
            emotional_tone="warm_intimate",
        )
        snap = record_director_decision(session, chat.id, decision)
        assert snap["character_affinity"] == 52
        assert snap["last_affinity_delta"] == 2
        assert snap["character_mood"] == "warm_affectionate"
