import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select
from sqlalchemy import func, delete

from api.deps import get_job_service, get_session, get_queue_manager, get_chat_repo, get_message_repo, get_character_repo, get_location_repo
from infrastructure.repositories.chat_repo import ChatRepository
from infrastructure.repositories.message_repo import MessageRepository
from infrastructure.repositories.character_repo import CharacterRepository
from infrastructure.repositories.location_repo import LocationRepository
from services.reference_cleanup import scrub_entity_references
from core.entities import Chat, Character, Job, JobStatus, Message, MessageKind, MessageRole, VoiceModel
from core.exceptions import ComfyError, NotFoundError, ValidationError
from services.chat_utils import insert_world_state_marker, resolve_voice_for_character, substitute_tavern_vars
from services.context_builder import build_chat_context_async, build_system_prompt_sections_async, chat_context_kwargs, prune_context
from services.job_service import JobService
from services.job_queue import QueueManager
from services.llm_workflow import build_chat_llm_workflow, sampler_overrides

MAX_CONTEXT_MESSAGES = 200
# Hard cap for endpoints that stream an entire chat history into memory
# (rollback, regenerate, swipe). Bounds RAM on multi-year single-user campaigns
# without affecting normal context-window behavior.
CHAT_HISTORY_HARD_CAP = 5000

router = APIRouter()


def _load_characters_ordered(session: Session, primary_id: str | None, additional_ids: list[str]) -> list[Character]:
    ids: list[str] = []
    if primary_id:
        ids.append(primary_id)
    for cid in additional_ids:
        if cid not in ids:
            ids.append(cid)
    if not ids:
        return []
    chars = session.exec(select(Character).where(Character.id.in_(ids))).all()
    char_map = {c.id: c for c in chars}
    return [char_map[cid] for cid in ids if cid in char_map]


class UpdateChatRequest(BaseModel):
    name: str | None = None
    character_id: str | None = None
    persona_name: str | None = None
    persona_description: str | None = None
    story_time: str | None = None
    story_location: str | None = None
    location_id: str | None = None
    active_lorebook_ids: list[str] | None = None
    llm_model: str | None = None
    allow_image_generation: bool | None = None
    allow_narration: bool | None = None
    system_prompt_override: str | None = None
    append_system_prompt: str | None = None
    max_context_tokens: int | None = None
    max_agentic_depth: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    tts_voice_id: str | None = None
    idle_sim_enabled: bool | None = None


class NarrateRequest(BaseModel):
    """Optional per-message TTS voice override."""
    voice_id: str | None = None
    language: str | None = None


class CreateChatRequest(BaseModel):
    name: str = "New Chat"
    character_id: str | None = None
    chat_type: str = "chat"
    persona_name: str | None = None
    override_greeting: str | None = None
    story_time: str | None = None
    story_location: str | None = None
    location_id: str | None = None
    active_lorebook_ids: list[str] = []
    max_agentic_depth: int | None = None
    idle_sim_enabled: bool = False


class SendMessageRequest(BaseModel):
    role: MessageRole
    content: str
    image_path: str | None = None
    lorebook_ids: list[str] | None = None
    agentic: bool = False
    generator_checkpoint: str | None = None
    no_reply: bool = False
    narrate: bool = False
    max_agentic_depth: int | None = None
    target_character_id: str | None = None


@router.get("", response_model=list[Chat])
def list_chats(
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo),
    limit: int = 50,
    offset: int = 0,
    workspace: str | None = None,
    q: str | None = None,):
    stmt = select(Chat).order_by(Chat.updated_at.desc()).offset(offset).limit(limit)
    if workspace:
        stmt = stmt.where(Chat.chat_type == workspace)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(Chat.name.ilike(pattern))
    return session.exec(stmt).all()


def _st_speaker_name(msg: Message, chat: Chat, char_names: dict[str, str]) -> str:
    if msg.role == MessageRole.USER:
        return chat.persona_name or "User"
    if msg.role == MessageRole.SYSTEM:
        return "System"
    if msg.kind == MessageKind.NARRATOR:
        return "Narrator"
    return (
        char_names.get(msg.character_id or "")
        or char_names.get(chat.character_id or "")
        or "Assistant"
    )


def _chat_to_sillytavern_jsonl(
    chat: Chat,
    messages: list[Message],
    character: Character | None,
    group_characters: list[Character],
) -> str:
    """Serialize a chat as SillyTavern-compatible JSONL.

    Line 1 is the ST metadata header; each following line is one message
    (``{name, is_user, is_system, send_date, mes}``). Non-text messages
    (world-state dividers, images) are skipped.
    """
    char_names = {c.id: c.name for c in ([character] if character else []) + group_characters}
    created = chat.created_at or datetime.now(timezone.utc)
    header = {
        "user_name": chat.persona_name or "User",
        "character_name": char_names.get(chat.character_id or "", "Assistant"),
        "create_date": created.strftime("%Y-%m-%d"),
        "chat_metadata": {},
    }
    lines = [json.dumps(header, ensure_ascii=False)]
    for msg in messages:
        meta = msg.message_metadata or {}
        if meta.get("source") == "world_state":
            continue
        if msg.kind == MessageKind.IMAGE:
            continue
        alternates = meta.get("alternates") or [msg.content]
        active_index = meta.get("active_index", 0)
        entry = {
            "name": _st_speaker_name(msg, chat, char_names),
            "is_user": msg.role == MessageRole.USER,
            "is_system": msg.role == MessageRole.SYSTEM,
            "send_date": msg.created_at.isoformat() if msg.created_at else created.isoformat(),
            "meta": {"tnh_kind": msg.kind.value if msg.kind else None},
            "swipes": [msg.content] + [a for a in alternates if a != msg.content],
            "swipe_id": active_index,
            "mes": msg.content,
        }
        lines.append(json.dumps(entry, ensure_ascii=False))
    return "\n".join(lines)


