from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_job_service, get_session
from core.entities import Chat, Character, Message, MessageRole

router = APIRouter()


class UpdateChatRequest(BaseModel):
    name: str | None = None
    character_id: str | None = None
    persona_name: str | None = None
    persona_description: str | None = None
    story_time: str | None = None
    story_location: str | None = None
    active_lorebook_ids: list[str] | None = None
    llm_model: str | None = None
    allow_image_generation: bool | None = None
    allow_narration: bool | None = None
    system_prompt_override: str | None = None
    append_system_prompt: str | None = None
    max_context_tokens: int | None = None


class CreateChatRequest(BaseModel):
    name: str = "New Chat"
    character_id: str | None = None
    chat_type: str = "chat"
    persona_name: str | None = None
    override_greeting: str | None = None
    story_time: str | None = None
    story_location: str | None = None
    active_lorebook_ids: list[str] = []


class SendMessageRequest(BaseModel):
    role: MessageRole
    content: str
    image_path: str | None = None
    lorebook_ids: list[str] | None = None
    agentic: bool = False
    generator_checkpoint: str | None = None
    no_reply: bool = False
    narrate: bool = False


@router.get("", response_model=list[Chat])
def list_chats(
    session: Session = Depends(get_session),
    limit: int = 50,
    offset: int = 0,
    workspace: str | None = None,
):
    stmt = select(Chat).order_by(Chat.updated_at.desc()).offset(offset).limit(limit)
    if workspace:
        stmt = stmt.where(Chat.chat_type == workspace)
    return session.exec(stmt).all()

@router.post("", response_model=Chat)
async def create_chat(req: CreateChatRequest, session: Session = Depends(get_session)):
    chat = Chat(
        name=req.name,
        character_id=req.character_id,
        chat_type=req.chat_type,
        persona_name=req.persona_name,
        story_time=req.story_time,
        story_location=req.story_location,
        active_lorebook_ids=req.active_lorebook_ids or [],
    )
    chat.created_at = datetime.now(timezone.utc)
    chat.updated_at = chat.created_at
    session.add(chat)
    session.commit()
    session.refresh(chat)

    # If a character is assigned, inject their first_mes as the opening message
    if chat.character_id:
        character = session.get(Character, chat.character_id)
        if character and (req.override_greeting or character.first_mes):
            # Apply basic template variable substitution before persisting
            raw_mes = req.override_greeting or character.first_mes
            first_mes = _substitute_tavern_vars(
                raw_mes,
                char=character.name or "",
                user=chat.persona_name or chat.name or "User",
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


def _substitute_tavern_vars(text: str, *, char: str = "", user: str = "User") -> str:
    """Apply SillyTavern-compatible template variable substitution on the backend.
    Handles {{char}}, {{user}} at minimum. Extend as needed."""
    import re
    from datetime import date as _date

    now = datetime.now(timezone.utc)
    replacements = {
        "char": char,
        "user": user,
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%Y-%m-%d"),
    }

    def replace_match(m):
        key = m.group(1).strip().lower()
        # {{random::a::b}} — pick randomly
        if key.startswith("random::"):
            options = [o.strip() for o in key[len("random::"):].split("::") if o.strip()]
            if options:
                import random
                return random.choice(options)
            return m.group(0)
        return replacements.get(key, m.group(0))

    return re.sub(r"\{\{([^}]+)\}\}", replace_match, text)

@router.get("/{chat_id}", response_model=Chat)
def get_chat(chat_id: str, session: Session = Depends(get_session)):
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat

@router.delete("/{chat_id}")
def delete_chat(chat_id: str, session: Session = Depends(get_session)):
    from sqlalchemy import delete as sql_delete

    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

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
def list_messages(chat_id: str, session: Session = Depends(get_session), limit: int = 100, offset: int = 0):
    return session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at).offset(offset).limit(limit)
    ).all()


