from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import List, Optional
from datetime import datetime, timezone

from api.deps import get_session
from core.entities import Scenario

router = APIRouter()


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    prompt_template: Optional[str] = None

@router.get("/", response_model=List[Scenario])
def list_scenarios(session: Session = Depends(get_session)):
    return session.exec(select(Scenario).order_by(Scenario.name)).all()

@router.post("/", response_model=Scenario)
def create_scenario(scenario: Scenario, session: Session = Depends(get_session)):
    scenario.created_at = datetime.now(timezone.utc)
    scenario.updated_at = scenario.created_at
    session.add(scenario)
    session.commit()
    session.refresh(scenario)
    return scenario

@router.get("/{scenario_id}", response_model=Scenario)
def get_scenario(scenario_id: str, session: Session = Depends(get_session)):
    scenario = session.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario

@router.put("/{scenario_id}", response_model=Scenario)
def update_scenario(scenario_id: str, update_data: ScenarioUpdate, session: Session = Depends(get_session)):
    scenario = session.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    
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
def delete_scenario(scenario_id: str, session: Session = Depends(get_session)):
    scenario = session.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    session.delete(scenario)
    session.commit()
    return {"message": "Scenario deleted"}
