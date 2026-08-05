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


class CreateChatRequest(BaseModel):
    name: str = "New Chat"
    character_id: str | None = None
    chat_type: str = "roleplay"
    persona_name: str | None = None
    override_greeting: str | None = None


class SendMessageRequest(BaseModel):
    role: MessageRole
    content: str
    image_path: str | None = None
    lorebook_ids: list[str] | None = None
    agentic: bool = False
    generator_checkpoint: str | None = None


@router.get("/", response_model=list[Chat])
def list_chats(session: Session = Depends(get_session)):
    return session.exec(select(Chat).order_by(Chat.updated_at.desc())).all()

@router.post("/", response_model=Chat)
async def create_chat(req: CreateChatRequest, session: Session = Depends(get_session)):
    chat = Chat(
        name=req.name,
        character_id=req.character_id,
        chat_type=req.chat_type,
        persona_name=req.persona_name
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
    
    if message.role == MessageRole.USER:
        past_messages = session.exec(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)).all()
        
        character = None
        if chat.character_id:
            from core.entities import Character
            character = session.get(Character, chat.character_id)
            
        system_prompt, context = build_chat_context(
            session, past_messages, character=character, lorebook_ids=request.lorebook_ids, persona_name=chat.persona_name
        )
            
        try:
            job_service = get_job_service(session)

            workflow: dict = {
                "messages": context,
                "chat_id": chat_id,
                "character_system_prompt": system_prompt or None,
                "type": "chat_reply",
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

@router.post("/{chat_id}/scene")
async def generate_scene(
    chat_id: str, 
    session: Session = Depends(get_session),
):
    from services.job_service import JobService
    from services.job_submission_service import JobSubmissionService
    
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
        
    past_messages = session.exec(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)).all()
    if not past_messages:
        raise HTTPException(status_code=400, detail="No messages in chat to base scene on")
        
    context_text = "\n".join([f"{m.role.value}: {m.content}" for m in past_messages[-10:] if m.content])
    
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
            ]
        },
        metadata={"source": "scene_prompt"}
    )
    await queue_manager.enqueue(prompt_job.id, task_type="llm")
    
    enriched_prompt = "beautiful scenery, masterpiece, high quality, 1girl, highly detailed"
    status_str, output = await wait_for_job_completion(prompt_job.id, timeout=120.0)
    if status_str == "completed" and output:
        enriched_prompt = output.get("content", enriched_prompt)
        
    submission_service = JobSubmissionService(session)
    
    image_workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 0,
                "steps": 20,
                "cfg": 7,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0]
            }
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": "sd_xl_base_1.0.safetensors"
            }
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "batch_size": 1,
                "width": 1024,
                "height": 1024
            }
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": enriched_prompt,
                "clip": ["4", 1]
            }
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "worst quality, low quality, bad anatomy, bad hands, missing fingers",
                "clip": ["4", 1]
            }
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2]
            }
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "ComfyUI",
                "images": ["8", 0]
            }
        }
    }
    
    img_job = await submission_service.create_and_enqueue_job(
        workflow=image_workflow,
        metadata={
            "chat_id": chat_id,
            "character_id": chat.character_id,
            "image_context": "*A photo of the scene was taken*",
            "prompt": enriched_prompt
        }
    )
    
    return {"job_id": img_job.id, "prompt": enriched_prompt}