@router.get("/{chat_id}/export")
def export_chat(chat_id: str, format: str = "json", session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), character_repo: CharacterRepository = Depends(get_character_repo)):
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
    messages = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    ).all()
    character = character_repo.get(chat.character_id) if chat.character_id else None

    def _serialize_message(msg: Message) -> dict:
        return {
            "id": msg.id,
            "role": msg.role.value,
            "kind": msg.kind.value if msg.kind else None,
            "character_id": msg.character_id,
            "content": msg.content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "updated_at": msg.updated_at.isoformat() if msg.updated_at else None,
            "pinned": msg.pinned,
            "message_metadata": msg.message_metadata or {},
        }

    payload = {
        "chat": {
            "id": chat.id,
            "name": chat.name,
            "chat_type": chat.chat_type,
            "character_id": chat.character_id,
            "character_name": character.name if character else None,
            "persona_name": chat.persona_name,
            "persona_description": chat.persona_description,
            "story_time": chat.story_time,
            "story_location": chat.story_location,
            "created_at": chat.created_at.isoformat() if chat.created_at else None,
            "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
        },
        "messages": [_serialize_message(m) for m in messages],
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "message_count": len(messages),
        },
    }
    if format == "jsonl":
        group_characters = (
            session.exec(
                select(Character).where(Character.id.in_(chat.additional_character_ids or []))
            ).all()
            if chat.additional_character_ids
            else []
        )
        text = _chat_to_sillytavern_jsonl(chat, messages, character, group_characters)
        safe_name = "".join(c for c in (chat.name or "chat") if c.isalnum() or c in "-_ ").strip().replace(" ", "_")[:60] or chat.id
        return Response(
            content=text,
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.jsonl"'},
        )

    return payload


def _parse_message_timestamp(raw: object) -> datetime:
    """Best-effort parse of a SillyTavern send_date / app ISO timestamp."""
    if isinstance(raw, (int, float)) and raw > 0:
        try:
            return datetime.fromtimestamp(raw / 1000 if raw > 1e12 else raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    if isinstance(raw, str):
        candidate = raw.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


@router.post("/import", response_model=Chat)
async def import_chat(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    character_id: str | None = Form(None),
    session: Session = Depends(get_session),
    character_repo: CharacterRepository = Depends(get_character_repo),
):
    """Import a chat from a SillyTavern JSONL export or this app's JSON export."""
    try:
        text = (await file.read()).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("Chat file must be UTF-8 encoded") from exc

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValidationError("Chat file is empty")
    try:
        first = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON on first line: {exc}") from exc

    st_format = isinstance(first, dict) and "messages" not in first and (
        "chat_metadata" in first or "character_name" in first or "user_name" in first
    )
    persona_name: str | None = None
    source_chat: dict = {}
    raw_messages: list[dict] = []
    if st_format:
        persona_name = (first.get("user_name") or "").strip() or None
        for i, ln in enumerate(lines[1:], start=2):
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"Invalid JSON on line {i}: {exc}") from exc
            if isinstance(obj, dict):
                raw_messages.append(obj)
        if not raw_messages:
            raise ValidationError("No messages found in JSONL file")
    elif isinstance(first, dict) and isinstance(first.get("messages"), list):
        source_chat = first.get("chat") if isinstance(first.get("chat"), dict) else {}
        raw_messages = [m for m in first["messages"] if isinstance(m, dict)]
        if not raw_messages:
            raise ValidationError("No messages found in export file")
    else:
        raise ValidationError("Unrecognized chat file — expected SillyTavern JSONL or an exported chat JSON")

    primary: Character | None = None
    if character_id:
        primary = character_repo.get(character_id)
        if not primary:
            raise ValidationError(f"Character '{character_id}' not found")
    if primary is None and source_chat.get("character_id"):
        primary = character_repo.get(source_chat["character_id"])

    all_characters = session.exec(select(Character)).all()
    char_by_name = {c.name.strip().lower(): c for c in all_characters if c.name}

    base_ts = datetime.now(timezone.utc) - timedelta(minutes=len(raw_messages))

    chat = Chat(
        name=name or source_chat.get("name") or (f"{primary.name} chat" if primary else "Imported Chat"),
        character_id=primary.id if primary else None,
        chat_type=source_chat.get("chat_type") or "chat",
        persona_name=persona_name or source_chat.get("persona_name"),
        story_time=source_chat.get("story_time"),
        story_location=source_chat.get("story_location"),
    )
    session.add(chat)
    session.flush()

    created_messages: list[Message] = []
    for i, obj in enumerate(raw_messages):
        if st_format:
            content = str(obj.get("mes") or "").strip()
            if not content:
                continue
            if obj.get("is_system"):
                role, kind = MessageRole.SYSTEM, MessageKind.SYSTEM
            elif obj.get("is_user"):
                role, kind = MessageRole.USER, MessageKind.USER
            else:
                role, kind = MessageRole.CHAR, MessageKind.CHAR
            speaker = str(obj.get("name") or "").strip()
            ts = _parse_message_timestamp(obj.get("send_date")) or (base_ts + timedelta(seconds=i))
            cid: str | None = None
            if role == MessageRole.CHAR:
                matched = char_by_name.get(speaker.lower())
                primary_id = primary.id if primary else None
                if matched and matched.id != primary_id:
                    cid = matched.id
                elif primary_id:
                    cid = primary_id
        else:
            content = str(obj.get("content") or "").strip()
            if not content or obj.get("kind") == MessageKind.IMAGE.value:
                continue
            try:
                role = MessageRole(obj.get("role") or MessageRole.CHAR.value)
            except ValueError:
                role = MessageRole.CHAR
            kind_str = obj.get("kind")
            try:
                kind = MessageKind(kind_str) if kind_str else (
                    MessageKind.USER if role == MessageRole.USER else MessageKind.CHAR
                )
            except ValueError:
                kind = MessageKind.CHAR
            cid = obj.get("character_id")
            ts = _parse_message_timestamp(obj.get("created_at")) or (base_ts + timedelta(seconds=i))
        created_messages.append(
            Message(
                chat_id=chat.id,
                role=role,
                kind=kind,
                content=content,
                character_id=cid,
                created_at=ts,
                updated_at=ts,
            )
        )
    for msg in created_messages:
        session.add(msg)
    session.commit()
    session.refresh(chat)
    return chat


