from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import (
    get_job_service,
    get_queue_manager,
    get_session,
    get_voice_model_repo,
)
from infrastructure.repositories.voice_model_repo import VoiceModelRepository
from core.entities import VoiceModel
from core.exceptions import NotFoundError, ValidationError
from services.job_service import JobService
from services.job_queue import QueueManager
from services.reference_cleanup import scrub_entity_references

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
    session: Session = Depends(get_session), voice_model_repo: VoiceModelRepository = Depends(get_voice_model_repo), ):
    query = select(VoiceModel).order_by(VoiceModel.name)
    if character_id is not None:
        query = query.where(VoiceModel.character_id == character_id)
    return session.exec(query).all()


@router.post("")
def create_voice(voice: VoiceModel, session: Session = Depends(get_session), voice_model_repo: VoiceModelRepository = Depends(get_voice_model_repo)):
    voice.created_at = datetime.now(timezone.utc)
    voice.updated_at = voice.created_at
    session.add(voice)
    session.commit()
    session.refresh(voice)
    return voice


@router.get("/{voice_id}")
def get_voice(voice_id: str, session: Session = Depends(get_session), voice_model_repo: VoiceModelRepository = Depends(get_voice_model_repo)):
    voice = voice_model_repo.get(voice_id)
    if not voice:
        raise NotFoundError("VoiceModel", voice_id)
    return voice


@router.put("/{voice_id}")
def update_voice(voice_id: str, update_data: VoiceModelUpdate, session: Session = Depends(get_session), voice_model_repo: VoiceModelRepository = Depends(get_voice_model_repo)):
    voice = voice_model_repo.get(voice_id)
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
def patch_voice(voice_id: str, update_data: VoiceModelUpdate, session: Session = Depends(get_session), voice_model_repo: VoiceModelRepository = Depends(get_voice_model_repo)):
    voice = voice_model_repo.get(voice_id)
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
def delete_voice(voice_id: str, session: Session = Depends(get_session), voice_model_repo: VoiceModelRepository = Depends(get_voice_model_repo)):
    voice = voice_model_repo.get(voice_id)
    if not voice:
        raise NotFoundError("VoiceModel", voice_id)
    scrub_entity_references(session, "voice", voice_id)
    session.delete(voice)
    session.commit()
    return {"message": "Voice model deleted"}


@router.post("/{voice_id}/preview")
async def get_voice_preview(
    voice_id: str,
    session: Session = Depends(get_session),
    voice_model_repo: VoiceModelRepository = Depends(get_voice_model_repo),
    job_service: JobService = Depends(get_job_service),
    queue_manager: QueueManager = Depends(get_queue_manager),
):
    """Queue a real TTS job that synthesizes the voice model's preview text."""
    from core.workflow_builder import build_tts_workflow

    voice = voice_model_repo.get(voice_id)
    if not voice:
        raise NotFoundError("VoiceModel", voice_id)
    if not voice.preview_text:
        raise ValidationError(f"Voice model '{voice.name}' has no preview text")

    workflow, metadata = build_tts_workflow(
        text=voice.preview_text,
        voice_profile=voice.voice_profile,
        voice_model_id=None,
        language=voice.language,
        chat_id=None,
        character_id=voice.character_id,
        extra_metadata={
            "type": "voice_preview",
            "voice_id": voice_id,
        },
    )

    job = await job_service.create_job(
        task_type="image",  # TTS runs on the image_worker adapter
        workflow=workflow,
        metadata=metadata,
    )
    await queue_manager.enqueue(job.id, task_type="image")

    return {"voice_id": voice.id, "job_id": job.id}
