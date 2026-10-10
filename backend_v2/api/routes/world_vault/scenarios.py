from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session
from typing import Literal

from api.deps import get_session, get_scenario_repo
from infrastructure.repositories.scenario_repo import ScenarioRepository
from services.reference_cleanup import scrub_entity_references
from core.entities import Scenario, Chat, Story
from core.exceptions import NotFoundError

router = APIRouter()


class ScenarioCreate(BaseModel):
    """Create body for POST /scenarios. See `CharacterCreateRequest`."""

    model_config = {"extra": "forbid"}

    name: str
    description: str | None = None
    prompt_template: str
    default_checkpoint: str | None = None
    default_voice_profile: str | None = None


class ScenarioUpdate(BaseModel):
    """Strict optional-field update model for PUT/PATCH /scenarios/{id}.

    `default_checkpoint` and `default_voice_profile` were missing here even
    though `Scenario` declares them and the Scenarios page renders both in its
    edit form. Pydantic's default `extra='ignore'` dropped them, the route
    returned 200, the UI toasted "Scenario updated", and the values never
    changed — every field in the form after the third was uneditable from the
    moment the scenario was created. `extra="forbid"` so the next missing field
    is a 422 instead of another silent no-op.
    """

    model_config = {"extra": "forbid"}

    name: str | None = None
    description: str | None = None
    prompt_template: str | None = None
    default_checkpoint: str | None = None
    default_voice_profile: str | None = None

@router.get("", response_model=list[Scenario])
def list_scenarios(session: Session = Depends(get_session), scenario_repo: ScenarioRepository = Depends(get_scenario_repo)):
    return scenario_repo.list()

@router.post("", response_model=Scenario)
def create_scenario(payload: ScenarioCreate, session: Session = Depends(get_session), scenario_repo: ScenarioRepository = Depends(get_scenario_repo)):
    scenario = Scenario(**payload.model_dump())
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
    if "default_checkpoint" in update_dict:
        scenario.default_checkpoint = update_dict["default_checkpoint"]
    if "default_voice_profile" in update_dict:
        scenario.default_voice_profile = update_dict["default_voice_profile"]
        
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
    target_type: Literal["chat", "story"]
    target_id: str


def _append_directive(existing: str | None, directive: str | None) -> str | None:
    """Add a scenario directive to a chat's existing append block.

    Re-applying the same scenario is a no-op rather than a duplicate, so a user
    who clicks Apply twice does not pay for the same paragraph twice.
    """
    directive = (directive or "").strip()
    if not directive:
        return existing
    if not existing or not existing.strip():
        return directive
    if directive in existing:
        return existing
    return f"{existing.rstrip()}\n\n{directive}"


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
        # `append_system_prompt`, NOT `system_prompt_override`.
        #
        # The override *replaces* everything character-related:
        # `build_system_prompt_sections` breaks out of the character loop when
        # it is set, and separately gates `mes_example` on its absence. So
        # clicking "Apply" on this page — a button labelled as adding a
        # directive — silently removed the character's description, personality,
        # scenario, system_prompt, append_system_prompt and example dialogue
        # from every subsequent turn of that chat, with nothing shown to the
        # user and no log line. The chat simply started answering out of
        # character.
        #
        # The override is still the right tool for its actual purpose, which is
        # the explicit "Chat Prompt" tab, and its replace-semantics are
        # documented in the builder. What was wrong was this button reaching
        # for it.
        chat.append_system_prompt = _append_directive(chat.append_system_prompt, scenario.prompt_template)
        session.add(chat)
        session.commit()
        session.refresh(chat)
        result["applied_to"] = "chat"
        result["chat_id"] = req.target_id
        result["applied_via"] = "append_system_prompt"
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

    return result
