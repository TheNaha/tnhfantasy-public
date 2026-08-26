from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlmodel import Session

from api.deps import get_session, get_persona_repo
from core.entities import Persona
from core.exceptions import NotFoundError, ValidationError
from infrastructure.repositories.persona_repo import PersonaRepository
from services.reference_cleanup import scrub_entity_references

router = APIRouter()


class PersonaUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Persona name cannot be blank")
        return v


@router.get("", response_model=list[Persona])
def list_personas(persona_repo: PersonaRepository = Depends(get_persona_repo)):
    return persona_repo.list()


@router.post("", response_model=Persona)
def create_persona(
    persona: Persona,
    session: Session = Depends(get_session),
    persona_repo: PersonaRepository = Depends(get_persona_repo),
):
    if not (persona.name or "").strip():
        raise ValidationError("Persona name is required")
    persona.name = persona.name.strip()
    now = datetime.now(timezone.utc)
    persona.created_at = now
    persona.updated_at = now
    session.add(persona)
    session.commit()
    session.refresh(persona)
    return persona


@router.get("/{persona_id}", response_model=Persona)
def get_persona(
    persona_id: str,
    persona_repo: PersonaRepository = Depends(get_persona_repo),
):
    persona = persona_repo.get(persona_id)
    if not persona:
        raise NotFoundError("Persona", persona_id)
    return persona


@router.put("/{persona_id}", response_model=Persona)
def update_persona(
    persona_id: str,
    update_data: PersonaUpdate,
    session: Session = Depends(get_session),
    persona_repo: PersonaRepository = Depends(get_persona_repo),
):
    persona = persona_repo.get(persona_id)
    if not persona:
        raise NotFoundError("Persona", persona_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    for field in ("name", "description"):
        if field in update_dict:
            setattr(persona, field, update_dict[field].strip() if field == "name" else update_dict[field])

    persona.updated_at = datetime.now(timezone.utc)
    session.add(persona)
    session.commit()
    session.refresh(persona)
    return persona


@router.delete("/{persona_id}")
def delete_persona(
    persona_id: str,
    session: Session = Depends(get_session),
    persona_repo: PersonaRepository = Depends(get_persona_repo),
):
    persona = persona_repo.get(persona_id)
    if not persona:
        raise NotFoundError("Persona", persona_id)

    # Chats referencing this persona keep their per-chat strings; the link is dropped.
    scrub_entity_references(session, "persona", persona_id)
    session.delete(persona)
    session.commit()
    return {"message": "Persona deleted"}
