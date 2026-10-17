"""Tests for World Architect & Onboarding Studio, Toggleable Fate Checks, Skillsets, Multi-Target Relationships, and Living World features."""

import json
from sqlmodel import Session

from core.entities import Character, Chat, Location, World
from services.context_builder import build_system_prompt_sections
from services.decision_schema import heuristic_director_decision



class TestToggleableFateCheckAndSkillsets:
    def test_fate_check_disabled_by_default(self):
        res = heuristic_director_decision(
            "User: I try to hack the security terminal and disarm the laser grid.",
            last_speaker="user",
            state_snapshot={"fate_check_enabled": False},
        )
        assert res.fate_outcome is None
        assert res.fate_directive is None

    def test_fate_check_enabled_with_skill_advantage_and_difficulty(self):
        snap_skilled = {
            "fate_check_enabled": True,
            "fate_difficulty": "easy",
            "fate_outcome_override": "auto",
            "user_skills": ["Netrunning", "Terminal Hacking"],
            "character_skills": ["Stealth"],
        }
        res = heuristic_director_decision(
            "User: I attempt to hack the security terminal using my netrunning deck.",
            last_speaker="user",
            state_snapshot=snap_skilled,
        )
        assert res.fate_outcome in ("critical_success", "success")
        assert any("Hacking" in s or "Netrunning" in s for s in res.matched_skills)
        assert "Skills applied:" in (res.fate_directive or "")

    def test_fate_check_outcome_override_pins_desired_outcome(self):
        snap_override = {
            "fate_check_enabled": False,  # Even if toggle is off, explicit override works
            "fate_difficulty": "extreme",
            "fate_outcome_override": "critical_success",
        }
        res = heuristic_director_decision(
            "User: I leap across the impossible chasm.",
            last_speaker="user",
            state_snapshot=snap_override,
        )
        assert res.fate_outcome == "critical_success"
        assert "Critical Success" in (res.fate_directive or "")