@router.post("", response_model=Chat)
async def create_chat(req: CreateChatRequest, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    if req.character_id:
        character = character_repo.get(req.character_id)
        if not character:
            raise NotFoundError("Character", req.character_id)

    chat = Chat(
        name=req.name,
        character_id=req.character_id,
        chat_type=req.chat_type,
        persona_name=req.persona_name,
        story_time=req.story_time,
        story_location=req.story_location,
        location_id=req.location_id,
        active_lorebook_ids=req.active_lorebook_ids or [],
        max_agentic_depth=req.max_agentic_depth,
        idle_sim_enabled=req.idle_sim_enabled,
    )
    chat.created_at = datetime.now(timezone.utc)
    chat.updated_at = chat.created_at
    session.add(chat)
    session.commit()
    session.refresh(chat)

    # If a character is assigned, inject their first_mes as the opening message
    if chat.character_id:
        character = character_repo.get(chat.character_id)
        if character and (req.override_greeting or character.first_mes):
            # Apply basic template variable substitution before persisting
            raw_mes = req.override_greeting or character.first_mes
            first_mes = substitute_tavern_vars(
                raw_mes,
                char=character.name or "",
                user=chat.persona_name or "User",
            )
            opening = Message(
                chat_id=chat.id,
                role=MessageRole.CHAR,
                content=first_mes,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(opening)
            session.commit()
            session.refresh(chat)

    return chat


@router.get("/{chat_id}", response_model=Chat)
def get_chat(chat_id: str, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo)):
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
    return chat

@router.delete("/{chat_id}")
def delete_chat(chat_id: str, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo)):
    from sqlalchemy import delete as sql_delete

    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    scrub_entity_references(session, "chat", chat_id)
    # Issue a direct SQL DELETE for messages first so the FK constraint is
    # satisfied before the chat row is removed.  The ORM unit-of-work can
    # reorder session.delete() calls and execute the chat DELETE before the
    # message DELETEs, causing an IntegrityError (messages_chat_id_fkey).
    session.exec(sql_delete(Message).where(Message.chat_id == chat_id))
    session.flush()   # commit the message deletes to the DB within the same txn
    session.delete(chat)
    session.commit()
    return {"message": "Chat deleted"}


@router.get("/{chat_id}/messages", response_model=list[Message])
def list_messages(chat_id: str, branch_id: str | None = None, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo),   limit: int = 100, offset: int = 0, q: str | None = None):
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
    query = select(Message).where(Message.chat_id == chat_id)
    if branch_id:
        query = query.where(Message.branch_id == branch_id)
    if q:
        query = query.where(Message.content.ilike(f"%{q}%"))
    return session.exec(query.order_by(Message.created_at).offset(offset).limit(limit)).all()


@router.get("/{chat_id}/system-prompt")
async def get_chat_system_prompt(chat_id: str, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo)):
    """Return the assembled system prompt (with per-section breakdown) for this chat."""
    from services.context_builder import estimate_tokens

    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    past_messages = list(
        session.exec(
            select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.desc()).limit(MAX_CONTEXT_MESSAGES)
        ).all()
    )
    past_messages.reverse()

    characters = _load_characters_ordered(session, chat.character_id, chat.additional_character_ids or [])

    ctx_kwargs = chat_context_kwargs(chat, characters=characters)

    sections = await build_system_prompt_sections_async(
        **ctx_kwargs,
    )

    system_prompt, context = await build_chat_context_async(
        past_messages,
        **ctx_kwargs,
    )

    return {
        "chat_id": chat_id,
        "character_id": chat.character_id,
        "system_prompt": system_prompt or "",
        "has_override": bool(chat.system_prompt_override),
        "has_append": bool(chat.append_system_prompt),
        "message_count": len(context),
        "context_tokens": estimate_tokens("\n".join(m.get("content", "") for m in context)),
        "sections": sections,
    }


@router.patch("/{chat_id}", response_model=Chat)
def update_chat(chat_id: str, data: UpdateChatRequest, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), location_repo: LocationRepository = Depends(get_location_repo)):
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
    update_fields = data.model_dump(exclude_unset=True)
    # Validate location_id if provided
    if "location_id" in update_fields and update_fields["location_id"] is not None:
        location = location_repo.get(update_fields["location_id"])
        if not location:
            raise NotFoundError("Location", update_fields["location_id"])
    # Validate tts_voice_id if provided
    if "tts_voice_id" in update_fields and update_fields["tts_voice_id"] is not None:
        from core.entities import VoiceModel
        voice = session.get(VoiceModel, update_fields["tts_voice_id"])
        if not voice:
            raise NotFoundError("VoiceModel", update_fields["tts_voice_id"])
    changed_state = {}
    if "story_time" in update_fields and update_fields["story_time"] != chat.story_time:
        changed_state["time"] = update_fields["story_time"]
        changed_state["old_time"] = chat.story_time
    if "story_location" in update_fields and update_fields["story_location"] != chat.story_location:
        changed_state["location"] = update_fields["story_location"]
        changed_state["old_location"] = chat.story_location
    if "location_id" in update_fields and update_fields["location_id"] != chat.location_id:
        changed_state["location_id"] = update_fields["location_id"]
        changed_state["old_location_id"] = chat.location_id
    for key, value in update_fields.items():
        setattr(chat, key, value)
    chat.updated_at = datetime.now(timezone.utc)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    if changed_state:
        insert_world_state_marker(session, chat_id, changed_state)

    return chat


# ---------------------------------------------------------------------------
# Helper: resolve default LLM model id from llm_config.json
# ---------------------------------------------------------------------------
from services.llm_config import get_default_llm_model as _get_default_llm_model

