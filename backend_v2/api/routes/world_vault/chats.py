from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from datetime import datetime, timezone

from api.deps import get_session, get_job_service
from core.entities import Chat, Message

router = APIRouter()

@router.get("/", response_model=List[Chat])
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
@router.get("/{chat_id}/messages", response_model=List[Message])
def list_messages(chat_id: str, session: Session = Depends(get_session)):
    return session.exec(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)).all()

from pydantic import BaseModel
from typing import Optional, List
from core.entities import MessageRole

class SendMessageRequest(BaseModel):
    role: MessageRole
    content: str
    image_path: Optional[str] = None
    lorebook_ids: Optional[List[str]] = None

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
    from services.job_queue import job_queue
    from services.context_builder import build_chat_context
    
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
