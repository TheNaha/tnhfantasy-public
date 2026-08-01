from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.deps import get_job_service, get_session
from core.entities import Chat, Message

router = APIRouter()

@router.get("/", response_model=list[Chat])
def list_chats(session: Session = Depends(get_session)):
    return session.exec(select(Chat).order_by(Chat.updated_at.desc())).all()

@router.post("/", response_model=Chat)
def create_chat(chat: Chat, session: Session = Depends(get_session)):
    chat.created_at = datetime.now(timezone.utc)
    chat.updated_at = chat.created_at
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat

@router.get("/{chat_id}", response_model=Chat)
def get_chat(chat_id: str, session: Session = Depends(get_session)):
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat

@router.delete("/{chat_id}")
def delete_chat(chat_id: str, session: Session = Depends(get_session)):
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Delete associated messages first
    messages = session.exec(select(Message).where(Message.chat_id == chat_id)).all()
    for msg in messages:
        session.delete(msg)
        
    session.delete(chat)
    session.commit()
    return {"message": "Chat deleted"}

# Message endpoints
@router.get("/{chat_id}/messages", response_model=list[Message])
def list_messages(chat_id: str, session: Session = Depends(get_session)):
    return session.exec(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)).all()


from pydantic import BaseModel

from core.entities import MessageRole


class SendMessageRequest(BaseModel):
    role: MessageRole
    content: str
    image_path: str | None = None
    lorebook_ids: list[str] | None = None

@router.patch("/{chat_id}", response_model=Chat)
def update_chat(chat_id: str, data: dict, session: Session = Depends(get_session)):
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    allowed = {"name", "character_id"}
    for key, value in data.items():
        if key in allowed:
            setattr(chat, key, value)
    chat.updated_at = datetime.now(timezone.utc)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return chat

@router.post("/{chat_id}/messages")
async def add_message(chat_id: str, request: SendMessageRequest, session: Session = Depends(get_session)):
    from core.entities import MessageRole
    from services.context_builder import build_chat_context
    from services.job_queue import job_queue
    
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
            session, past_messages, character=character, lorebook_ids=request.lorebook_ids
        )
            
        try:
            job_service = get_job_service(session)
            job = await job_service.create_job(
                task_type="text",
                workflow={
                    "messages": context,
                    "chat_id": chat_id,
                    "character_system_prompt": system_prompt or None,
                    "type": "chat_reply"
                },
                metadata={"chat_id": chat_id, "character_id": chat.character_id, "workspace": "roleplay"}
            )
            
            await job_queue.enqueue(job.id)
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
    import asyncio

    from api.deps import get_job_submission_service
    from core.entities import JobStatus
    from services.job_service import JobService
    
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
        task_type="text",
        workflow={
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context:\n{context_text}"}
            ]
        },
        metadata={"source": "scene_prompt"}
    )
    
    # Wait for LLM
    enriched_prompt = "beautiful scenery, masterpiece, high quality, 1girl, highly detailed"
    for _ in range(30):
        status = await job_service.get_job(prompt_job.id)
        if status.status == JobStatus.COMPLETED:
            if status.outputs and len(status.outputs) > 0:
                enriched_prompt = status.outputs[0].get("content", enriched_prompt)
            break
        elif status.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            break
        await asyncio.sleep(1.0)
        
    # Submit image job
    submission_service = get_job_submission_service(session)
    # Build a simple SDXL/SD1.5 workflow block - we will assume default workflow for now.
    # Actually, we can use the default workflow logic from generator store, but backend needs it.
    # To keep it simple, we use the fallback text2img workflow:
    
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
            "image_context": "*A photo of the scene was taken*",
            "prompt": enriched_prompt
        }
    )
    
    return {"job_id": img_job.id, "prompt": enriched_prompt}
