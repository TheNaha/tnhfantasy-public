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

@router.post("/{chat_id}/messages")
async def add_message(chat_id: str, message: Message, session: Session = Depends(get_session)):
    from core.entities import MessageRole
    from services.job_queue import job_queue
    
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
        
    message.chat_id = chat_id
    message.created_at = datetime.now(timezone.utc)
    message.updated_at = message.created_at
    
    session.add(message)
    session.commit()
    session.refresh(message)
    
    job_id = None
    
    if message.role == MessageRole.USER:
        # Build context from previous messages (excluding the just-saved user message)
        past_messages = session.exec(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)).all()
        context = []
        for msg in past_messages:
            if msg.id == message.id:
                continue
            role = "user" if msg.role == MessageRole.USER else "assistant"
            context.append({"role": role, "content": msg.content})
            
        # Append the new user message
        context.append({"role": "user", "content": message.content})

        # Load character system prompt if character is linked to this chat
        character_system_prompt = None
        if chat.character_id:
            from core.entities import Character
            character = session.get(Character, chat.character_id)
            if character and character.system_prompt:
                character_system_prompt = character.system_prompt
            elif character:
                # Build a basic system prompt from character fields if no explicit one
                parts = [f"You are {character.name}."]
                if character.personality:
                    parts.append(f"Personality: {character.personality}")
                if character.scenario:
                    parts.append(f"Scenario: {character.scenario}")
                character_system_prompt = "\n".join(parts)
            
        try:
            job_service = get_job_service(session)
            job = await job_service.create_job(
                task_type="text",
                workflow={
                    "messages": context,
                    "chat_id": chat_id,
                    "character_system_prompt": character_system_prompt or None,
                    "type": "chat_reply"
                },
                metadata={"chat_id": chat_id}
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
