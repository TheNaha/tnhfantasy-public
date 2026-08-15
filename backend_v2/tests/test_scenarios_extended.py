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
