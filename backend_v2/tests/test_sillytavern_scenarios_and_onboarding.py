"""Tests for SillyTavern Scenario Mapping, Section Generators, Field Enrichment, Locked Statekeeper Fields, and Chained Story Ingestion."""


from services.world_onboarding_service import _build_scenarios_from_greetings, _derive_scenario_title


def test_derive_scenario_title_and_build_scenarios():
    first_mes = "The forge, labelled 'The Pointed Anvil', was suffocatingly hot as Pyrene hammered the molten steel."
    title = _derive_scenario_title(first_mes, 0, "The Pointed Anvil Forge")
    assert "Pointed Anvil" in title

    alt1 = "Outside the tavern, heavy rain poured down as travelers sought shelter."
    title_alt = _derive_scenario_title(alt1, 1, "Drunken Dragon Tavern")
    assert len(title_alt) > 3

    scenarios = _build_scenarios_from_greetings(
        char_name="Pyrene",
        scenario_text="Pyrene works as the master blacksmith.",
        first_mes=first_mes,
        alternate_greetings=[alt1, "In the quiet library, ancient books lined the mahogany shelves."],
        default_location="Blacksmith Guild",
        default_time="Midday",
    )
    assert len(scenarios) == 3
    assert scenarios[0]["is_primary"] is True
    assert scenarios[0]["id"] == "scenario_0"
    assert scenarios[1]["is_primary"] is False
    assert scenarios[1]["id"] == "scenario_1"
    assert "Pointed Anvil" in scenarios[0]["title"]


def test_extract_scenarios_endpoint(client):
    payload = {
        "char_name": "Isekai Summoner",
        "scenario_text": "Summoned to a fantasy world.",
        "first_mes": "*A dazzling runic circle glows on the cold stone floor of the Royal Sanctum.*",
        "alternate_greetings": [
            "*You awaken in a muddy ditch after colliding with Truck-kun on your way home.*",
            "*Thunder roars over the stormy battlefield as the portal deposits you in the frontlines.*",
        ],
        "default_location": "Royal Sanctum",
        "default_time": "Midnight",
        "use_llm": False,
    }
    resp = client.post("/api/v2/world-vault/onboarding/extract-scenarios", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "scenarios" in data
    assert data["total_count"] == 3
    assert data["scenarios"][0]["location_name"] == "Royal Sanctum"
    assert data["scenarios"][0]["is_primary"] is True


def test_extract_visual_tags_endpoint(client):
    payload = {
        "char_name": "Seraphina",
        "description": "Seraphina has long silver hair, glowing violet eyes, and wears ornate obsidian plate armor with a crimson cape.",
        "personality": "Stoic, dutiful, and honorable knight.",
        "existing_tags": ["knight", "fantasy"],
        "use_vision": False,
    }
    resp = client.post("/api/v2/world-vault/onboarding/extract-visual-tags", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "visual_tags" in data
    assert "character_outfit" in data
    assert "wardrobe_presets" in data
    assert len(data["wardrobe_presets"]) >= 1


def test_extract_statekeeper_preserves_locked_fields(client):
    current_state = {
        "character_mood": "Absolute Wrath",
        "scene_tension": 4.8,
        "current_activity": "Forging the Excalibur Blade",
        "character_outfit": "Molten Leather Apron",
    }
    locked_fields = ["character_mood", "scene_tension"]

    payload = {
        "char_name": "Pyrene",
        "description": "Pyrene is a cheerful dwarven blacksmith.",
        "personality": "Friendly, boisterous, loves ale.",
        "scenario_text": "Meeting at the local tavern.",
        "first_mes": "Pyrene smiles cheerfully and hands you a mug of ale.",
        "default_location": "Tavern",
        "default_time": "Evening",
        "locked_fields": locked_fields,
        "current_state": current_state,
    }

    resp = client.post("/api/v2/world-vault/onboarding/extract-statekeeper", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    snapshot = data["initial_state_snapshot"]

    # Mood and Tension MUST be preserved from locked state
    assert snapshot["character_mood"] == "Absolute Wrath"
    assert snapshot["scene_tension"] == 4.8
    assert "character_mood" in data["locked_fields_preserved"]
    assert "scene_tension" in data["locked_fields_preserved"]


def test_extract_world_lore_endpoint(client):
    payload = {
        "char_name": "Elira",
        "description": "Archmage of the Silver Spire.",
        "scenario_text": "In the arcane academy atop Mount Celestia.",
        "first_mes": "Elira adjusts her crystal spectacles as she reviews the astral charts.",
        "character_book": {
            "name": "Celestia Lorebook",
            "entries": [
                {
                    "keys": ["astral", "magic"],
                    "content": "Astral magic draws from celestial alignments.",
                    "enabled": True,
                }
            ],
        },
    }
    resp = client.post("/api/v2/world-vault/onboarding/extract-world-lore", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["world_name"] == "Celestia Lorebook"
    assert len(data["locations"]) >= 1
    assert data["lorebook"]["create"] is True
    assert len(data["lorebook"]["entries"]) == 1


def test_enrich_field_endpoint(client):
    payload = {
        "field_name": "description",
        "current_value": "A master swordsman with a dark past.",
        "char_name": "Vane",
        "instruction": "Enrich with atmosphere and sensory details.",
    }
    resp = client.post("/api/v2/world-vault/onboarding/enrich-field", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["field_name"] == "description"
    assert len(data["enriched_value"]) > 0


def test_ingest_story_chained_endpoint(client):
    # Construct a multi-paragraph text with enough words to trigger chunking if chunk_size is small
    paragraphs = [
        "Chapter I: The Arrival. In the year of the eclipse, Captain Roland stepped off the airship onto the bustling docks of Zephyria. The sky was thick with steam and copper gears turned in every clocktower. Roland checked his brass compass and made his way through the crowded alleys.",
        "Roland said 'We must reach the Grand Conservatory before the clock strikes midnight.' His companion Lyra drew her twin daggers, scanning the shadows for mechanical sentinels.",
        "Deep in the lower districts at the Sunken Factory, toxic runoff pooled beneath rusty grates. Lyra whispered that the Resistance had established a forward safehouse near the boiler room.",
        "As midnight approached, the clocktower chimed across Zephyria. A legion of automaton guards marched into the square, their optical sensors flashing crimson.",
    ]
    raw_text = "\n\n".join(paragraphs * 8)  # Expand to ~800 words

    payload = {
        "raw_text": raw_text,
        "title": "Chronicles of Zephyria",
        "chunk_size_words": 150,  # Small chunk size to verify chained multi-chunk processing
        "overlap_words": 30,
    }
    resp = client.post("/api/v2/world-vault/onboarding/ingest-story-chained", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_type"] == "chained_long_document"
    assert data["chunk_count"] > 1
    assert len(data["story_chapters"]) == data["chunk_count"]
    assert len(data["scenarios"]) == data["chunk_count"]
    assert data["world"]["name"] is not None
    assert len(data["characters"]) >= 1