# ---------------------------------------------------------------------------
# Helper: resolve effective context window for a chat
# ---------------------------------------------------------------------------
from services.chat_utils import resolve_context_tokens as _resolve_context_tokens


@router.post("/{chat_id}/messages")
async def add_message(chat_id: str, request: SendMessageRequest, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), message_repo: MessageRepository = Depends(get_message_repo)) -> dict:
    from services.job_queue import queue_manager
    
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
        
    message = Message(
        chat_id=chat_id,
        role=request.role,
        content=request.content,
        image_path=request.image_path,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    
    session.add(message)
    session.commit()
    session.refresh(message)
    
    job_id = None
    
    if message.role == MessageRole.USER and not request.no_reply:
        past_messages = message_repo.list_by_chat(chat_id)
        
        characters = _load_characters_ordered(session, chat.character_id, chat.additional_character_ids or [])
            
        ctx_kwargs = chat_context_kwargs(
            chat,
            characters=characters,
            lorebook_ids=request.lorebook_ids,
            max_context_tokens=_resolve_context_tokens(chat),
            active_character_id=request.target_character_id,
        )
        system_prompt, context = await build_chat_context_async(
            past_messages, 
            **ctx_kwargs,
        )
            
        try:
            job_service = get_job_service(session)

            if request.narrate:
                if not chat.allow_narration:
                    raise ValidationError("Narration is disabled for this chat")
                from config import get_system_prompt_blocks
                from services.orchestrator_service import NARRATOR_SYSTEM_PROMPT

                narrator_prompt = (get_system_prompt_blocks() or {}).get("narrator") or NARRATOR_SYSTEM_PROMPT

                workflow, metadata = build_chat_llm_workflow(
                    messages=[
                        {"role": "system", "content": narrator_prompt},
                        *context,
                        {"role": "user", "content": f"[Narration request] {message.content}"},
                    ],
                    chat_id=chat_id,
                    character_id=request.target_character_id or chat.character_id,
                    system_prompt=system_prompt or None,
                    model=chat.llm_model or _get_default_llm_model(),
                    samplers=sampler_overrides(chat),
                    type_="narrator",
                    source="narrator",
                )
            else:
                workflow, metadata = build_chat_llm_workflow(
                    messages=context,
                    chat_id=chat_id,
                    character_id=request.target_character_id or chat.character_id,
                    system_prompt=system_prompt or None,
                    model=chat.llm_model or _get_default_llm_model(),
                    samplers=sampler_overrides(chat),
                )

            if request.agentic:
                from services.orchestrator_service import AGENTIC_TOOLS, filter_agentic_tools
                workflow["tools"] = filter_agentic_tools(
                    AGENTIC_TOOLS,
                    allow_image=chat.allow_image_generation,
                    allow_narration=chat.allow_narration,
                )
                metadata["agentic"] = True
                metadata["orchestrator_depth"] = 0
                metadata["original_messages"] = context
                effective_max = request.max_agentic_depth or chat.max_agentic_depth
                if effective_max is not None:
                    metadata["max_agentic_depth"] = effective_max

            if request.generator_checkpoint:
                metadata["generator_checkpoint"] = request.generator_checkpoint

            job = await job_service.create_job(
                task_type="llm",
                workflow=workflow,
                metadata=metadata,
            )

            await queue_manager.enqueue(job.id, task_type="llm")
            job_id = job.id

        except Exception as e:
            raise ComfyError(str(e))

    return {"user_message_id": message.id, "job_id": job_id}

@router.delete("/{chat_id}/messages/{message_id}")
def delete_message(chat_id: str, message_id: str, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo)):
    message = session.get(Message, message_id)
    if not message or message.chat_id != chat_id:
        raise NotFoundError("Message", message_id)
        
    session.delete(message)
    session.commit()
    return {"message": "Message deleted"}

@router.get("/{chat_id}/jobs")
def list_chat_jobs(chat_id: str, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo)):
    """Recent jobs (LLM + image) assigned to this chat, newest first."""

    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    jobs = session.exec(
        select(Job)
        .where(
            Job.status.in_([JobStatus.PENDING, JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED,
                           JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING,
                           JobStatus.COMPLETED, JobStatus.FAILED]),
        )
        .where(Job.metadata_["chat_id"].as_string() == chat_id)
        .order_by(Job.created_at.desc())
        .limit(100)
    ).all()

    chat_jobs = []
    for job in jobs:
        meta = job.metadata_ or {}
        workflow = job.workflow or {}
        job_type = meta.get("type") or workflow.get("type") or meta.get("source") or job.task_type
        chat_jobs.append({
            "id": job.id,
            "task_type": job.task_type,
            "type": job_type,
            "status": job.status.value,
            "progress": job.progress,
            "overall_progress": job.overall_progress,
            "message": job.message,
            "error": job.error,
            "provider_id": job.provider_id,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "agentic": bool(meta.get("agentic")),
            "depth": meta.get("orchestrator_depth"),
            "parent_job_id": meta.get("parent_job_id"),
        })
    return chat_jobs

class EditMessageRequest(BaseModel):
    content: str


class SwipeRequest(BaseModel):
    direction: str  # "left" | "right" | "select"
    index: int | None = None  # used when direction == "select"


