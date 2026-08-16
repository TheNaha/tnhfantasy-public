from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_session, get_scenario_repo
from infrastructure.repositories.scenario_repo import ScenarioRepository
from services.reference_cleanup import scrub_entity_references
from core.entities import Scenario, Chat, Story
from core.exceptions import NotFoundError, ValidationError

router = APIRouter()


class ScenarioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    prompt_template: str | None = None

@router.get("", response_model=list[Scenario])
def list_scenarios(session: Session = Depends(get_session), scenario_repo: ScenarioRepository = Depends(get_scenario_repo)):
    return scenario_repo.list()

@router.post("", response_model=Scenario)
def create_scenario(scenario: Scenario, session: Session = Depends(get_session), scenario_repo: ScenarioRepository = Depends(get_scenario_repo)):
    scenario.created_at = datetime.now(timezone.utc)
    scenario.updated_at = scenario.created_at
    session.add(scenario)
    session.commit()
    session.refresh(scenario)
    return scenario

@router.get("/{scenario_id}", response_model=Scenario)
def get_scenario(scenario_id: str, session: Session = Depends(get_session), scenario_repo: ScenarioRepository = Depends(get_scenario_repo)):
    scenario = scenario_repo.get(scenario_id)
    if not scenario:
        raise NotFoundError("Scenario", scenario_id)
    return scenario

@router.put("/{scenario_id}", response_model=Scenario)
def update_scenario(scenario_id: str, update_data: ScenarioUpdate, session: Session = Depends(get_session), scenario_repo: ScenarioRepository = Depends(get_scenario_repo)):
    scenario = scenario_repo.get(scenario_id)
    if not scenario:
        raise NotFoundError("Scenario", scenario_id)
    
    update_dict = update_data.model_dump(exclude_unset=True)
    if "name" in update_dict:
        scenario.name = update_dict["name"]
    if "description" in update_dict:
        scenario.description = update_dict["description"]
    if "prompt_template" in update_dict:
        scenario.prompt_template = update_dict["prompt_template"]
        
    scenario.updated_at = datetime.now(timezone.utc)
    session.add(scenario)
    session.commit()
    session.refresh(scenario)
    return scenario

@router.delete("/{scenario_id}")
def delete_scenario(scenario_id: str, session: Session = Depends(get_session), scenario_repo: ScenarioRepository = Depends(get_scenario_repo)):
    scenario = scenario_repo.get(scenario_id)
    if not scenario:
        raise NotFoundError("Scenario", scenario_id)
    
    scrub_entity_references(session, "scenario", scenario_id)
    session.delete(scenario)
    session.commit()
    return {"message": "Scenario deleted"}


class ApplyScenarioRequest(BaseModel):
    target_type: str  # "chat" or "story"
    target_id: str


@router.post("/{scenario_id}/apply")
def apply_scenario(scenario_id: str, req: ApplyScenarioRequest, session: Session = Depends(get_session), scenario_repo: ScenarioRepository = Depends(get_scenario_repo)):
    """Apply a scenario's prompt_template and defaults to a chat or story."""
    scenario = scenario_repo.get(scenario_id)
    if not scenario:
        raise NotFoundError("Scenario", scenario_id)

    result = {"scenario_id": scenario_id, "scenario_name": scenario.name}

    if req.target_type == "chat":
        chat = session.get(Chat, req.target_id)
        if not chat:
            raise NotFoundError("Chat", req.target_id)
        # Apply the prompt template as a system prompt override
        chat.system_prompt_override = scenario.prompt_template
        session.add(chat)
        session.commit()
        session.refresh(chat)
        result["applied_to"] = "chat"
        result["chat_id"] = req.target_id
    elif req.target_type == "story":
        story = session.get(Story, req.target_id)
        if not story:
            raise NotFoundError("Story", req.target_id)
        story.scenario_id = scenario_id
        session.add(story)
        session.commit()
        session.refresh(story)
        result["applied_to"] = "story"
        result["story_id"] = req.target_id
    else:
        raise ValidationError(f"target_type must be 'chat' or 'story', got '{req.target_type}'")

    return result