class TestTurnZeroStateSeedingAndMultiRelationships:
    def test_create_chat_seeds_turn_zero_state_snapshot(self, client, session: Session):
        world = World(name="Aethelgard", description="High fantasy kingdom")
        session.add(world)
        session.commit()
        session.refresh(world)

        loc = Location(
            name="Moonlit Courtyard",
            description="A marble courtyard beneath silver spires.",
            world_id=world.id,
            atmosphere="Midnight",
        )
        session.add(loc)
        session.commit()
        session.refresh(loc)

        char = Character(
            name="Seraphina",
            description="An elven spellblade wearing a midnight-blue velvet cloak and carrying a runed rapier. Master of swordplay and arcane magic.",
            personality="Guarded, observant, fiercely loyal.",
            scenario="Meeting {{user}}, her new bodyguard, in the Moonlit Courtyard at Midnight.",
            first_mes="*Seraphina adjusts her midnight-blue velvet cloak as she watches you step into the Moonlit Courtyard.* \"You're late.\"",
            default_location="Moonlit Courtyard",
            default_time="Midnight",
            world_id=world.id,
        )
        npc = Character(
            name="Vaelen",
            description="Captain of the royal guard.",
            world_id=world.id,
        )
        session.add_all([char, npc])
        session.commit()
        session.refresh(char)
        session.refresh(npc)

        resp = client.post(
            "/api/v2/chats",
            json={
                "name": "Courtyard Watch",
                "world_id": world.id,
                "character_id": char.id,
                "additional_character_ids": [npc.id],
                "persona_name": "Kael",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["story_location"] == "Moonlit Courtyard"
        assert data["story_time"] == "Midnight"
        assert data["location_id"] == loc.id

        snap = data["state_snapshot"]
        assert snap["character_mood"]
        assert snap["current_activity"]
        assert "cloak" in snap["character_outfit"].lower()
        assert isinstance(snap["wardrobe"], list) and len(snap["wardrobe"]) >= 1
        assert isinstance(snap["character_skills"], list) and len(snap["character_skills"]) >= 1
        assert isinstance(snap["user_skills"], list) and len(snap["user_skills"]) >= 1
        assert isinstance(snap["relationships"], list) and len(snap["relationships"]) >= 2
        target_names = [r["target_name"] for r in snap["relationships"]]
        assert "Kael" in target_names
        assert "Vaelen" in target_names
        assert snap["world_clock"]["day"] == 1
        assert snap["world_clock"]["location"] == "Moonlit Courtyard"
        assert len(snap["world_clock"]["chronology_log"]) == 1

    def test_context_builder_injects_skills_relationships_clock_and_crossover(self, session: Session):
        char = Character(name="Seraphina", description="Elven spellblade")
        sections = build_system_prompt_sections(
            session,
            character=char,
            state_snapshot={
                "character_mood": "Guarded",
                "current_activity": "Patrolling the courtyard",
                "character_outfit": "Midnight-blue velvet cloak",
                "relationship_status": "Cautious allies",
                "relationships": [
                    {"target_name": "Kael", "target_type": "user", "status": "Sworn protector", "affinity": "trusted"},
                    {"target_name": "Vaelen", "target_type": "character", "status": "Rival captain", "affinity": "tense"},
                ],
                "character_skills": ["Swordplay", "Arcane Magic"],
                "user_skills": ["Tactical Defense", "Perception"],
                "world_clock": {
                    "day": 2,
                    "time_of_day": "Dawn",
                    "location": "Moonlit Courtyard",
                    "chronology_log": [
                        {"day": 1, "time": "Midnight", "location": "Courtyard", "event": "Survived the assassin ambush."}
                    ],
                },
                "crossover_context": "CROSSOVER CANON: Seraphina was pulled from Aethelgard into Neo-Tokyo.",
                "fate_check_enabled": True,
                "last_fate_outcome": "success",
                "last_fate_directive": "FATE / SKILL CHECK (MODERATE -> SUCCESS): The action succeeds cleanly.",
            },
        )
        by_label = {s["label"]: s["content"] for s in sections}
        assert "Live State Snapshot (Statekeeper)" in by_label
        snap_text = by_label["Live State Snapshot (Statekeeper)"]
        assert "Swordplay" in snap_text
        assert "Tactical Defense" in snap_text
        assert "Kael: Sworn protector" in snap_text
        assert "Vaelen: Rival captain" in snap_text
        assert "Day 2 · Dawn" in snap_text
        assert "Survived the assassin ambush" in snap_text
        assert "World Crossover Context" in by_label
        assert "Director Fate / Skill Check" in by_label


class TestWorldOnboardingStudioRoutes:
    def test_analyze_card_and_commit_world_blueprint(self, client, session: Session):
        card_json = {
            "spec": "chara_card_v2",
            "spec_version": "2.0",
            "data": {
                "name": "Astraea",
                "description": "Astraea is a cyber-valkyrie with silver hair and glowing blue eyes wearing a white chrono-armor suit. She guards the Astral Citadel.",
                "personality": "Noble, analytical, protective.",
                "scenario": "{{user}} is a dimensional engineer who just arrived at the Astral Citadel at Starlight Dusk.",
                "first_mes": "*Astraea lowers her plasma lance inside the Astral Citadel.* \"State your coordinates, traveler.\"",
                "alternate_greetings": [
                    "*In the Under-City Hangar at Midnight, Astraea repairs herdamaged wing-thrusters.*"
                ],
                "character_book": {
                    "name": "Astral Codex",
                    "entries": [
                        {
                            "keys": ["Astral Citadel", "Citadel"],
                            "content": "A floating fortress orbiting the shattered moon.",
                            "enabled": True,
                        }
                    ],
                },
            },
        }
        files = {"file": ("astraea.json", json.dumps(card_json).encode("utf-8"), "application/json")}
        resp = client.post("/api/v2/world-vault/onboarding/analyze-card", files=files)
        assert resp.status_code == 200, resp.text
        blueprint = resp.json()

        assert blueprint["source_type"] == "character_card"
        assert blueprint["characters"][0]["name"] == "Astraea"
        assert len(blueprint["scenarios"]) == 2
        assert len(blueprint["locations"]) >= 1
        assert blueprint["lorebook"]["create"] is True
        assert len(blueprint["lorebook"]["entries"]) == 1
        assert blueprint["initial_state_snapshot"]["character_skills"]

        # Enable Persona creation and commit the blueprint
        blueprint["persona"]["create"] = True
        blueprint["launch_chat"] = True
        blueprint["launch_story"] = True

        commit_resp = client.post("/api/v2/world-vault/onboarding/commit", json=blueprint)
        assert commit_resp.status_code == 200, commit_resp.text
        committed = commit_resp.json()

        assert committed["world_id"]
        assert len(committed["character_ids"]) == 1
        assert len(committed["location_ids"]) >= 1
        assert len(committed["scenario_ids"]) == 2
        assert committed["lorebook_id"]
        assert committed["persona_id"]
        assert committed["chat_id"]
        assert committed["story_id"]

        chat = session.get(Chat, committed["chat_id"])
        assert chat is not None
        assert chat.world_id == committed["world_id"]
        assert chat.state_snapshot["world_clock"]["day"] == 1

    def test_analyze_story_text_extracts_world_and_cast(self, client):
        prose = (
            "Aldric stood atop the Obsidian Watchtower as the crimson eclipse darkened the sky. "
            "Beside him, Lyris adjusted her emerald cloak and gripped her enchanted bow.\n\n"
            "\"The Shadow Vanguard will breach the Iron Gate before midnight,\" Lyris warned. "
            "Aldric drew his sun-forged greatsword, his mastery of pyromancy and swordplay ready for the siege."
        )
        resp = client.post(
            "/api/v2/world-vault/onboarding/analyze-story-text",
            json={"title": "Siege of the Obsidian Watchtower", "raw_text": prose},
        )
        assert resp.status_code == 200, resp.text
        bp = resp.json()
        assert bp["source_type"] == "document_story"
        assert bp["world"]["name"] == "Siege of the Obsidian Watchtower"
        char_names = [c["name"] for c in bp["characters"]]
        assert "Aldric" in char_names or "Lyris" in char_names
        assert len(bp["scenarios"]) >= 1

    def test_crossover_preview_and_live_world_actions(self, client, session: Session):
        world_a = World(name="Cyber Neo-Veridia", description="High-tech cyberpunk megacity")
        world_b = World(name="Eldoria", description="Ancient realm of dragons and leyline magic")
        session.add_all([world_a, world_b])
        session.commit()
        session.refresh(world_a)
        session.refresh(world_b)

        loc_b = Location(name="Dragonspire Sanctum", description="High altar of the dragon lords", world_id=world_b.id)
        loc_b2 = Location(name="Whispering Tavern", description="A cozy tavern in Eldoria", world_id=world_b.id)
        session.add_all([loc_b, loc_b2])
        session.commit()
        session.refresh(loc_b)
        session.refresh(loc_b2)

        traveler = Character(
            name="Kira-7",
            description="Cybernetic infiltrator with optical camo and plasma blades.",
            world_id=world_a.id,
        )
        resident = Character(
            name="Archmage Thorne",
            description="Keeper of the Dragonspire leylines.",
            world_id=world_b.id,
        )
        session.add_all([traveler, resident])
        session.commit()
        session.refresh(traveler)
        session.refresh(resident)

        cross_resp = client.post(
            "/api/v2/world-vault/onboarding/crossover-preview",
            json={
                "traveler_character_ids": [traveler.id],
                "target_world_id": world_b.id,
                "archetype": "rift_portal",
                "target_location_id": loc_b.id,
                "resident_character_ids": [resident.id],
                "commit_immediately": True,
            },
        )
        assert cross_resp.status_code == 200, cross_resp.text
        cross_data = cross_resp.json()
        assert cross_data["launched_chat_id"]
        assert "Kira-7" in cross_data["crossover_context"]

        chat_id = cross_data["launched_chat_id"]

        # Fast-Travel to Whispering Tavern
        ft_resp = client.post(
            f"/api/v2/world-vault/onboarding/fast-travel/{chat_id}",
            json={"location_id": loc_b2.id, "time_of_day": "Late Night"},
        )
        assert ft_resp.status_code == 200, ft_resp.text
        assert ft_resp.json()["story_location"] == "Whispering Tavern"

        # Living World Tick
        tick_resp = client.post(
            f"/api/v2/world-vault/onboarding/world-tick/{world_b.id}",
            json={"time_advance_label": "+1 Day", "active_chat_id": chat_id},
        )
        assert tick_resp.status_code == 200, tick_resp.text
        assert tick_resp.json()["state_snapshot"]["world_clock"]["day"] == 2

        # Commit to World Canon
        canon_resp = client.post(f"/api/v2/world-vault/onboarding/commit-canon/{chat_id}")
        assert canon_resp.status_code == 200, canon_resp.text
        assert canon_resp.json()["lorebook_id"]

        # Compile Chat to Story Chapter
        story_resp = client.post(
            f"/api/v2/world-vault/onboarding/compile-story/{chat_id}",
            json={"title": "Kira in Eldoria"},
        )
        assert story_resp.status_code == 200, story_resp.text
        assert story_resp.json()["story_id"]
        assert story_resp.json()["chapter_id"]