@router.post("/{chat_id}/messages/{message_id}/narrate", response_model=dict)
async def narrate_message(
    chat_id: str,
    message_id: str,
    data: NarrateRequest | None = None,
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    character_repo: CharacterRepository = Depends(get_character_repo),
    job_service: JobService = Depends(get_job_service),
    queue_manager: QueueManager = Depends(get_queue_manager),
):
    """Trigger a TTS job to narrate a specific message."""
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
        
    message = session.get(Message, message_id)
    if not message or message.chat_id != chat_id:
        raise NotFoundError("Message", message_id)

    if not message.content:
        raise ComfyError("Message has no content to narrate")

    from core.workflow_builder import build_tts_workflow

    # Resolve voice profile: explicit voice_id → chat override → character voice → default
    voice_profile = voice_model_id = language = None
    chosen_voice_id = (data.voice_id if data else None) or chat.tts_voice_id
    if chosen_voice_id:
        voice = session.get(VoiceModel, chosen_voice_id)
        if not voice:
            raise NotFoundError("VoiceModel", chosen_voice_id)
        voice_profile = voice.voice_profile
        voice_model_id = voice.id
        language = voice.language
    elif chat.character_id:
        char = character_repo.get(chat.character_id)
        voice_profile, voice_model_id, language = resolve_voice_for_character(session, char)
    if data and data.language:
        language = data.language

    workflow, metadata = build_tts_workflow(
        text=message.content,
        voice_profile=voice_profile,
        voice_model_id=voice_model_id,
        language=language,
        chat_id=chat_id,
        character_id=chat.character_id,
        extra_metadata={
            "source": "chat_tts",
            "message_id": message_id,
        }
    )

    job = await job_service.create_job(
        task_type="image",  # Dispatch to the ComfyUI image_worker adapter
        workflow=workflow,
        metadata=metadata,
    )
    await queue_manager.enqueue(job.id, task_type="image")
    
    return {"message_id": message.id, "job_id": job.id}


@router.post("/{chat_id}/messages/{message_id}/swipe", response_model=Message)
def swipe_message(
    chat_id: str,
    message_id: str,
    data: SwipeRequest,
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), ):
    """Navigate between alternate replies for a character message.

    Alternates are stored in message_metadata:
      {"alternates": ["text0", "text1", ...], "active_index": 0}

    The message content is always kept in sync with the active alternate.
    Swiping right moves to the next alternate (or wraps), left moves back.
    Selecting by index picks a specific alternate directly.
    """
    message = session.get(Message, message_id)
    if not message or message.chat_id != chat_id:
        raise NotFoundError("Message", message_id)
    if message.role != MessageRole.CHAR:
        raise ValidationError("Only character messages support swipe")

    meta = message.message_metadata or {}
    alternates: list[str] = meta.get("alternates", [message.content])
    if message.content not in alternates:
        alternates.insert(0, message.content)
    active_index: int = meta.get("active_index", 0)
    n = len(alternates)

    if data.direction == "right":
        active_index = (active_index + 1) % n
    elif data.direction == "left":
        active_index = (active_index - 1) % n
    elif data.direction == "select":
        if data.index is None or data.index < 0 or data.index >= n:
            raise ValidationError(f"Invalid index {data.index} (0–{n-1})")
        active_index = data.index
    else:
        raise ValidationError("direction must be left | right | select")

    message.content = alternates[active_index]
    message.message_metadata = {**meta, "alternates": alternates, "active_index": active_index}
    message.updated_at = datetime.now(timezone.utc)
    session.add(message)
    session.commit()
    session.refresh(message)
    return message


@router.post("/{chat_id}/messages/{message_id}/generate-swipe")
async def generate_swipe(
    chat_id: str,
    message_id: str,
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo)
) -> dict:
    from services.job_queue import queue_manager

    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    target_msg = session.get(Message, message_id)
    if not target_msg or target_msg.chat_id != chat_id:
        raise NotFoundError("Message", message_id)
    if target_msg.role != MessageRole.CHAR:
        raise ValidationError("Only character messages can generate swipes")

    all_messages = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.desc()).limit(CHAT_HISTORY_HARD_CAP)
    ).all()
    all_messages.reverse()
    
    target_index = next((i for i, m in enumerate(all_messages) if m.id == target_msg.id), -1)
    if target_index < 0:
        raise NotFoundError("Message", message_id)

    remaining = all_messages[:target_index]
    
    characters = _load_characters_ordered(session, chat.character_id, chat.additional_character_ids or [])

    ctx_kwargs = chat_context_kwargs(
        chat,
        characters=characters,
        max_context_tokens=_resolve_context_tokens(chat),
    )
    system_prompt, context = await build_chat_context_async(
        remaining,
        **ctx_kwargs,
    )

    
    # Mirror agentic state
    prev_agentic = target_msg.tool_calls is not None or (target_msg.message_metadata or {}).get("agentic", False)

    workflow, metadata = build_chat_llm_workflow(
        messages=context,
        chat_id=chat_id,
        character_id=chat.character_id,
        system_prompt=system_prompt or None,
        model=chat.llm_model or _get_default_llm_model(),
        samplers=sampler_overrides(chat),
        extra_metadata={
            "is_swipe": True,
            "target_message_id": message_id
        },
    )
    
    if prev_agentic:
        from services.orchestrator_service import AGENTIC_TOOLS, filter_agentic_tools
        workflow["tools"] = filter_agentic_tools(
            AGENTIC_TOOLS,
            allow_image=chat.allow_image_generation,
            allow_narration=chat.allow_narration,
        )
        metadata["agentic"] = True
        metadata["orchestrator_depth"] = 0
        metadata["original_messages"] = context
        metadata["max_agentic_depth"] = chat.max_agentic_depth or 3

    job_service = get_job_service(session)
    job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
    session.commit()

    # Agentic chaining happens when the job completes with tool calls
    # (see job_processing.py) — this route only enqueues the job.
    await queue_manager.enqueue(job.id, task_type="llm")

    return {"job_id": job.id}

class PinMessageRequest(BaseModel):
    pinned: bool


@router.patch("/{chat_id}/messages/{message_id}/pin", response_model=Message)
def pin_message(
    chat_id: str,
    message_id: str,
    data: PinMessageRequest,
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), ):
    """Toggle the pinned state of a message. Pinned messages survive context pruning."""
    message = session.get(Message, message_id)
    if not message or message.chat_id != chat_id:
        raise NotFoundError("Message", message_id)
    message.pinned = data.pinned
    message.updated_at = datetime.now(timezone.utc)
    session.add(message)
    session.commit()
    session.refresh(message)
    return message

class RollbackRequest(BaseModel):
    message_id: str

class RegenerateRequest(BaseModel):
    message_id: str | None = None

