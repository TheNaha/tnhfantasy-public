from __future__ import annotations

from sqlmodel import Session, select

from core.entities import World


class WorldRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[World]:
        return self.session.exec(select(World).order_by(World.name)).all()

    def get(self, world_id: str) -> World | None:
        return self.session.get(World, world_id)