@router.get("/{chat_id}/system-prompt")
async def get_chat_system_prompt(chat_id: str, session: Session = Depends(get_session)):
    """Return the assembled system prompt (with per-section breakdown) for this chat."""
    from services.context_builder import (
        build_chat_context_async,
        build_system_prompt_sections_async,
        estimate_tokens,
    )

    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    past_messages = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    ).all()

    character = None
    if chat.character_id:
        character = session.get(Character, chat.character_id)

    sections = await build_system_prompt_sections_async(
        session,
        character=character,
        lorebook_ids=chat.active_lorebook_ids or None,
        persona_name=chat.persona_name,
        persona_description=getattr(chat, "persona_description", None),
        story_time=chat.story_time,
        story_location=chat.story_location,
        system_prompt_override=chat.system_prompt_override,
        append_system_prompt=chat.append_system_prompt,
    )

    system_prompt, context = await build_chat_context_async(
        session,
        past_messages,
        character=character,
        lorebook_ids=chat.active_lorebook_ids or None,
        persona_name=chat.persona_name,
        story_time=chat.story_time,
        story_location=chat.story_location,
        system_prompt_override=chat.system_prompt_override,
        append_system_prompt=chat.append_system_prompt,
        persona_description=getattr(chat, "persona_description", None),
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
def update_chat(chat_id: str, data: UpdateChatRequest, session: Session = Depends(get_session)):
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    update_fields = data.model_dump(exclude_unset=True)
    changed_state = {}
    if "story_time" in update_fields and update_fields["story_time"] != chat.story_time:
        changed_state["time"] = update_fields["story_time"]
        changed_state["old_time"] = chat.story_time
    if "story_location" in update_fields and update_fields["story_location"] != chat.story_location:
        changed_state["location"] = update_fields["story_location"]
        changed_state["old_location"] = chat.story_location
    for key, value in update_fields.items():
        setattr(chat, key, value)
    chat.updated_at = datetime.now(timezone.utc)
    session.add(chat)
    session.commit()
    session.refresh(chat)

    if changed_state:
        _insert_world_state_marker(session, chat_id, changed_state)

    return chat

# ---------------------------------------------------------------------------
# Helper: resolve default LLM model id from llm_config.json
# ---------------------------------------------------------------------------
from services.llm_config import get_default_llm_model as _get_default_llm_model

# ---------------------------------------------------------------------------
# Helper: resolve effective context window for a chat
# ---------------------------------------------------------------------------
_DEFAULT_CONTEXT_TOKENS = 4096

def _resolve_context_tokens(chat) -> int:
    """Return the effective max context tokens: per-chat → global setting → 4096."""
    if chat.max_context_tokens and chat.max_context_tokens > 0:
        return chat.max_context_tokens
    try:
        from config import get_config
        cfg = get_config() or {}
        ai_cfg = cfg.get("ai", {})
        val = ai_cfg.get("maxContextTokens") or ai_cfg.get("max_context_tokens")
        if val and int(val) > 0:
            return int(val)
    except Exception:
        pass
    return _DEFAULT_CONTEXT_TOKENS


def _insert_world_state_marker(
    session: Session,
    chat_id: str,
    changed: dict,
) -> None:
    """Insert a UI-only world-state divider marker message after a time/location change."""
    parts = []
    if changed.get("location"):
        parts.append(f"Location: {changed['location']}")
    if changed.get("time"):
        parts.append(f"Time: {changed['time']}")
    if not parts:
        return
    marker = Message(
        chat_id=chat_id,
        role=MessageRole.SYSTEM,
        content="\n".join(parts),
        message_metadata={"source": "world_state", **changed},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(marker)
    session.commit()


@router.post("/{chat_id}/messages")
async def add_message(chat_id: str, request: SendMessageRequest, session: Session = Depends(get_session)) -> dict:
    from services.context_builder import build_chat_context_async
    from services.job_queue import queue_manager
    
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
        
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
        past_messages = session.exec(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)).all()
        
        character = None
        if chat.character_id:
            from core.entities import Character
            character = session.get(Character, chat.character_id)
            
        system_prompt, context = await build_chat_context_async(
            session, 
            past_messages, 
            character=character, 
            lorebook_ids=request.lorebook_ids, 
            persona_name=chat.persona_name,
            story_time=chat.story_time,
            story_location=chat.story_location,
            system_prompt_override=chat.system_prompt_override,
            append_system_prompt=chat.append_system_prompt,
            persona_description=getattr(chat, "persona_description", None),
            max_context_tokens=_resolve_context_tokens(chat),
        )
            
        try:
            job_service = get_job_service(session)

            if request.narrate:
                if not chat.allow_narration:
                    raise HTTPException(status_code=400, detail="Narration is disabled for this chat")
                from config import get_system_prompt_blocks
                from services.orchestrator_service import NARRATOR_SYSTEM_PROMPT
                from services.llm_workflow import build_llm_workflow

                narrator_prompt = (get_system_prompt_blocks() or {}).get("narrator") or NARRATOR_SYSTEM_PROMPT

                workflow, metadata = build_llm_workflow(
                    messages=[
                        {"role": "system", "content": narrator_prompt},
                        *context,
                        {"role": "user", "content": f"[Narration request] {message.content}"},
                    ],
                    type_="narrator",
                    chat_id=chat_id,
                    character_id=chat.character_id,
                    character_system_prompt=system_prompt or None,
                    model=chat.llm_model or _get_default_llm_model(),
                    source="narrator",
                )
            else:
                from services.llm_workflow import build_llm_workflow

                workflow, metadata = build_llm_workflow(
                    messages=context,
                    type_="chat_reply",
                    chat_id=chat_id,
                    character_id=chat.character_id,
                    character_system_prompt=system_prompt or None,
                    model=chat.llm_model or _get_default_llm_model(),
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
            raise HTTPException(status_code=500, detail=str(e))

    return {"user_message_id": message.id, "job_id": job_id}

@router.delete("/{chat_id}/messages/{message_id}")
def delete_message(chat_id: str, message_id: str, session: Session = Depends(get_session)):
    message = session.get(Message, message_id)
    if not message or message.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Message not found")
        
    session.delete(message)
    session.commit()
    return {"message": "Message deleted"}

@router.get("/{chat_id}/jobs")
def list_chat_jobs(chat_id: str, session: Session = Depends(get_session)):
    """Recent jobs (LLM + image) assigned to this chat, newest first."""
    from sqlalchemy import JSON
    from core.entities import Job, JobStatus

    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    jobs = session.exec(
        select(Job)
        .where(
            Job.status.in_([JobStatus.PENDING, JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED,
                           JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING,
                           JobStatus.COMPLETED, JobStatus.FAILED]),
            Job.metadata_['chat_id'].as_string() == chat_id,
        )
        .order_by(Job.created_at.desc())
        .limit(30)
    ).all()

    chat_jobs = []
    for job in jobs:
        workflow = job.workflow or {}
        meta = job.metadata_ or {}
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


@router.post("/{chat_id}/messages/{message_id}/swipe", response_model=Message)
def swipe_message(
    chat_id: str,
    message_id: str,
    data: SwipeRequest,
    session: Session = Depends(get_session),
):
    """Navigate between alternate replies for a character message.

    Alternates are stored in message_metadata:
      {"alternates": ["text0", "text1", ...], "active_index": 0}

    The message content is always kept in sync with the active alternate.
    Swiping right moves to the next alternate (or wraps), left moves back.
    Selecting by index picks a specific alternate directly.
    """
    message = session.get(Message, message_id)
    if not message or message.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.role != MessageRole.CHAR:
        raise HTTPException(status_code=400, detail="Only character messages support swipe")

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
            raise HTTPException(status_code=400, detail=f"Invalid index {data.index} (0–{n-1})")
        active_index = data.index
    else:
        raise HTTPException(status_code=400, detail="direction must be left | right | select")

    message.content = alternates[active_index]
    message.message_metadata = {**meta, "alternates": alternates, "active_index": active_index}
    message.updated_at = datetime.now(timezone.utc)
    session.add(message)
    session.commit()
    session.refresh(message)
    return message

class PinMessageRequest(BaseModel):
    pinned: bool


@router.patch("/{chat_id}/messages/{message_id}/pin", response_model=Message)
def pin_message(
    chat_id: str,
    message_id: str,
    data: PinMessageRequest,
    session: Session = Depends(get_session),
):
    """Toggle the pinned state of a message. Pinned messages survive context pruning."""
    message = session.get(Message, message_id)
    if not message or message.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Message not found")
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
    session: Session = Depends(get_session),
):
    message = session.get(Message, message_id)
    if not message or message.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.role not in (MessageRole.USER, MessageRole.CHAR):
        raise HTTPException(status_code=400, detail="Only user and character messages can be edited")
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
    session: Session = Depends(get_session),
):
    """Delete the target message and everything after it (undo mistakes)."""
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    anchor = session.get(Message, req.message_id)
    if not anchor or anchor.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Message not found")

    all_messages = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    ).all()

    to_delete = [m for m in all_messages if m.created_at >= anchor.created_at]
    for m in to_delete:
        session.delete(m)
    session.commit()
    return {"deleted": len(to_delete), "kept": len(all_messages) - len(to_delete)}