@router.patch("/{chat_id}/messages/{message_id}", response_model=Message)
def edit_message(
    chat_id: str,
    message_id: str,
    data: EditMessageRequest,
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), ):
    message = session.get(Message, message_id)
    if not message or message.chat_id != chat_id:
        raise NotFoundError("Message", message_id)
    if message.role not in (MessageRole.USER, MessageRole.CHAR):
        raise ValidationError("Only user and character messages can be edited")
    message.content = data.content
    message.updated_at = datetime.now(timezone.utc)
    session.add(message)
    session.commit()
    session.refresh(message)
    return message

@router.post("/{chat_id}/rollback")
def rollback_chat(
    chat_id: str,
    req: RollbackRequest,
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), ):
    """Delete the target message and everything after it (undo mistakes)."""
    from sqlalchemy import delete
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    anchor = session.get(Message, req.message_id)
    if not anchor or anchor.chat_id != chat_id:
        raise NotFoundError("Message", req.message_id)

    # Delete at the SQL level — never loads the full chat history into Python.
    result = session.execute(
        delete(Message).where(
            Message.chat_id == chat_id,
            Message.created_at >= anchor.created_at,
        )
    )
    deleted = result.rowcount
    session.commit()

    kept = session.exec(
        select(func.count(Message.id)).where(Message.chat_id == chat_id)
    ).one()
    return {"deleted": deleted, "kept": kept}

@router.post("/{chat_id}/regenerate")
async def regenerate_reply(
    chat_id: str,
    req: RegenerateRequest,
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo),
) -> dict:
    """
    Re-run the last user message: delete every message after it, then dispatch
    a fresh reply job mirroring the previous job's agentic settings.
    """
    from services.job_queue import queue_manager

    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    anchor = None
    if req.message_id:
        anchor = session.get(Message, req.message_id)
        if not anchor or anchor.chat_id != chat_id:
            raise NotFoundError("Message", req.message_id)
    else:
        # Find the most recent user message without scanning full history.
        anchor = session.exec(
            select(Message)
            .where(Message.chat_id == chat_id, Message.role == MessageRole.USER)
            .order_by(Message.created_at.desc())
            .limit(1)
        ).first()

    if not anchor:
        raise ValidationError("No user message to regenerate")

    # Delete trailing messages at the SQL level.
    delete_result = session.execute(
        delete(Message).where(
            Message.chat_id == chat_id,
            Message.created_at > anchor.created_at,
        )
    )
    deleted = delete_result.rowcount

    # Mirror the previous chat_reply job's agentic settings if available.
    prev_agentic = False
    prev_checkpoint = None
    recent_jobs = session.exec(
        select(Job)
        .where(Job.task_type == "llm")
        .where(Job.metadata_["chat_id"].as_string() == chat_id)
        .order_by(Job.created_at.desc())
        .limit(20)
    ).all()
    for job in recent_jobs:
        meta = job.metadata_ or {}
        wf = job.workflow or {}
        if (wf.get("type") or meta.get("type")) == "chat_reply":
            prev_agentic = bool(meta.get("agentic"))
            prev_checkpoint = meta.get("generator_checkpoint")
            break

    # Load only the recent context window (context builder caps to MAX_CONTEXT_MESSAGES).
    recent = session.exec(
        select(Message)
        .where(Message.chat_id == chat_id, Message.created_at <= anchor.created_at)
        .order_by(Message.created_at.desc())
        .limit(CHAT_HISTORY_HARD_CAP)
    ).all()
    remaining = list(reversed(recent))
    characters = _load_characters_ordered(session, chat.character_id, chat.additional_character_ids or [])

    ctx_kwargs = chat_context_kwargs(
        chat,
        characters=characters,
        max_context_tokens=_resolve_context_tokens(chat),
    )
    system_prompt, context = await build_chat_context_async(
        remaining,
        **ctx_kwargs,
    )


    workflow, metadata = build_chat_llm_workflow(
        messages=context,
        chat_id=chat_id,
        character_id=getattr(anchor, "character_id", None) or chat.character_id,
        system_prompt=system_prompt or None,
        model=chat.llm_model or _get_default_llm_model(),
        samplers=sampler_overrides(chat),
        extra_metadata={"regenerated": True},
    )
    if prev_agentic:
        from services.orchestrator_service import AGENTIC_TOOLS, filter_agentic_tools
        workflow["tools"] = filter_agentic_tools(
            AGENTIC_TOOLS,
            allow_image=chat.allow_image_generation,
            allow_narration=chat.allow_narration,
        )
        metadata["agentic"] = True
        metadata["orchestrator_depth"] = 0
        metadata["original_messages"] = context
        effective_max = chat.max_agentic_depth
        if effective_max is not None:
            metadata["max_agentic_depth"] = effective_max
    if prev_checkpoint:
        metadata["generator_checkpoint"] = prev_checkpoint

    job_service = get_job_service(session)
    try:
        job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
        session.commit()
        await queue_manager.enqueue(job.id, task_type="llm")
    except Exception as e:
        session.rollback()
        raise ComfyError(str(e))

    return {"job_id": job.id, "removed_messages": deleted}

class ImpersonateRequest(BaseModel):
    hint: str = ""  # Optional direction for the impersonation


