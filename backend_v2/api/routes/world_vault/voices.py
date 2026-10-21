from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import (
    get_session,
    get_voice_model_repo,
)
from infrastructure.repositories.voice_model_repo import VoiceModelRepository
from core.entities import VoiceModel
from core.exceptions import NotFoundError, ValidationError
from services.job_submission_service import submit_tts_job
from services.reference_cleanup import scrub_entity_references
from services.world_ownership import apply_world_id, require_world

router = APIRouter()

# The line a designed voice is demonstrated on. Deliberately neutral and
# declarative: a greeting reads as a greeting whatever the voice, so a bad voice is
# obvious rather than hidden behind an emotional passage.
DEFAULT_VOICE_SAMPLE_TEXT = (
    "The tide is out, and the harbour bell has not rung since spring."
)


class VoiceModelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    type: str | None = None
    voice_profile: str | None = None
    model_path: str | None = None
    language: str | None = None
    preview_text: str | None = None
    character_id: str | None = None
    # Which World this entity belongs to. Ownership of record lives on the
    # member, not in an array on the `worlds` row — see `services/
    # world_ownership.py`. Absent means "leave alone"; an explicit null detaches.
    world_id: str | None = None


@router.get("")
def list_voices(
    character_id: str | None = None,
    session: Session = Depends(get_session), voice_model_repo: VoiceModelRepository = Depends(get_voice_model_repo), ):
    query = select(VoiceModel).order_by(VoiceModel.name)
    if character_id is not None:
        query = query.where(VoiceModel.character_id == character_id)
    return session.exec(query).all()


class VoiceModelCreate(BaseModel):
    """Create body for POST /voices. See `CharacterCreateRequest`.

    `preview_path` is server-owned: it is written by the preview TTS job that
    completes asynchronously, so accepting it here would let a client point the
    player at a file that does not exist.
    """

    model_config = {"extra": "forbid"}

    name: str
    description: str | None = None
    type: str = "xtts"
    voice_profile: str | None = None
    model_path: str | None = None
    language: str | None = None
    preview_text: str | None = None
    character_id: str | None = None
    # Which World this entity belongs to. Ownership of record lives on the
    # member, not in an array on the `worlds` row — see `services/
    # world_ownership.py`. Absent means "leave alone"; an explicit null detaches.
    world_id: str | None = None


@router.post("")
def create_voice(payload: VoiceModelCreate, session: Session = Depends(get_session), voice_model_repo: VoiceModelRepository = Depends(get_voice_model_repo)):
    require_world(session, payload.world_id)
    voice = VoiceModel(**payload.model_dump())
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
    apply_world_id(session, voice, update_dict)
    update_dict.pop("world_id", None)
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
    apply_world_id(session, voice, update_dict)
    update_dict.pop("world_id", None)
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
):
    """Queue a real TTS job that synthesizes the voice model's preview text.

    Was submitting `task_type="image"` with the comment "TTS runs on the
    image_worker adapter". That was true of the code path and false of the
    capability: no provider image had a text-to-speech node, so the job was
    routed to a worker that could not build its graph. Now `task_type="tts"`,
    which the load balancer only offers to providers whose `capabilities`
    include it, and built from `services.tts_workflow_builder`.
    """
    from services.tts_workflow_builder import (
        _require_tts_capable,
        build_voice_speak_workflow,
    )

    _require_tts_capable(session)

    voice = voice_model_repo.get(voice_id)
    if not voice:
        raise NotFoundError("VoiceModel", voice_id)
    if not voice.preview_text:
        raise ValidationError(f"Voice model '{voice.name}' has no preview text")

    workflow, metadata = build_voice_speak_workflow(
        voice.preview_text,
        voice_profile=voice.voice_profile,
        language=voice.language,
        filename_prefix=f"voice_preview/{voice_id}",
        extra_metadata={"type": "voice_preview", "voice_id": voice_id},
    )
    if voice.character_id:
        metadata["character_id"] = voice.character_id

    job = await submit_tts_job(
        session,
        workflow,
        metadata,
    )

    return {"voice_id": voice.id, "job_id": job.id}



# ---------------------------------------------------------------------------
# Voice design
# ---------------------------------------------------------------------------
# The three paths, in the order a user would reach for them:
#
#   design  — describe the voice in words, get a reference. Needs nothing.
#   preset  — pick one of the model's own timbres. Needs nothing.
#   clone   — upload a reference you already have.
#
# `design` is the one that matters. The blocker was never "the model is bad" but
# "nobody here has a reference clip and no experience making one" — so the
# reference is GENERATED, by describing the voice, and then spoken in to become
# the character's own reference. Everything downstream then works on audio this
# model produced, which is in-distribution for cloning and needs no external
# asset.


class VoiceSpec(BaseModel):
    """One voice to design in a batch."""

    name: str
    description: str
    character_id: str | None = None
    language: str | None = None
    # Overrides the batch's sample text for this voice only. Useful when a
    # character is better demonstrated on a particular line.
    sample_text: str | None = None


class VoiceDesignRequest(BaseModel):
    voices: list[VoiceSpec]
    sample_text: str | None = None
    language: str | None = None


class VoiceDesignResponse(BaseModel):
    job_id: str
    voice_count: int
    voices: list[dict]


@router.post("/design", response_model=VoiceDesignResponse)
async def design_voices(
    req: VoiceDesignRequest,
    session: Session = Depends(get_session),
):
    """Design a batch of voices from natural-language descriptions, in ONE job.

    Batched because batching is the cost lever, not a convenience. A TTS
    container cold start is ~44s in-container — measured, see
    `docs/audit-2026-09-29.md` — so five voices as five jobs is five cold
    starts, and this endpoint is the difference between one and five.

    Refuses when no provider declares the `tts` capability, before building a
    graph or occupying a queue slot. The alternative is a job that dies inside a
    container with a ComfyUI error naming a node that was never installed,
    which is the state this feature was in before `capabilities` existed.
    """
    from services.tts_workflow_builder import (
        MAX_VOICES_PER_DESIGN_JOB,
        _require_tts_capable,
        build_voice_design_workflow,
    )

    _require_tts_capable(session)

    if not req.voices:
        raise ValidationError("Provide at least one voice to design")
    if len(req.voices) > MAX_VOICES_PER_DESIGN_JOB:
        raise ValidationError(
            f"{len(req.voices)} voices exceeds the per-job limit of "
            f"{MAX_VOICES_PER_DESIGN_JOB}. Design the cast in batches — each "
            "batch is one container cold start, which is what batching saves."
        )

    try:
        workflow, metadata = build_voice_design_workflow(
            [v.model_dump() for v in req.voices],
            sample_text=req.sample_text or DEFAULT_VOICE_SAMPLE_TEXT,
            language=req.language,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    # The TTS app is its own Modal deployment, addressed by its own app name, so
    # the shared submission path is right — it stamps `enqueued_at` and lets the
    # shared queue claim it — but the task type stays `tts` so the load balancer
    # only considers providers whose capabilities include it.
    job = await submit_tts_job(session, workflow, metadata)

    return VoiceDesignResponse(
        job_id=job.id,
        voice_count=len(req.voices),
        voices=metadata["voices"],
    )


# `POST /api/v2/voices/speak` is GONE (2026-10-21).
#
# It duplicated `POST /api/v2/voices/{voice_id}/preview`, which is the one the
# frontend calls. `VoiceSpeakRequest` went with it: nothing else referenced it.
