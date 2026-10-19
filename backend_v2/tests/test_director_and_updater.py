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
        assert res.should_trigger_image is True
        assert res.should_run_updater is True
        assert res.updater_gates["gate_world_state"] == pytest.approx(0.81)
        assert res.updater_gates["gate_inventory_or_items"] == pytest.approx(0.71)
        assert "gate_world_state" in res.triggered_gates
        assert "gate_inventory_or_items" in res.triggered_gates

    def test_image_threshold_is_configurable_per_chat(self):
        raw = {"trigger_image": {"probability": 0.55}}

        default = parse_director_result(dict(raw))
        assert default.image_threshold == pytest.approx(0.65)
        assert default.should_trigger_image is False

        eager = parse_director_result(
            dict(raw),
            state_snapshot={"image_threshold": 0.50},
        )
        assert eager.image_threshold == pytest.approx(0.50)
        assert eager.should_trigger_image is True

        disabled = parse_director_result(
            dict(raw),
            allow_image_generation=False,
            state_snapshot={"image_threshold": 0.10},
        )
        assert disabled.should_trigger_image is False

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

    def test_completion_confidence_bands_prefer_laya_then_syntax(self):
        incomplete = "The gates creaked open and"
        complete = "The gates creaked open."

        confident_incomplete = parse_director_result(
            {"is_complete": {"probability": 0.2}}, context_text=complete
        )
        assert confident_incomplete.is_complete is False
        assert confident_incomplete.completion_source == "laya"

        confident_complete = parse_director_result(
            {"is_complete": {"probability": 0.9}}, context_text=incomplete
        )
        assert confident_complete.is_complete is True
        assert confident_complete.completion_source == "laya"

        uncertain = parse_director_result(
            {"is_complete": {"probability": 0.5}}, context_text=incomplete
        )
        assert uncertain.is_complete is False
        assert uncertain.completion_source == "syntax"
        assert uncertain.is_complete_laya_prob == 0.5

        forced_syntax = parse_director_result(
            {"is_complete": {"probability": 0.9}},
            context_text=incomplete,
            state_snapshot={"completion_policy": "syntax"},
        )
        assert forced_syntax.is_complete is False
        assert forced_syntax.completion_source == "syntax"


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
                "affinity_delta": 2,
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
        assert chat.state_snapshot["character_affinity"] == 52
        assert "character_affinity" in summary["last_updater_result"]["applied_fields"]

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

    def test_record_director_decision_leaves_affinity_to_updater(self, session: Session):
        char = Character(name="Kael", description="A knight")
        session.add(char)
        session.commit()
        chat = Chat(character_id=char.id, state_snapshot={"character_affinity": 50, "character_mood": "calm"})
        session.add(chat)
        session.commit()

        decision = DirectorDecisionResult(
            scene_tension=2.0,
            emotional_tone="warm_intimate",
        )
        snap = record_director_decision(session, chat.id, decision)
        # Affinity and mood are Statekeeper-owned: the Director does not modify them.
        assert snap["character_affinity"] == 50
        assert snap["character_mood"] == "calm"

    def test_laya_gater_does_not_overwrite_existing_mood(self, session: Session):
        char = Character(name="Kael", description="A knight")
        session.add(char)
        session.commit()
        chat = Chat(character_id=char.id, state_snapshot={"character_mood": "Cautious and vigilant"})
        session.add(chat)
        session.commit()

        decision = DirectorDecisionResult(
            mood_shift_detected=True,
            scene_tension=2.0,
            emotional_tone="warm_intimate",
        )
        snap = record_director_decision(session, chat.id, decision)
        # Should preserve the narrative mood, leaving mood updates to the Updater
        assert snap["character_mood"] == "Cautious and vigilant"
        assert snap["last_director_decision"]["mood_shift_detected"] is True

    def test_expression_locking_preserves_locked_expression(self, session: Session):
        char = Character(
            name="Kael",
            description="A knight",
            expressions={"blushing": "avatar_blush.png", "angry": "avatar_angry.png"},
        )
        session.add(char)
        session.commit()
        chat = Chat(
            character_id=char.id,
            state_snapshot={
                "character_expression": "blushing",
                "locked_fields": ["character_expression"],
            },
        )
        session.add(chat)
        session.commit()

        from services.updater_service import apply_updater_result

        res = apply_updater_result(
            session,
            chat_id=chat.id,
            character_id=char.id,
            raw_text='{"character_expression": "angry"}',
            triggered_gates=["gate_character_mood"],
        )
        assert res["state_snapshot"]["character_expression"] == "blushing"

    def test_updater_updates_expression_under_mood_gate(self, session: Session):
        char = Character(
            name="Kael",
            description="A knight",
            expressions={"blushing": "avatar_blush.png", "angry": "avatar_angry.png"},
        )
        session.add(char)
        session.commit()
        chat = Chat(
            character_id=char.id,
            state_snapshot={"character_expression": "blushing"},
        )
        session.add(chat)
        session.commit()

        from services.updater_service import apply_updater_result

        # When gate_character_mood fires:
        res = apply_updater_result(
            session,
            chat_id=chat.id,
            character_id=char.id,
            raw_text='{"character_expression": "angry"}',
            triggered_gates=["gate_character_mood"],
        )
        assert res["state_snapshot"]["character_expression"] == "angry"
        assert res["state_snapshot"]["character_expression_avatar"] == "avatar_angry.png"

        # When gate_character_mood did NOT fire: dropped!
        res2 = apply_updater_result(
            session,
            chat_id=chat.id,
            character_id=char.id,
            raw_text='{"character_expression": "blushing"}',
            triggered_gates=["gate_inventory_or_items"],
        )
        assert res2["state_snapshot"]["character_expression"] == "angry"

    def test_chat_entity_defaults_max_autonomous_turns_to_4(self, session: Session):
        chat = Chat(title="Autonomous Conductor Chat")
        session.add(chat)
        session.commit()
        session.refresh(chat)

        assert chat.max_autonomous_turns == 4
        assert chat.director_autonomy_level == "balanced"
        assert chat.director_enabled is True

    def test_director_does_not_overwrite_existing_emotional_tone(self, session: Session):
        char = Character(name="Kael", description="A knight")
        session.add(char)
        session.commit()
        chat = Chat(character_id=char.id, state_snapshot={"emotional_tone": "Tense, rain-slicked noir showdown"})
        session.add(chat)
        session.commit()

        decision = DirectorDecisionResult(
            emotional_tone="warm_intimate",
            scene_tension=3.0,
        )
        snap = record_director_decision(session, chat.id, decision)
        # Director must NOT overwrite the atmospheric tone with generic "warm_intimate"
        assert snap["emotional_tone"] == "Tense, rain-slicked noir showdown"
        assert snap["last_director_decision"]["emotional_tone"] == "warm_intimate"

    def test_updater_updates_nuanced_mood_and_emotional_tone(self, session: Session):
        char = Character(name="Lyra", description="A rogue netrunner")
        session.add(char)
        session.commit()
        chat = Chat(
            character_id=char.id,
            state_snapshot={
                "emotional_tone": "Conversational",
                "character_mood": "Neutral",
            },
        )
        session.add(chat)
        session.commit()

        updater_json = json.dumps(
            {
                "emotional_tone": "Ominous silence broken by distant sirens",
                "character_mood": "Slightly guarded but intrigued",
                "current_activity": "Listening intently at the alleyway entrance",
            }
        )
        summary = apply_updater_result(
            session,
            chat_id=chat.id,
            character_id=char.id,
            raw_text=updater_json,
            triggered_gates=["gate_scene_tone", "gate_character_mood", "gate_current_activity"],
        )
        assert summary["applied"] is True
        session.refresh(chat)
        assert chat.state_snapshot["emotional_tone"] == "Ominous silence broken by distant sirens"
        assert chat.state_snapshot["character_mood"] == "Slightly guarded but intrigued"
        assert chat.state_snapshot["current_activity"] == "Listening intently at the alleyway entrance"
        assert "last_updater_result" in chat.state_snapshot
        last_upd = chat.state_snapshot["last_updater_result"]
        assert "emotional_tone" in last_upd["applied_fields"]
        assert "character_mood" in last_upd["applied_fields"]
        assert "Ominous silence" in last_upd["summary"]

    def test_updater_enforces_triggered_gates_and_wild_mode(self, session: Session):
        char = Character(name="Kael", description="A knight")
        session.add(char)
        session.commit()
        chat = Chat(
            character_id=char.id,
            state_snapshot={"weather": "Clear", "character_mood": "Calm"},
        )
        session.add(chat)
        session.commit()

        raw = json.dumps(
            {
                "weather": "Thunderstorm",
                "character_mood": "Alert",
                "scene_summary": "Storm rolls in.",
            }
        )
        res = apply_updater_result(
            session,
            chat_id=chat.id,
            character_id=char.id,
            raw_text=raw,
            triggered_gates=["gate_character_mood"],
        )
        snap = res["state_snapshot"]
        assert snap["character_mood"] == "Alert"
        assert snap["weather"] == "Clear"
        assert "weather" in res["last_updater_result"]["dropped_keys"]
        assert "weather" not in res["last_updater_result"]["deltas"]

        wild_chat = Chat(
            character_id=char.id,
            state_snapshot={"weather": "Clear", "director_mode": "wild"},
        )
        session.add(wild_chat)
        session.commit()
        wild_res = apply_updater_result(
            session,
            chat_id=wild_chat.id,
            character_id=char.id,
            raw_text=raw,
            triggered_gates=[],
        )
        assert wild_res["state_snapshot"]["weather"] == "Thunderstorm"
        assert wild_res["last_updater_result"]["dropped_keys"] == []

    def test_updater_owns_character_expression_behind_mood_gate(self, session: Session):
        char = Character(
            name="Mira",
            description="A bard",
            expressions={"Happy": "/avatars/mira_happy.png", "angry": "/avatars/mira_angry.png"},
        )
        session.add(char)
        session.commit()

        def _chat():
            chat = Chat(character_id=char.id, state_snapshot={})
            session.add(chat)
            session.commit()
            return chat

        raw = json.dumps({"character_expression": "happy"})

        # Gate fired + registered label (case-insensitive): applied with the canonical key.
        fired = _chat()
        res = apply_updater_result(
            session,
            chat_id=fired.id,
            character_id=char.id,
            raw_text=raw,
            triggered_gates=["gate_character_mood"],
        )
        assert res["state_snapshot"]["character_expression"] == "Happy"
        assert res["state_snapshot"]["character_expression_avatar"] == "/avatars/mira_happy.png"
        assert "character_expression" in res["last_updater_result"]["applied_fields"]

        # Gate did not fire: the field is dropped.
        gated = _chat()
        res = apply_updater_result(
            session, chat_id=gated.id, character_id=char.id, raw_text=raw, triggered_gates=[]
        )
        assert "character_expression" not in res["state_snapshot"]
        assert "character_expression" in res["last_updater_result"]["dropped_keys"]

        # Unknown label: ignored even when the gate fired.
        unknown = _chat()
        res = apply_updater_result(
            session,
            chat_id=unknown.id,
            character_id=char.id,
            raw_text=json.dumps({"character_expression": "ecstatic"}),
            triggered_gates=["gate_character_mood"],
        )
        assert "character_expression" not in res["state_snapshot"]

    def test_decision_diagnostics_and_questions_evaluated(self):
        raw = {
            "next_speaker": {"choice": "character"},
            "pacing_directive": {"choice": "sensory_detail"},
            "scene_tension": {"score": 3.0},
            "pacing_speed": {"score": 2.0},
            "emotional_tone": {"choice": "mysterious_tense"},
            "gate_world_state": {"probability": 0.40},
            "gate_scene_tone": {"probability": 0.72},
            "gate_character_state": {"probability": 0.30},
            "gate_character_mood": {"probability": 0.65},
            "gate_relationship_dynamic": {"probability": 0.20},
            "gate_inventory_or_items": {"probability": 0.10},
            "gate_durable_memory": {"probability": 0.15},
            "gate_lore_discovery": {"probability": 0.05},
        }
        res = parse_director_result(
            raw,
            engine_used="remote_laya_cpu:colab",
            model_id="laya_multilingual",
        )
        assert res.should_run_updater is True
        assert "gate_scene_tone" in res.triggered_gates
        assert "gate_character_mood" in res.triggered_gates

        eval_info = res.updater_evaluation
        assert eval_info["should_run_updater"] is True
        assert eval_info["activation_threshold"] == 0.55
        assert "Scene Tone / Atmosphere" in eval_info["diagnostic_summary"]
        assert len(res.questions_evaluated) >= 14

        # Verify question trace contains questions and rubrics
        q_keys = {q["key"] for q in res.questions_evaluated}
        assert "gate_scene_tone" in q_keys
        assert "emotional_tone" in q_keys
        tone_q = next(q for q in res.questions_evaluated if q["key"] == "gate_scene_tone")
        assert tone_q["type"] == "noul"
        assert tone_q["category"] == "Statekeeper Gates"
        assert "FIRED" in tone_q["status"]

    def test_parse_director_result_extracts_sub_variant(self):
        raw = {
            "next_speaker": {"choice": "narrator"},
            "narrator_variant": {"choice": "narrator-combat"},
            "pacing_directive": {"choice": "escalate_conflict"},
            "scene_tension": {"score": 4.0},
        }
        res = parse_director_result(raw)
        assert res.next_speaker == "narrator"
        assert res.selected_variant == "narrator-combat"

        char_raw = {
            "next_speaker": {"choice": "character"},
            "character_variant": {"choice": "character-playful"},
        }
        res_char = parse_director_result(char_raw)
        assert res_char.next_speaker == "character"
        assert res_char.selected_variant == "character-playful"

    @pytest.mark.asyncio
    async def test_decision_service_records_trace_and_custom_directive(self, session: Session):
        from core.entities import Chat, DirectorTrace
        from services.decision_service import DecisionService
        from services.laya_questions import save_or_update_question_override

        chat = Chat(name="Trace Chat")
        session.add(chat)
        session.commit()
        session.refresh(chat)

        # Add custom question
        save_or_update_question_override(
            session,
            "triage",
            "is_combat_scene",
            question="Is this an active combat sequence?",
            directive="Use dynamic short sentences and tactical awareness.",
            threshold=0.50,
            is_custom=True,
        )

        service = DecisionService(session)
        # Mock _try_remote_agent to return raw_answers with the custom question firing
        decision = await service.evaluate_pre_generation_triage(
            character_name="Mira",
            user_name="Player",
            chat_id=chat.id,
            turn=1,
            model_override="disabled",
        )
        assert decision.workflow_stage == "triage"

        # Verify trace was persisted
        traces = session.exec(select(DirectorTrace).where(DirectorTrace.chat_id == chat.id)).all()
        assert len(traces) == 1
        assert traces[0].stage == "triage"
        assert traces[0].turn == 1

    def test_pipeline_and_questions_api_routes(self, client):
        resp = client.get("/api/v2/llm/pipeline")
        assert resp.status_code == 200
        data = resp.json()
        assert "stages" in data
        assert len(data["stages"]) == 6
        assert data["limits"]["max_turns"] == 4
        assert data["limits"]["max_continuations"] == 4

        # List questions
        q_resp = client.get("/api/v2/llm/questions")
        assert q_resp.status_code == 200
        qs = q_resp.json()
        assert any(q["key"] == "gate_character_mood" for q in qs)
        assert any(q["stage"] == "triage" for q in qs)

        # Create custom question
        post_resp = client.post(
            "/api/v2/llm/questions/triage/custom",
            json={
                "key": "custom_whisper",
                "question": "Is the user whispering secret information?",
                "directive": "Reply in hushed, intimate tones.",
                "threshold": 0.70,
            },
        )
        assert post_resp.status_code == 200
        created = post_resp.json()
        assert created["key"] == "custom_whisper"
        assert created["is_custom"] is True

        # Toggle/update question
        put_resp = client.put(
            "/api/v2/llm/questions/triage/custom_whisper",
            json={"enabled": False},
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["enabled"] is False

        # Delete question
        del_resp = client.delete("/api/v2/llm/questions/triage/custom_whisper")
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True


def test_providers_health_aggregate(client):
    """Aggregate provider health returns status per provider."""
    resp = client.get("/api/v2/llm/providers/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "providers" in body
    assert "healthy_count" in body
    assert "total_count" in body
    for p in body["providers"]:
        assert "provider_id" in p
        assert "healthy" in p
        assert "models" in p
        assert "latency_ms" in p


def test_agents_with_variants(client):
    """Agents endpoint returns profiles with variant lists."""
    resp = client.get("/api/v2/llm/agents/with-variants")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    if body:
        agent = body[0]
        assert "slug" in agent
        assert "variants" in agent
        assert "active_variant_slug" in agent
        assert "resolved_prompt_template" in agent


def test_variant_questions_injected_for_custom_agents(session):
    """Laya injects variant choice questions for any agent with variants."""
    from services.laya_questions import resolve_stage_questions
    from core.entities import AgentProfile, AgentPromptVariant

    agent = AgentProfile(
        id="agent-alchemist",
        slug="alchemist",
        name="Royal Alchemist",
        agent_type="custom",
        description="Master apothecary",
        system_prompt_template="You are an alchemist.",
        model_target="rp",
        is_builtin=False,
        enabled=True,
    )
    session.add(agent)
    session.commit()

    variant = AgentPromptVariant(
        agent_id=agent.id,
        slug="painterly",
        name="Painterly",
        description="Focus on colors and textures",
        system_prompt_template="You are a painterly alchemist.",
        is_active=True,
    )
    session.add(variant)
    session.commit()

    available = [{"slug": agent.slug, "name": agent.name, "description": agent.description}]
    qs = resolve_stage_questions(
        session,
        "triage",
        available_agents=available,
    )
    keys = {q["key"] for q in qs}
    assert "alchemist_variant" in keys
    variant_q = next(q for q in qs if q["key"] == "alchemist_variant")
    assert variant_q["type"] == "choice"
    assert "painterly" in variant_q["options"]


def test_parse_director_result_resolves_custom_agent_variant():
    """Variant resolution handles any agent slug, not just character/narrator."""
    from services.decision_schema import parse_director_result

    result = parse_director_result(
        {
            "next_speaker": "alchemist",
            "alchemist_variant": {"choice": "painterly"},
        },
        engine_used="test",
        model_id="test-model",
        allow_image_generation=False,
        state_snapshot={},
        context_text="",
    )
    assert result.selected_variant == "painterly"
    assert result.selected_agent == "alchemist"



