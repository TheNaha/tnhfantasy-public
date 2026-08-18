from __future__ import annotations

from sqlmodel import Session, select

from core.entities import Scenario


class ScenarioRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[Scenario]:
        return self.session.exec(select(Scenario).order_by(Scenario.name)).all()

    def get(self, scenario_id: str) -> Scenario | None:
        return self.session.get(Scenario, scenario_id)
