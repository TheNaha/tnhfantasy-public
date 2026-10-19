"""Tests for AgentProfile CRUD and interactive workflow simulation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from core.entities import AgentProfile


@pytest.fixture
def client(session: Session) -> TestClient:
    from api.main import app
    from api.deps import get_session

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_list_builtin_agents(client: TestClient, session: Session):
    response = client.get("/api/v2/agents")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 5
    slugs = {a["slug"] for a in data}
    assert "character" in slugs
    assert "narrator" in slugs
    assert "illustrator" in slugs
    assert "updater" in slugs
    assert "continuation" in slugs


def test_create_and_delete_custom_agent(client: TestClient, session: Session):
    # 1. Create custom agent
    payload = {
        "slug": "battle_tactician",
        "name": "Battle Tactician",
        "agent_type": "tactician",
        "description": "Specialized combat analyst directing high-stakes tactical maneuvers.",
        "system_prompt_template": "You are {character_name}'s tactical advisor in {story_location}.",
        "model_target": "rp",
        "enabled": True,
        "temperature": 0.4,
    }
    create_resp = client.post("/api/v2/agents", json=payload)
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["slug"] == "battle_tactician"
    assert created["is_builtin"] is False
    agent_id = created["id"]

    # 2. Update custom agent
    update_resp = client.put(f"/api/v2/agents/{agent_id}", json={"temperature": 0.35, "description": "Updated tactical advisor."})
    assert update_resp.status_code == 200
    assert update_resp.json()["temperature"] == 0.35
    assert update_resp.json()["description"] == "Updated tactical advisor."

    # 3. Simulate triage using the custom agent
    sim_resp = client.post(
        "/api/v2/agents/simulate",
        json={
            "prompt": "Enemy flanked us on the left rampart, need cover fire!",
            "stage": "triage",
            "character_name": "Seraphina",
            "user_name": "Commander",
            "location": "The Ramparts",
            "time": "Dusk",
        },
    )
    assert sim_resp.status_code == 200
    sim_data = sim_resp.json()
    assert "triage" in sim_data
    assert sim_data["triage"]["workflow_stage"] == "triage"

    # 4. Built-in deletion is blocked
    builtin_agent = session.exec(select(AgentProfile).where(AgentProfile.slug == "character")).first()
    assert builtin_agent is not None
    del_builtin = client.delete(f"/api/v2/agents/{builtin_agent.id}")
    assert del_builtin.status_code == 400

    # 5. Delete custom agent
    del_resp = client.delete(f"/api/v2/agents/{agent_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True
