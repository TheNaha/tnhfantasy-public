"""Tests for extended Scenario endpoints (apply_scenario)."""
import pytest

from core.entities import Scenario, Chat, Story


@pytest.fixture
def scenario(session):
    scen = Scenario(
        name="Fantasy Tavern",
        prompt_template="You are in a bustling tavern.",
        target_type="chat",
    )
    session.add(scen)
    session.commit()
    session.refresh(scen)
    return scen


@pytest.fixture
def chat(session):
    chat = Chat(title="ApplyScenarioTest")
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat


@pytest.fixture
def story(session):
    story = Story(title="ApplyScenarioStory")
    session.add(story)
    session.commit()
    session.refresh(story)
    return story


def test_apply_scenario_to_chat(client, session, scenario, chat):
    response = client.post(f"/api/v2/scenarios/{scenario.id}/apply", json={
        "target_type": "chat",
        "target_id": chat.id,
    })
    assert response.status_code == 200
    data = response.json()
    assert data.get("applied_to") == "chat"


def test_apply_scenario_to_story(client, session, scenario, story):
    response = client.post(f"/api/v2/scenarios/{scenario.id}/apply", json={
        "target_type": "story",
        "target_id": story.id,
    })
    assert response.status_code == 200
    data = response.json()
    assert data.get("applied_to") == "story"


def test_apply_scenario_not_found(client):
    response = client.post("/api/v2/scenarios/nonexistent/apply", json={
        "target_type": "chat",
        "target_id": "some-id",
    })
    assert response.status_code == 404


def test_apply_scenario_invalid_target(client, session, scenario):
    response = client.post(f"/api/v2/scenarios/{scenario.id}/apply", json={
        "target_type": "chat",
        "target_id": "nonexistent-target",
    })
    assert response.status_code == 404


def test_update_scenario_persists_checkpoint_and_voice(client, session, scenario):
    """PUT /scenarios/{id} must persist every field it accepts.

    `ScenarioUpdate` declares `default_checkpoint` and `default_voice_profile`
    and the handler applied only name/description/prompt_template, so a client
    that sent the other two got a 200, a success toast, and no change — the
    exact silent no-op the model's own docstring claims is impossible.
    """
    response = client.put(
        f"/api/v2/scenarios/{scenario.id}",
        json={
            "name": "Renamed Tavern",
            "default_checkpoint": "sdXL_v2.safetensors",
            "default_voice_profile": "warm-narrator",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Tavern"
    assert body["default_checkpoint"] == "sdXL_v2.safetensors"
    assert body["default_voice_profile"] == "warm-narrator"

    # Read back through the API, not the fixture object.
    reread = client.get(f"/api/v2/scenarios/{scenario.id}")
    assert reread.status_code == 200
    assert reread.json()["default_checkpoint"] == "sdXL_v2.safetensors"
    assert reread.json()["default_voice_profile"] == "warm-narrator"


def test_update_scenario_can_clear_optional_fields(client, session, scenario):
    """A null leaf unsets the field rather than being ignored."""
    client.put(
        f"/api/v2/scenarios/{scenario.id}",
        json={"default_checkpoint": "a.safetensors"},
    )
    response = client.put(
        f"/api/v2/scenarios/{scenario.id}",
        json={"default_checkpoint": None},
    )
    assert response.status_code == 200
    assert response.json()["default_checkpoint"] is None
