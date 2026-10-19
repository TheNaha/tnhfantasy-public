"""Tests for AgentPromptVariant CRUD, activation, and reference resolution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from core.entities import AgentProfile, AgentPromptVariant, Character, Chat, Message, MessageRole
from services.agent_variants import resolve_agent
from services.illustrator_service import enqueue_scene_illustration_job


@pytest.fixture
def client(session: Session) -> TestClient:
    from api.main import app
    from api.deps import get_session

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _character_agent(session: Session) -> AgentProfile:
    profile = session.exec(select(AgentProfile).where(AgentProfile.slug == "character")).first()
    assert profile is not None
    return profile


def _create_variant(client: TestClient, agent_id: str, slug: str, *, activate: bool = False):
    return client.post(
        f"/api/v2/agents/{agent_id}/variants",
        json={
            "slug": slug,
            "name": slug.replace("_", " ").title(),
            "description": "A test prompt variant.",
            "system_prompt_template": "You are {{char}}, speaking in a register unique to this variant.",
            "temperature": 0.55,
            "activate": activate,
        },
    )


def test_variant_crud_and_activation(client: TestClient, session: Session):
    profile = _character_agent(session)

    first = _create_variant(client, profile.id, "concise", activate=True)
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["agent_id"] == profile.id
    assert first_data["is_active"] is True

    second = _create_variant(client, profile.id, "florid", activate=True)
    assert second.status_code == 200, second.text
    second_data = second.json()
    assert second_data["is_active"] is True

    session.expire_all()
    listed = client.get(f"/api/v2/agents/{profile.id}/variants").json()
    by_slug = {v["slug"]: v for v in listed}
    assert by_slug["concise"]["is_active"] is False
    assert by_slug["florid"]["is_active"] is True

    updated = client.put(
        f"/api/v2/agents/{profile.id}/variants/{second_data['id']}",
        json={"system_prompt_template": "Updated {{char}} prose.", "top_p": 0.8},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["system_prompt_template"] == "Updated {{char}} prose."
    assert updated.json()["top_p"] == 0.8

    # The active variant overrides the profile template during resolution.
    session.expire_all()
    resolved = resolve_agent(session, "character")
    assert resolved is not None
    assert resolved.variant_slug == "florid"
    assert resolved.prompt_template == "Updated {{char}} prose."
    samplers = resolved.sampler_overrides()
    assert samplers["temperature"] == 0.55
    assert samplers["top_p"] == 0.8

    deleted = client.delete(f"/api/v2/agents/{profile.id}/variants/{second_data['id']}")
    assert deleted.status_code == 200
    session.expire_all()
    assert resolve_agent(session, "character").variant is None


def test_builtin_profile_is_not_mutated_by_a_variant(client: TestClient, session: Session):
    profile = _character_agent(session)
    original = profile.system_prompt_template

    created = _create_variant(client, profile.id, "noir_voice", activate=True)
    assert created.status_code == 200, created.text

    session.expire_all()
    session.refresh(profile)
    assert profile.system_prompt_template == original


def test_variant_prefix_reference_resolves(client: TestClient, session: Session):
    profile = _character_agent(session)
    created = _create_variant(client, profile.id, "bardic", activate=False)
    assert created.status_code == 200, created.text

    # Inactive variants still resolve when addressed explicitly.
    resolved = resolve_agent(session, "variant:bardic")
    assert resolved is not None
    assert resolved.profile.id == profile.id
    assert resolved.variant_slug == "bardic"
    assert resolve_agent(session, "variant:missing") is None


def test_variant_slug_is_globally_unique(client: TestClient, session: Session):
    character = _character_agent(session)
    narrator = session.exec(select(AgentProfile).where(AgentProfile.slug == "narrator")).first()
    assert narrator is not None

    assert _create_variant(client, character.id, "shared_voice").status_code == 200
    duplicate = _create_variant(client, narrator.id, "shared_voice")
    assert duplicate.status_code == 400
    assert "already exists" in duplicate.text


def test_deleting_an_agent_removes_its_variants(client: TestClient, session: Session):
    created_agent = client.post(
        "/api/v2/agents",
        json={
            "slug": "variant_owner",
            "name": "Variant Owner",
            "agent_type": "specialist",
            "description": "Owns variants that must be removed with it.",
            "system_prompt_template": "You are a temporary test agent.",
        },
    )
    assert created_agent.status_code == 200, created_agent.text
    agent_id = created_agent.json()["id"]

    assert _create_variant(client, agent_id, "owner_voice").status_code == 200
    session.expire_all()
    assert session.exec(
        select(AgentPromptVariant).where(AgentPromptVariant.agent_id == agent_id)
    ).first() is not None

    deleted = client.delete(f"/api/v2/agents/{agent_id}")
    assert deleted.status_code == 200
    session.expire_all()
    assert session.exec(
        select(AgentPromptVariant).where(AgentPromptVariant.agent_id == agent_id)
    ).first() is None


def test_simulation_can_preview_a_variant(client: TestClient, session: Session):
    profile = _character_agent(session)
    created = _create_variant(client, profile.id, "cinematic", activate=False)
    assert created.status_code == 200, created.text

    response = client.post(
        "/api/v2/agents/simulate",
        json={
            "prompt": "The storm breaks over the citadel as I raise my blade.",
            "stage": "triage",
            "character_name": "Seraphina",
            "user_name": "Player",
            "variant_slug": "cinematic",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "agent_profile" in data
    assert data["agent_profile"]["variant_slug"] == "cinematic"
    assert "register unique" in data["agent_profile"]["rendered_prompt_preview"]


class _CapturingJobService:
    def __init__(self) -> None:
        self.created: dict | None = None

    async def create_job(self, task_type, workflow, metadata):
        self.created = {"task_type": task_type, "workflow": workflow, "metadata": metadata}
        return SimpleNamespace(id="illustrator-prompt-job")


async def test_illustrator_agent_uses_active_variant_and_tools(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    profile = session.exec(
        select(AgentProfile).where(AgentProfile.slug == "illustrator")
    ).first()
    if profile is None:
        profile = AgentProfile(
            id="test-illustrator",
            slug="illustrator",
            name="Illustrator Agent",
            agent_type="multimodal",
            description="Synthesizes visual moments into image prompts.",
            system_prompt_template="You are an expert prompt artist.",
            model_target="util",
            enabled=True,
        )
        session.add(profile)
        session.commit()

    session.add(AgentPromptVariant(
        agent_id=profile.id,
        slug="painterly_illustrator",
        name="Painterly Illustrator",
        description="Variant used to pin the illustrator prompt.",
        system_prompt_template="Paint {{char}} in a painterly style.",
        is_active=True,
        temperature=0.4,
    ))
    character = Character(
        id="char-illustrated",
        name="Seraphina",
        description="A silver-haired knight.",
        visual_tags=["silver hair", "blue eyes"],
        checkpoint="artemis.safetensors",
    )
    chat = Chat(
        id="chat-illustrated",
        character_id=character.id,
        persona_name="Player",
        story_location="Obsidian Citadel",
        story_time="Dusk",
        state_snapshot={"character_outfit": "battle-scarred cuirass", "weather": "storm"},
    )
    session.add(character)
    session.add(chat)
    session.add(Message(
        chat_id=chat.id,
        role=MessageRole.USER,
        content="The storm breaks as I raise my blade.",
    ))
    session.commit()

    from services.job_queue import queue_manager

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(queue_manager, "enqueue", _noop)
    job_service = _CapturingJobService()

    job_id = await enqueue_scene_illustration_job(
        session,
        job_service=job_service,
        chat_id=chat.id,
        character_id=character.id,
        branch_id="branch-1",
        source_job_id="reply-job",
    )

    assert job_id == "illustrator-prompt-job"
    created = job_service.created
    assert created["task_type"] == "llm"

    workflow = created["workflow"]
    assert workflow["type"] == "illustrator"
    assert workflow["background"] is True
    assert workflow["temperature"] == 0.4
    assert workflow["messages"][0]["content"] == "Paint Seraphina in a painterly style."
    assert "silver hair" in workflow["messages"][1]["content"]
    assert "Obsidian Citadel" in workflow["messages"][1]["content"]
    assert "storm breaks" in workflow["messages"][1]["content"]

    metadata = created["metadata"]
    assert metadata["source"] == "scene_prompt"
    assert metadata["parent_job_id"] == "reply-job"
    assert metadata["agent_slug"] == "illustrator"
    assert metadata["agent_variant_slug"] == "painterly_illustrator"
    assert metadata["branch_id"] == "branch-1"
