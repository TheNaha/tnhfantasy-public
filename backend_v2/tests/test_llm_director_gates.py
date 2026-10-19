"""The LLM Studio gate registry is served from the decision schema.

The Studio used to hardcode its own gate list, and four keys had drifted to
aliases the Director never emits. These tests pin the endpoint to
`decision_schema.py` so that drift cannot come back.
"""

from __future__ import annotations

from api.routes.world_vault.llm_config import get_director_gates
from services.decision_schema import (
    GATE_FIELD_MAP,
    IMAGE_TRIGGER_THRESHOLD,
    UPDATER_GATE_KEYS,
    UPDATER_GATE_THRESHOLD,
)


def test_registry_serves_exactly_the_primary_gates():
    data = get_director_gates()
    keys = [gate["key"] for category in data["categories"] for gate in category["gates"]]

    primary = set(UPDATER_GATE_KEYS) - {"gate_world_state", "gate_character_state"}
    assert len(keys) == 16
    assert set(keys) == primary
    assert len(keys) == len(set(keys))


def test_registry_does_not_serve_retired_aliases():
    keys = {
        gate["key"]
        for category in get_director_gates()["categories"]
        for gate in category["gates"]
    }
    for alias in (
        "gate_location",
        "gate_weather",
        "gate_character_activity",
        "gate_quests_and_goals",
    ):
        assert alias not in keys


def test_registry_carries_labels_fields_and_threshold():
    data = get_director_gates()
    assert data["threshold"] == UPDATER_GATE_THRESHOLD
    assert data["image_threshold"] == IMAGE_TRIGGER_THRESHOLD
    assert data["always_allowed_fields"] == ["scene_summary"]

    for category in data["categories"]:
        assert category["title"]
        for gate in category["gates"]:
            assert gate["label"] and gate["label"] != gate["key"]
            assert gate["fields"], f"{gate['key']} authorizes no updater fields"
            assert set(gate["fields"]) <= set(GATE_FIELD_MAP[gate["key"]])

    assert len(data["legacy_gates"]) == 2