@router.post("/{chat_id}/regenerate")
async def regenerate_reply(
    chat_id: str,
    req: RegenerateRequest,
    session: Session = Depends(get_session),
) -> dict:
    """
    Re-run the last user message: delete every message after it, then dispatch
    a fresh reply job mirroring the previous job's agentic settings.
    """
    from core.entities import Job, JobStatus
    from services.context_builder import build_chat_context_async
    from services.job_queue import queue_manager

    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    all_messages = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    ).all()

    anchor = None
    if req.message_id:
        anchor = session.get(Message, req.message_id)
        if not anchor or anchor.chat_id != chat_id:
            raise HTTPException(status_code=404, detail="Message not found")
    else:
        for m in reversed(all_messages):
            if m.role == MessageRole.USER:
                anchor = m
                break

    if not anchor:
        raise HTTPException(status_code=400, detail="No user message to regenerate")

    anchor_index = next(i for i, m in enumerate(all_messages) if m.id == anchor.id)
    trailing = all_messages[anchor_index + 1:]
    for m in trailing:
        session.delete(m)
    session.commit()

    # Mirror the previous chat_reply job's agentic settings if available.
    prev_agentic = False
    prev_checkpoint = None
    recent_jobs = session.exec(
        select(Job).where(Job.task_type == "llm").order_by(Job.created_at.desc()).limit(200)
    ).all()
    for job in recent_jobs:
        meta = job.metadata_ or {}
        wf = job.workflow or {}
        if meta.get("chat_id") == chat_id and (wf.get("type") or meta.get("type")) == "chat_reply":
            prev_agentic = bool(meta.get("agentic"))
            prev_checkpoint = meta.get("generator_checkpoint")
            break

    remaining = [m for m in all_messages[: anchor_index + 1]]
    character = None
    if chat.character_id:
        character = session.get(Character, chat.character_id)

    system_prompt, context = await build_chat_context_async(
        session,
        remaining,
        character=character,
        lorebook_ids=chat.active_lorebook_ids or None,
        persona_name=chat.persona_name,
        story_time=chat.story_time,
        story_location=chat.story_location,
        system_prompt_override=chat.system_prompt_override,
        append_system_prompt=chat.append_system_prompt,
            persona_description=getattr(chat, "persona_description", None),
        max_context_tokens=_resolve_context_tokens(chat),
    )

    from services.llm_workflow import build_llm_workflow

    workflow, metadata = build_llm_workflow(
        messages=context,
        type_="chat_reply",
        chat_id=chat_id,
        character_id=chat.character_id,
        character_system_prompt=system_prompt or None,
        model=chat.llm_model or _get_default_llm_model(),
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
    if prev_checkpoint:
        metadata["generator_checkpoint"] = prev_checkpoint

    job_service = get_job_service(session)
    try:
        job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
        await queue_manager.enqueue(job.id, task_type="llm")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"job_id": job.id, "removed_messages": len(trailing)}

