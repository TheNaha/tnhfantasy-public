from __future__ import annotations

from sqlmodel import Session, select

from core.entities import VoiceModel


class VoiceModelRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self, character_id: str | None = None) -> list[VoiceModel]:
        stmt = select(VoiceModel)
        if character_id is not None:
            stmt = stmt.where(VoiceModel.character_id == character_id)
        return self.session.exec(stmt.order_by(VoiceModel.name)).all()

    def get(self, voice_id: str) -> VoiceModel | None:
        return self.session.get(VoiceModel, voice_id)
