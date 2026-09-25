from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from api.deps import get_session, get_chat_repo
from infrastructure.repositories.chat_repo import ChatRepository
from core.entities import Message
from core.exceptions import NotFoundError

router = APIRouter()


@router.get("/{chat_id}/branches")
def list_branches(
    chat_id: str,
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), ):
    """Return all branch roots and their alternates for a chat.

    A "branch root" is a message that has children (alternates or replies in
    a different branch). The response groups messages by branch_id.
    """
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    messages = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    ).all()

    branches: dict[str, list] = {}
    branch_order = []
    for msg in messages:
        bid = msg.branch_id or msg.id
        if bid not in branches:
            branches[bid] = []
            branch_order.append(bid)
        branches[bid].append({
            "id": msg.id,
            "content": msg.content,
            "role": msg.role.value,
            "branch_name": msg.branch_name or "Original",
            "parent_id": msg.parent_id,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "alternates": msg.message_metadata.get("alternates") if msg.message_metadata else None,
        })

    return [
        {"branch_id": bid, "messages": branches[bid]}
        for bid in branch_order
    ]


from pydantic import BaseModel


class CreateBranchRequest(BaseModel):
    message_id: str
    branch_name: str | None = None


@router.post("/{chat_id}/branches")
def create_branch(
    chat_id: str,
    data: CreateBranchRequest,
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), ):
    """Create a new conversation branch from a message.

    The new branch starts as a copy of the conversation up to `message_id`,
    allowing the user to continue from that point with different responses.
    Returns the new branch_id and the first message in the new branch.
    """
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    message_id = data.message_id
    anchor = session.get(Message, message_id)
    if not anchor or anchor.chat_id != chat_id:
        raise NotFoundError("Message", message_id)

    new_branch_id = str(uuid4())
    branch_name = data.branch_name or f"Branch {datetime.now(timezone.utc).strftime('%H:%M')}"

    # Copy all messages from the anchor's branch up to and including the anchor
    # into the new branch, keeping the same content but new IDs.
    old_to_new: dict[str, str] = {}
    anchor_branch = anchor.branch_id or anchor.id

    branch_msgs = session.exec(
        select(Message)
        .where(Message.chat_id == chat_id)
        .where(Message.branch_id == anchor_branch)  # type: ignore
        .order_by(Message.created_at)
    ).all()

    if not branch_msgs:
        branch_msgs = session.exec(
            select(Message)
            .where(Message.chat_id == chat_id)
            .where(Message.created_at <= anchor.created_at)
            .order_by(Message.created_at)
        ).all()

    for msg in branch_msgs:
        if msg.id != anchor.id and msg.created_at > anchor.created_at:
            break  # Stop at the anchor; ignore descendants past it
        new_id = str(uuid4())
        old_to_new[msg.id] = new_id
        new_msg = Message(
            id=new_id,
            chat_id=chat_id,
            role=msg.role,
            kind=msg.kind,
            character_id=msg.character_id,
            content=msg.content,
            image_path=msg.image_path,
            tool_calls=dict(msg.tool_calls) if msg.tool_calls else None,
            message_metadata=dict(msg.message_metadata) if msg.message_metadata else None,
            pinned=msg.pinned,
            parent_id=old_to_new.get(msg.parent_id) if msg.parent_id else None,
            branch_id=new_branch_id,
            branch_name=branch_name,
            created_at=msg.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        session.add(new_msg)

    session.commit()

    # Return the last message in the new branch (the anchor copy)
    last_new_id = list(old_to_new.values())[-1] if old_to_new else None
    return {
        "branch_id": new_branch_id,
        "branch_name": branch_name,
        "anchor_message_id": anchor.id,
        "new_first_message_id": list(old_to_new.values())[0] if old_to_new else None,
        "new_anchor_message_id": last_new_id,
    }


@router.get("/{chat_id}/messages/{message_id}/alternates")
def get_alternates(
    chat_id: str,
    message_id: str,
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), ):
    """Get all alternate replies for a character message (the swipe alternates)."""
    msg = session.get(Message, message_id)
    if not msg or msg.chat_id != chat_id:
        raise NotFoundError("Message", message_id)

    meta = msg.message_metadata or {}
    alternates = meta.get("alternates")
    active = meta.get("active_index", 0)

    return {
        "message_id": msg.id,
        "alternates": alternates or [],
        "active_index": active,
        "content": msg.content,
    }
