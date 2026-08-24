from __future__ import annotations

from sqlmodel import Session, select

from core.entities import Campaign


class CampaignRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[Campaign]:
        return self.session.exec(select(Campaign).order_by(Campaign.name)).all()

    def get(self, campaign_id: str) -> Campaign | None:
        return self.session.get(Campaign, campaign_id)