@router.post("/{chat_id}/impersonate")
async def impersonate(chat_id: str, req: ImpersonateRequest, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), character_repo: CharacterRepository = Depends(get_character_repo)) -> dict:
    """Generate a user-voice message and insert it as a USER turn, then trigger the char reply.

    Unlike /suggest (which streams text into the input box), impersonation inserts
    a completed user message directly and immediately fires the character's response.
    The LLM writes *as the user*, not as the character.
    """
    from services.job_queue import queue_manager

    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    past_messages = list(
        session.exec(
            select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.desc()).limit(MAX_CONTEXT_MESSAGES)
        ).all()
    )
    past_messages.reverse()

    character = character_repo.get(chat.character_id) if chat.character_id else None

    user_name = chat.persona_name or "User"
    char_name = character.name if character else "the AI"

    # Build world-state context without character identity (same approach as suggest)
    world_sections = await build_system_prompt_sections_async(
        **chat_context_kwargs(chat, character=None, include_roleplay_default=False),
    )
    world_context_str = "\n\n".join(s["content"] for s in world_sections) if world_sections else ""

    hint_clause = f" Specifically: {req.hint.strip()}." if req.hint.strip() else ""
    imp_system = (
        f"You are {user_name}, the human participant in this roleplay with {char_name}. "
        f"Write ONE in-character message or action that {user_name} would realistically say or do next.{hint_clause} "
        f"Output ONLY the raw message text — no labels, no quotes around the whole reply."
        + (f"\n\n{world_context_str}" if world_context_str else "")
    )

    # Swap roles for the impersonation LLM call: char→user, user→assistant
    msg_list = []
    for msg in past_messages:
        meta = getattr(msg, "message_metadata", None) or {}
        if meta.get("source") == "world_state":
            continue
        if msg.role == MessageRole.USER:
            msg_list.append({"role": "assistant", "content": msg.content})
        elif msg.role == MessageRole.CHAR:
            msg_list.append({"role": "user", "content": msg.content})
        elif msg.role == MessageRole.SYSTEM and meta.get("source") not in ("narrator", "world_state"):
            msg_list.append({"role": "user", "content": f"[{msg.content}]"})

    all_msgs = [{"role": "system", "content": imp_system}] + msg_list
    all_msgs = prune_context(all_msgs, imp_system, [], _resolve_context_tokens(chat))

    try:
        job_service = get_job_service(session)

        workflow, metadata = build_chat_llm_workflow(
            messages=all_msgs,
            chat_id=chat_id,
            character_id=chat.character_id,
            model=chat.llm_model or _get_default_llm_model(),
            samplers=sampler_overrides(chat),
            type_="suggest_reply",
            source="suggest_reply",
            extra_metadata={
                "hint": req.hint,
                "is_impersonation": True,
                "max_agentic_depth": chat.max_agentic_depth,
            } if req.hint else {
                "is_impersonation": True,
                "max_agentic_depth": chat.max_agentic_depth,
            },
        )

        imp_job = await job_service.create_job(
            task_type="llm",
            workflow=workflow,
            metadata=metadata,
        )
        await queue_manager.enqueue(imp_job.id, task_type="llm")
        return {"job_id": imp_job.id}
    except Exception as e:
        raise ComfyError(str(e))


class SuggestReplyRequest(BaseModel):
    draft: str | None = None

@router.post("/{chat_id}/suggest")
async def suggest_reply(chat_id: str, req: SuggestReplyRequest, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), character_repo: CharacterRepository = Depends(get_character_repo)) -> dict:

    from services.job_queue import queue_manager
    
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
        
    past_messages = list(
        session.exec(
            select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.desc()).limit(MAX_CONTEXT_MESSAGES)
        ).all()
    )
    past_messages.reverse()

    character = None
    if chat.character_id:
        character = character_repo.get(chat.character_id)

    from config import get_system_prompt_blocks

    world_sections = await build_system_prompt_sections_async(
        **chat_context_kwargs(chat, character=None, include_roleplay_default=False),
    )
    world_context_str = "\n\n".join(s["content"] for s in world_sections) if world_sections else ""

    user_name = chat.persona_name or "User"
    char_name = character.name if character else "the AI"

    if req.draft and req.draft.strip():
        # Draft provided: Refine the user's draft
        suggest_instruction = (
            "CRITICAL INSTRUCTION: You are acting as {user}, the human user in this roleplay. "
            "You have written a rough draft of your next message, but you need to refine it. "
            "Rewrite the draft to be more descriptive, in-character, and engaging, while keeping the original intent. "
            "Write only the raw text of the final response — no labels, no quotes around the whole reply, no meta-commentary."
        )
        suggest_instruction = substitute_tavern_vars(suggest_instruction, char=char_name, user=user_name)
        suggest_system = (
            f"You are {user_name}, the human participant in the following roleplay conversation "
            f"with {char_name}. Your job is to rewrite and improve {user_name}'s rough draft of the next message.\n\n"
            + (f"{world_context_str}\n\n" if world_context_str else "")
            + suggest_instruction
        )
    else:
        # No draft: Auto-suggest from scratch
        suggest_instruction = (
            (get_system_prompt_blocks() or {}).get("suggest_instruction")
            or (
                "CRITICAL INSTRUCTION: You are acting as {user}, the human user in this roleplay. "
                "Based on the conversation so far, write ONE short, in-character response or action "
                "that {user} would realistically say or do next. "
                "Write only the raw text — no labels, no quotes around the whole reply, no meta-commentary."
            )
        )
        suggest_instruction = substitute_tavern_vars(suggest_instruction, char=char_name, user=user_name)
        suggest_system = (
            f"You are {user_name}, the human participant in the following roleplay conversation "
            f"with {char_name}. Your job is to suggest what {user_name} might say or do next.\n\n"
            + (f"{world_context_str}\n\n" if world_context_str else "")
            + suggest_instruction
        )

    msg_list = []
    for msg in past_messages:
        meta = getattr(msg, "message_metadata", None) or {}
        if meta.get("source") == "world_state":
            continue
        if msg.role == MessageRole.USER:
            # From the LLM's perspective (acting as user), prior user messages are "assistant"
            msg_list.append({"role": "assistant", "content": msg.content})
        elif msg.role == MessageRole.CHAR:
            # Character messages are the "user" turn (the party the LLM is responding to)
            msg_list.append({"role": "user", "content": msg.content})
        elif msg.role == MessageRole.SYSTEM and meta.get("source") not in ("narrator", "world_state"):
            msg_list.append({"role": "user", "content": f"[{msg.content}]"})

    # Prune to stay within context budget
    all_msgs = [{"role": "system", "content": suggest_system}] + msg_list
    
    if req.draft and req.draft.strip():
        all_msgs.append({"role": "user", "content": f"[User's rough draft to refine]:\n{req.draft}"})
        
    all_msgs = prune_context(all_msgs, suggest_system, [], _resolve_context_tokens(chat))

    try:
        job_service = get_job_service(session)

        workflow, metadata = build_chat_llm_workflow(
            messages=all_msgs,
            chat_id=chat_id,
            character_id=chat.character_id,
            model=chat.llm_model or _get_default_llm_model(),
            samplers=sampler_overrides(chat),
            type_="suggest_reply",
            extra_metadata={"is_suggestion": True, "max_agentic_depth": chat.max_agentic_depth},
        )

        job = await job_service.create_job(
            task_type="llm",
            workflow=workflow,
            metadata=metadata,
        )
        await queue_manager.enqueue(job.id, task_type="llm")
        return {"job_id": job.id}
        
    except Exception as e:
        raise ComfyError(str(e))

