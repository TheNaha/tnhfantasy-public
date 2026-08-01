from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from datetime import datetime, timezone

from api.deps import get_session
from core.entities import Character

router = APIRouter()

@router.get("/", response_model=List[Character])
def list_characters(session: Session = Depends(get_session)):
    return session.exec(select(Character).order_by(Character.name)).all()

@router.post("/", response_model=Character)
def create_character(character: Character, session: Session = Depends(get_session)):
    character.created_at = datetime.now(timezone.utc)
    character.updated_at = character.created_at
    session.add(character)
    session.commit()
    session.refresh(character)
    return character

@router.get("/{character_id}", response_model=Character)
def get_character(character_id: str, session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return character

@router.put("/{character_id}", response_model=Character)
def update_character(character_id: str, character_update: Character, session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    update_data = character_update.model_dump(exclude_unset=True)
    update_data.pop("id", None)
    
    for key, value in update_data.items():
        setattr(character, key, value)
        
    character.updated_at = datetime.now(timezone.utc)
    session.add(character)
    session.commit()
    session.refresh(character)
    return character

@router.delete("/{character_id}")
def delete_character(character_id: str, session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    
    session.delete(character)
    session.commit()
    return {"message": "Character deleted"}
