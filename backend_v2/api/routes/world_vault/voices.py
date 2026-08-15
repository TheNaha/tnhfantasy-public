from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_session
from core.entities import VoiceModel
from services.reference_cleanup import scrub_entity_references
from core.exceptions import NotFoundError, ValidationError

router = APIRouter()


class VoiceModelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    type: str | None = None
    voice_profile: str | None = None
    model_path: str | None = None
    language: str | None = None
    preview_text: str | None = None
    character_id: str | None = None


@router.get("")
def list_voices(
    character_id: str | None = None,
    session: Session = Depends(get_session),
):
    query = select(VoiceModel).order_by(VoiceModel.name)
    if character_id is not None:
        query = query.where(VoiceModel.character_id == character_id)
    return session.exec(query).all()


@router.post("")
def create_voice(voice: VoiceModel, session: Session = Depends(get_session)):
    if voice.id is None:
        pass  # Let default_factory handle it
    voice.created_at = datetime.now(timezone.utc)
    voice.updated_at = voice.created_at
    session.add(voice)
    session.commit()
    session.refresh(voice)
    return voice


@router.get("/{voice_id}")
def get_voice(voice_id: str, session: Session = Depends(get_session)):
    voice = session.get(VoiceModel, voice_id)
    if not voice:
        raise NotFoundError("VoiceModel", voice_id)
    return voice


@router.put("/{voice_id}")
def update_voice(voice_id: str, update_data: VoiceModelUpdate, session: Session = Depends(get_session)):
    voice = session.get(VoiceModel, voice_id)
    if not voice:
        raise NotFoundError("VoiceModel", voice_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(voice, key, value)

    voice.updated_at = datetime.now(timezone.utc)
    session.add(voice)
    session.commit()
    session.refresh(voice)
    return voice


@router.patch("/{voice_id}")
def patch_voice(voice_id: str, update_data: VoiceModelUpdate, session: Session = Depends(get_session)):
    voice = session.get(VoiceModel, voice_id)
    if not voice:
        raise NotFoundError("VoiceModel", voice_id)

    update_dict = update_data.model_dump(exclude_unset=True)
    update_dict = {k: v for k, v in update_dict.items() if v is not None}
    for key, value in update_dict.items():
        setattr(voice, key, value)

    voice.updated_at = datetime.now(timezone.utc)
    session.add(voice)
    session.commit()
    session.refresh(voice)
    return voice


@router.delete("/{voice_id}")
def delete_voice(voice_id: str, session: Session = Depends(get_session)):
    voice = session.get(VoiceModel, voice_id)
    if not voice:
        raise NotFoundError("VoiceModel", voice_id)
    scrub_entity_references(session, "voice", voice_id)
    session.delete(voice)
    session.commit()
    return {"message": "Voice model deleted"}


@router.post("/{voice_id}/preview")
def get_voice_preview(voice_id: str, session: Session = Depends(get_session)):
    """Return the preview text for a voice model so the frontend can synthesize it."""
    voice = session.get(VoiceModel, voice_id)
    if not voice:
        raise NotFoundError("VoiceModel", voice_id)
    if not voice.preview_text:
        raise ValidationError(f"Voice model '{voice.name}' has no preview text")
    return {"preview_text": voice.preview_text, "voice_profile": voice.voice_profile, "language": voice.language}