@router.post("/{chat_id}/scene")
async def generate_scene(
    chat_id: str, 
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    character_repo: CharacterRepository = Depends(get_character_repo),
    message_repo: MessageRepository = Depends(get_message_repo),
):
    from services.job_queue import queue_manager

    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
        
    past_messages = message_repo.list_by_chat(chat_id)
    if not past_messages:
        raise ValidationError("No messages in chat to base scene on")
        
    context_text = "\n".join([f"{m.role.value}: {m.content}" for m in past_messages[-10:] if m.content])
    
    # Resolve checkpoint: character > configured default > any installed model
    checkpoint = None
    if chat.character_id:
        character = character_repo.get(chat.character_id)
        if character and character.checkpoint:
            checkpoint = character.checkpoint
    if not checkpoint:
        from services.model_availability_service import ModelAvailabilityService
        checkpoint = ModelAvailabilityService(session).resolve_checkpoint()
    
    system_prompt = (
        "You are an AI scene director for a roleplay chat. Read the following recent "
        "roleplay chat context and create a visual depiction of the current scene or the "
        "main character's action (e.g. a selfie).\n"
        "Call the generate_image tool with a highly detailed ComfyUI image prompt "
        "(comma-separated Danbooru tags: subject, pose, lighting, camera angle, style, "
        "quality tags).\n"
        "After the image is generated, reply with a brief in-character caption for the "
        "image (1-2 sentences).\n"
        "If you are unable to call tools, output ONLY the image prompt text."
    )

    job_service = JobService(session)
    from services.orchestrator_service import AGENTIC_TOOLS, filter_agentic_tools

    workflow, metadata = build_chat_llm_workflow(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\n{context_text}"}
        ],
        chat_id=chat_id,
        character_id=chat.character_id,
        model=chat.llm_model or _get_default_llm_model(),
        samplers=sampler_overrides(chat),
        type_="chat_reply",
        workspace="roleplay",
        source="scene_prompt",
        extra_metadata={
            "scene_checkpoint": checkpoint,
            "generator_checkpoint": checkpoint,
            "agentic": True,
            "orchestrator_depth": 0,
        },
    )
    workflow["tools"] = filter_agentic_tools(
        AGENTIC_TOOLS,
        allow_image=chat.allow_image_generation,
        allow_narration=chat.allow_narration,
    )

    prompt_job = await job_service.create_job(
        task_type="llm",
        workflow=workflow,
        metadata=metadata,
    )
    await queue_manager.enqueue(prompt_job.id, task_type="llm")
    
    # The scene LLM job is agentic: it calls the generate_image tool (or, when
    # the model cannot call tools, its plain-text output is chained into an
    # image job by the scene_prompt finalize branch in job_processing.py).
    return {"job_id": prompt_job.id, "status": "queued", "message": "Scene generation started"}


class ChatIllustrateRequest(BaseModel):
    image_prompt: str = ""


@router.post("/{chat_id}/illustrate")
async def illustrate_chat(
    chat_id: str,
    request: ChatIllustrateRequest,
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    character_repo: CharacterRepository = Depends(get_character_repo),
):
    """Generate an image for the current chat moment without an LLM in the loop.

    Uses the provided prompt, or falls back to the latest character reply when
    no prompt is given. Mirrors the agentic generate_image tool's metadata so
    the image lands in the chat as a kind=IMAGE message via the chat_image
    event (world_integration_service) and in the roleplay workspace.
    """
    from services.model_availability_service import ModelAvailabilityService

    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
    if not chat.allow_image_generation:
        raise ValidationError("Image generation is disabled for this chat")

    image_prompt = (request.image_prompt or "").strip()
    if not image_prompt:
        last_char = session.exec(
            select(Message)
            .where(
                Message.chat_id == chat_id,
                Message.role.in_(["char", "user"]),
                Message.content.is_not(None),
            )
            .order_by(Message.created_at.desc())
        ).first()
        if last_char and last_char.content.strip():
            image_prompt = last_char.content.strip()
    if not image_prompt:
        raise ValidationError("No prompt and no character reply to illustrate")

    character = character_repo.get(chat.character_id) if chat.character_id else None

    checkpoint = (character.checkpoint if character and character.checkpoint else None)
    if not checkpoint:
        checkpoint = ModelAvailabilityService(session).resolve_checkpoint()

    lora_name = character.lora if character and character.lora else None

    from services.image_submission import submit_image_job

    job = await submit_image_job(
        session,
        prompt=image_prompt,
        checkpoint=checkpoint,
        lora=lora_name,
        filename_prefix="ChatIllustrate",
        source="chat_image",
        workspace="chat",
        chat_id=chat_id,
        character_id=chat.character_id,
        extra_metadata={"image_context": image_prompt},
    )
    return {"job_id": job.id, "status": "queued", "message": "Illustration started"}


@router.get("/{chat_id}/images")
def list_chat_images(chat_id: str, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo)):
    """List all images attached to messages in this chat (workspace gallery)."""
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    rows = session.exec(
        select(Message)
        .where(Message.chat_id == chat_id, Message.image_path.is_not(None))
        .order_by(Message.created_at.desc())
    ).all()
    return [
        {"path": m.image_path, "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in rows
        if m.image_path
    ]
