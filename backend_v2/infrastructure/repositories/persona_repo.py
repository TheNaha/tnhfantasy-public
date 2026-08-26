from __future__ import annotations

from sqlmodel import Session, select

from core.entities import Persona


class PersonaRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[Persona]:
        return self.session.exec(select(Persona).order_by(Persona.name)).all()

    def get(self, persona_id: str) -> Persona | None:
        return self.session.get(Persona, persona_id)
