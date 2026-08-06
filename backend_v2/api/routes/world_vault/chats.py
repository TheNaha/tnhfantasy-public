from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.deps import get_job_service, get_session
from core.entities import Chat, Character, Message, MessageRole
from core.events import wait_for_job_completion

router = APIRouter()


class UpdateChatRequest(BaseModel):
    name: str | None = None
    character_id: str | None = None
    persona_name: str | None = None
    story_time: str | None = None
    story_location: str | None = None
    active_lorebook_ids: list[str] | None = None
    llm_model: str | None = None
    allow_image_generation: bool | None = None


class CreateChatRequest(BaseModel):
    name: str = "New Chat"
    character_id: str | None = None
    chat_type: str = "roleplay"
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


@router.get("/", response_model=list[Chat])
def list_chats(session: Session = Depends(get_session)):
    return session.exec(select(Chat).order_by(Chat.updated_at.desc())).all()

@router.post("/", response_model=Chat)
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
def list_messages(chat_id: str, session: Session = Depends(get_session)):
    return session.exec(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)).all()


@router.patch("/{chat_id}", response_model=Chat)
def update_chat(chat_id: str, data: UpdateChatRequest, session: Session = Depends(get_session)):
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    update_fields = data.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        setattr(chat, key, value)
    chat.updated_at = datetime.now(timezone.utc)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat

# ---------------------------------------------------------------------------
# Helper: resolve default LLM model id from llm_config.json
# ---------------------------------------------------------------------------
from services.llm_config import get_default_llm_model as _get_default_llm_model


@router.post("/{chat_id}/messages")
async def add_message(chat_id: str, request: SendMessageRequest, session: Session = Depends(get_session)) -> dict:
    from services.context_builder import build_chat_context
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
            
        system_prompt, context = build_chat_context(
            session, 
            past_messages, 
            character=character, 
            lorebook_ids=request.lorebook_ids, 
            persona_name=chat.persona_name,
            story_time=chat.story_time,
            story_location=chat.story_location
        )
            
        try:
            job_service = get_job_service(session)

            workflow: dict = {
                "messages": context,
                "chat_id": chat_id,
                "character_system_prompt": system_prompt or None,
                "type": "chat_reply",
                "model": chat.llm_model or _get_default_llm_model(),
            }
            metadata: dict = {
                "chat_id": chat_id,
                "character_id": chat.character_id,
                "workspace": "roleplay",
            }

            if request.agentic:
                from services.orchestrator_service import AGENTIC_TOOLS
                workflow["tools"] = AGENTIC_TOOLS
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

@router.post("/{chat_id}/suggest")
async def suggest_reply(chat_id: str, session: Session = Depends(get_session)) -> dict:
    from services.context_builder import build_chat_context
    from services.job_queue import queue_manager
    
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
        
    past_messages = session.exec(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)).all()
    
    character = None
    if chat.character_id:
        from core.entities import Character
        character = session.get(Character, chat.character_id)
        
    # We want to guide the LLM to write exactly ONE action or spoken sentence FOR the user.
    system_prompt, context = build_chat_context(
        session, 
        past_messages, 
        character=character, 
        lorebook_ids=None, 
        persona_name=chat.persona_name,
        story_time=chat.story_time,
        story_location=chat.story_location
    )
    
    # Override system prompt to explicitly act as the user
    suggest_prompt = system_prompt + "\n\nCRITICAL INSTRUCTION: You must act as the USER (the person talking to the character). Based on the context, write a single short action or sentence the USER is likely to say or do next. Output ONLY the raw text without wrapping it in quotes or labels."
    
    try:
        job_service = get_job_service(session)
        workflow: dict = {
            "messages": context,
            "chat_id": chat_id,
            "character_system_prompt": suggest_prompt,
            "type": "suggest_reply",
            "model": chat.llm_model or _get_default_llm_model(),
        }
        metadata: dict = {
            "chat_id": chat_id,
            "character_id": chat.character_id,
            "workspace": "roleplay",
            "is_suggestion": True
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
    
    # Resolve checkpoint: character > user settings > fallback
    checkpoint = "sd_xl_base_1.0.safetensors"
    if chat.character_id:
        character = session.get(Character, chat.character_id)
        if character and character.checkpoint:
            checkpoint = character.checkpoint
    
    system_prompt = (
        "You are an AI scene director. Read the following recent roleplay chat context and "
        "write a highly detailed ComfyUI prompt (comma-separated Danbooru tags, lighting, camera angle, subjects) "
        "describing the current visual scene or the main character's action (e.g. a selfie). "
        "Return ONLY the prompt text."
    )
    
    job_service = JobService(session)
    prompt_job = await job_service.create_job(
        task_type="llm",
        workflow={
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context:\n{context_text}"}
            ],
            "model": chat.llm_model or _get_default_llm_model(),
        },
        metadata={"source": "scene_prompt", "chat_id": chat_id, "scene_checkpoint": checkpoint}
    )
    await queue_manager.enqueue(prompt_job.id, task_type="llm")
    
    # Return immediately — the prompt LLM job will chain into the image job via orchestrator
    # or the frontend can poll. We don't block the request here.
    return {"job_id": prompt_job.id, "status": "queued", "message": "Scene generation started"}