class ImpersonateRequest(BaseModel):
    hint: str = ""  # Optional direction for the impersonation


@router.post("/{chat_id}/impersonate")
async def impersonate(chat_id: str, req: ImpersonateRequest, session: Session = Depends(get_session)) -> dict:
    """Generate a user-voice message and insert it as a USER turn, then trigger the char reply.

    Unlike /suggest (which streams text into the input box), impersonation inserts
    a completed user message directly and immediately fires the character's response.
    The LLM writes *as the user*, not as the character.
    """
    from services.context_builder import build_system_prompt_sections_async, prune_context
    from services.job_queue import queue_manager
    from config import get_system_prompt_blocks

    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    past_messages = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    ).all()

    character = None
    if chat.character_id:
        character = session.get(Character, chat.character_id)

    user_name = chat.persona_name or "User"
    char_name = character.name if character else "the AI"

    # Build world-state context without character identity (same approach as suggest)
    world_sections = await build_system_prompt_sections_async(
        session,
        character=None,
        lorebook_ids=chat.active_lorebook_ids or None,
        persona_name=chat.persona_name,
        story_time=chat.story_time,
        story_location=chat.story_location,
        include_roleplay_default=False,
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
        imp_job = await job_service.create_job(
            task_type="llm",
            workflow={
                "messages": all_msgs,
                "chat_id": chat_id,
                "type": "impersonate",
                "model": chat.llm_model or _get_default_llm_model(),
            },
            metadata={
                "chat_id": chat_id,
                "workspace": "roleplay",
                "is_impersonation": True,
                "hint": req.hint,
            },
        )
        await queue_manager.enqueue(imp_job.id, task_type="llm")
        return {"job_id": imp_job.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SuggestReplyRequest(BaseModel):
    draft: str | None = None

@router.post("/{chat_id}/suggest")
async def suggest_reply(chat_id: str, req: SuggestReplyRequest, session: Session = Depends(get_session)) -> dict:
    from services.context_builder import build_chat_context
    from services.job_queue import queue_manager
    
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
        
    past_messages = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    ).all()
    
    character = None
    if chat.character_id:
        from core.entities import Character
        character = session.get(Character, chat.character_id)

    from services.context_builder import build_system_prompt_sections_async
    from config import get_system_prompt_blocks

    world_sections = await build_system_prompt_sections_async(
        session,
        character=None,
        lorebook_ids=chat.active_lorebook_ids or None,
        persona_name=chat.persona_name,
        story_time=chat.story_time,
        story_location=chat.story_location,
        include_roleplay_default=False,
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
        suggest_instruction = (
            suggest_instruction
            .replace("{user}", user_name)
            .replace("{{user}}", user_name)
            .replace("{char}", char_name)
            .replace("{{char}}", char_name)
        )
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
        suggest_instruction = (
            suggest_instruction
            .replace("{user}", user_name)
            .replace("{{user}}", user_name)
            .replace("{char}", char_name)
            .replace("{{char}}", char_name)
        )
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
    from services.context_builder import prune_context
    all_msgs = [{"role": "system", "content": suggest_system}] + msg_list
    
    if req.draft and req.draft.strip():
        all_msgs.append({"role": "user", "content": f"[User's rough draft to refine]:\n{req.draft}"})
        
    all_msgs = prune_context(all_msgs, suggest_system, [])

    try:
        job_service = get_job_service(session)
        workflow: dict = {
            "messages": all_msgs,
            "chat_id": chat_id,
            "type": "suggest_reply",
            "model": chat.llm_model or _get_default_llm_model(),
        }
        metadata: dict = {
            "chat_id": chat_id,
            "character_id": chat.character_id,
            "workspace": "roleplay",
            "is_suggestion": True,
        }

        job = await job_service.create_job(
            task_type="llm",
            workflow=workflow,
            metadata=metadata,
        )
        await queue_manager.enqueue(job.id, task_type="llm")
        return {"job_id": job.id}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{chat_id}/scene")
async def generate_scene(
    chat_id: str, 
    session: Session = Depends(get_session),
):
    from services.job_service import JobService
    from services.job_submission_service import JobSubmissionService
    from services.job_queue import queue_manager
    
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
        
    past_messages = session.exec(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)).all()
    if not past_messages:
        raise HTTPException(status_code=400, detail="No messages in chat to base scene on")
        
    context_text = "\n".join([f"{m.role.value}: {m.content}" for m in past_messages[-10:] if m.content])
    
    # Resolve checkpoint: character > user settings > fallback to any installed model
    checkpoint = None
    if chat.character_id:
        character = session.get(Character, chat.character_id)
        if character and character.checkpoint:
            checkpoint = character.checkpoint
    if not checkpoint:
        from services.model_availability_service import ModelAvailabilityService
        checkpoint = ModelAvailabilityService(session).get_available_checkpoint()
    if not checkpoint:
        checkpoint = "sd_xl_base_1.0.safetensors"
    
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
    from services.orchestrator_service import AGENTIC_TOOLS
    prompt_job = await job_service.create_job(
        task_type="llm",
        workflow={
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context:\n{context_text}"}
            ],
            "model": chat.llm_model or _get_default_llm_model(),
            "type": "chat_reply",
            "tools": AGENTIC_TOOLS,
        },
        metadata={
            "source": "scene_prompt",
            "chat_id": chat_id,
            "character_id": chat.character_id,
            "scene_checkpoint": checkpoint,
            "generator_checkpoint": checkpoint,
            "agentic": True,
            "orchestrator_depth": 0,
            "workspace": "roleplay",
        }
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
):
    """Generate an image for the current chat moment without an LLM in the loop.

    Uses the provided prompt, or falls back to the latest character reply when
    no prompt is given. Mirrors the agentic generate_image tool's metadata so
    the image lands in the chat as a kind=IMAGE message via the chat_image
    event (world_integration_service) and in the roleplay workspace.
    """
    from core.workflow_builder import build_image_workflow
    from services.job_queue import queue_manager
    from services.job_service import JobService
    from services.model_availability_service import ModelAvailabilityService

    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if not chat.allow_image_generation:
        raise HTTPException(status_code=400, detail="Image generation is disabled for this chat")

    image_prompt = (request.image_prompt or "").strip()
    if not image_prompt:
        last_char = session.exec(
            select(Message)
            .where(
                Message.chat_id == chat_id,
                Message.role.in_(["char", "assistant"]),
                Message.content.is_not(None),
            )
            .order_by(Message.created_at.desc())
        ).first()
        if last_char and last_char.content.strip():
            image_prompt = last_char.content.strip()
    if not image_prompt:
        raise HTTPException(status_code=400, detail="No prompt and no character reply to illustrate")

    character = session.get(Character, chat.character_id) if chat.character_id else None

    checkpoint = (character.checkpoint if character and character.checkpoint else None)
    if not checkpoint:
        checkpoint = ModelAvailabilityService(session).get_available_checkpoint()
    if not checkpoint:
        checkpoint = "sd_xl_base_1.0.safetensors"

    lora_name = character.lora if character and character.lora else None

    workflow = build_image_workflow(
        prompt=image_prompt,
        checkpoint=checkpoint,
        lora=lora_name,
        filename_prefix="ChatIllustrate",
    )

    metadata: dict = {
        "source": "chat_image",
        "chat_id": chat_id,
        "character_id": chat.character_id,
        "workspace": "roleplay",
        "image_context": image_prompt,
        "prompt": image_prompt,
        "checkpoint": checkpoint,
        "steps": 20,
        "cfg": 7,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 1024,
        "height": 1024,
        "seed": 0,
    }
    if lora_name:
        metadata["loras"] = [lora_name]

    job_service = JobService(session)
    job = await job_service.create_job(
        task_type="image",
        workflow=workflow,
        metadata=metadata,
    )
    await queue_manager.enqueue(job.id, task_type="image")
    return {"job_id": job.id, "status": "queued", "message": "Illustration started"}


@router.get("/{chat_id}/images")
def list_chat_images(chat_id: str, session: Session = Depends(get_session)):
    """List all images attached to messages in this chat (workspace gallery)."""
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

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
