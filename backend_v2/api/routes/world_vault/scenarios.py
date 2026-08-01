from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from datetime import datetime, timezone

from api.deps import get_session
from core.entities import Scenario

router = APIRouter()

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
def update_scenario(scenario_id: str, update_data: dict, session: Session = Depends(get_session)):
    scenario = session.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    if "name" in update_data:
        scenario.name = update_data["name"]
    if "description" in update_data:
        scenario.description = update_data["description"]
    if "prompt_template" in update_data:
        scenario.prompt_template = update_data["prompt_template"]
        
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
