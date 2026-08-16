from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session, select

from core.entities import Scenario


class ScenarioRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[Scenario]:
        return self.session.exec(select(Scenario).order_by(Scenario.name)).all()

    def get(self, scenario_id: str) -> Scenario | None:
        return self.session.get(Scenario, scenario_id)

    def search(self, query: str, limit: int = 10) -> list[Scenario]:
        stmt = select(Scenario).where(
            text("lower(name) LIKE :q")
        ).order_by(Scenario.name).limit(limit)
        return self.session.exec(stmt, {"q": f"%{query.lower()}%"}).all()
