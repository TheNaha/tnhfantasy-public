from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from datetime import datetime, timezone

from api.deps import get_session
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

@router.post("/{chat_id}/messages", response_model=Message)
def add_message(chat_id: str, message: Message, session: Session = Depends(get_session)):
    chat = session.get(Chat, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
        
    message.chat_id = chat_id
    message.created_at = datetime.now(timezone.utc)
    message.updated_at = message.created_at
    
    session.add(message)
    
    chat.updated_at = message.created_at
    session.add(chat)
    
    session.commit()
    session.refresh(message)
    return message

@router.delete("/{chat_id}/messages/{message_id}")
def delete_message(chat_id: str, message_id: str, session: Session = Depends(get_session)):
    message = session.get(Message, message_id)
    if not message or message.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Message not found")
        
    session.delete(message)
    session.commit()
    return {"message": "Message deleted"}
