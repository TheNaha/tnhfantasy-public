from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import Select, func
from sqlmodel import Session, select

from api.deps import get_session, get_chat_repo
from infrastructure.repositories.chat_repo import ChatRepository
from core.entities import Message
from core.exceptions import NotFoundError, ValidationError

router = APIRouter()

# Row caps for the branch endpoints. Both used to operate on the whole chat:
# the read handed the client every message with its full `content` and
# `alternates` array, and the write copied all of them in one transaction. A
# long roleplay chat reaches thousands of messages, so both are bounded now.
#
# The numbers are sized for what the UI renders — a branch tree for a single
# conversation. 500 rows is a few hundred KB worst case and covers almost every
# chat (chat history itself is hard-capped at 5000 by CHAT_HISTORY_HARD_CAP in
# services/chats.py), and 2000 is the ceiling a client can explicitly ask for.
BRANCH_PAGE_DEFAULT_LIMIT = 500
BRANCH_PAGE_MAX_LIMIT = 2000
# Same ceiling as the read: create_branch refuses rather than silently copying
# a prefix, so its worst case is one 2000-row insert in a single transaction.
BRANCH_COPY_MAX_MESSAGES = 2000


def _set_pagination_headers(response: Response, *, total: int, limit: int, offset: int) -> None:
    """Advertise truncation on a list response.

    The body stays a bare JSON array because that is the shape
    `frontend_v2/src/components/chat/ChatTimeline.jsx` iterates
    (`branches.map(...)`) and `useBranches.js` reads
    (`Array.isArray(query.data)`); wrapping it in an object crashes that
    component. Headers carry the pagination contract instead, so a client can
    always tell a truncated page from a complete one.
    """
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    response.headers["X-Has-More"] = "true" if offset + limit < total else "false"


@router.get("/{chat_id}/branches")
def list_branches(
    chat_id: str,
    response: Response,
    limit: int = Query(default=BRANCH_PAGE_DEFAULT_LIMIT, ge=1, le=BRANCH_PAGE_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), ):
    """Return branch roots and their alternates for a chat, newest page first.

    A "branch root" is a message that has children (alternates or replies in
    a different branch). The response groups messages by branch_id.

    Pagination is message-level, so a branch can straddle a page boundary and
    appear in more than one page. `limit` defaults to
    BRANCH_PAGE_DEFAULT_LIMIT and is capped at BRANCH_PAGE_MAX_LIMIT; the
    response headers X-Total-Count / X-Has-More / X-Limit / X-Offset say
    whether the page is the whole chat.
    """
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    total = session.exec(
        select(func.count()).select_from(Message).where(Message.chat_id == chat_id)
    ).one()

    messages = session.exec(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at, Message.id)  # id tie-breaks equal timestamps so pages do not overlap
        .offset(offset)
        .limit(limit)
    ).all()

    _set_pagination_headers(response, total=total, limit=limit, offset=offset)

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


def _copy_candidates(
    session: Session, chat_id: str, anchor: Message, anchor_branch: str
) -> tuple[list[Message], Select[tuple[int]]]:
    """Messages create_branch would copy, at most BRANCH_COPY_MAX_MESSAGES + 1.

    The +1 is the overflow probe: fetching one row past the cap is what lets the
    caller refuse an over-long branch without first materialising all of it.
    The second element is the matching COUNT, used only to report the real
    number when the cap is exceeded.
    """
    count = (
        select(func.count())
        .select_from(Message)
        .where(Message.chat_id == chat_id)
        .where(Message.branch_id == anchor_branch)  # type: ignore
        .where(Message.created_at <= anchor.created_at)
    )
    rows = session.exec(
        select(Message)
        .where(Message.chat_id == chat_id)
        .where(Message.branch_id == anchor_branch)  # type: ignore
        .where(Message.created_at <= anchor.created_at)
        .order_by(Message.created_at, Message.id)
        .limit(BRANCH_COPY_MAX_MESSAGES + 1)
    ).all()
    if rows:
        return list(rows), count

    # The original thread carries no branch_id on its rows, so fall back to the
    # original thread's messages up to the anchor.
    #
    # The `branch_id IS NULL` predicate is load-bearing, not redundant. Branch
    # copies share their originals' `chat_id` AND `created_at`, so an unfiltered
    # "everything in the chat up to the anchor" also matched every message of
    # every PREVIOUSLY created branch. Branching from the main thread therefore
    # silently merged every other branch into the new one, retagged with the new
    # branch_id, and corrupted the tree — with no error anywhere.
    #
    # It also has to be `IS NULL` and not `!= anchor.id`, which is the same
    # convention `_branch_scope` in `chats.py` uses, so "the original thread"
    # means one thing across the module.
    original_thread = Message.branch_id.is_(None)
    count = (
        select(func.count())
        .select_from(Message)
        .where(Message.chat_id == chat_id)
        .where(original_thread)
        .where(Message.created_at <= anchor.created_at)
    )
    fallback = session.exec(
        select(Message)
        .where(Message.chat_id == chat_id)
        .where(original_thread)
        .where(Message.created_at <= anchor.created_at)
        .order_by(Message.created_at, Message.id)
        .limit(BRANCH_COPY_MAX_MESSAGES + 1)
    ).all()
    return list(fallback), count


@router.post("/{chat_id}/branches")
def create_branch(
    chat_id: str,
    data: CreateBranchRequest,
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), ):
    """Create a new conversation branch from a message.

    The new branch starts as a copy of the conversation up to `message_id`,
    allowing the user to continue from that point with different responses.
    Returns the new branch_id and the first message in the new branch.

    Bounded by BRANCH_COPY_MAX_MESSAGES, the same ceiling as the branch read.
    Exceeding it is a 400 with the real copy count, not a silent truncation —
    a branch cut off mid-conversation is a corrupt branch, and a half-built
    one is worse than a refusal.
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

    # Copy the messages from the anchor's branch up to and including the anchor
    # into the new branch, keeping the same content but new IDs.
    old_to_new: dict[str, str] = {}
    anchor_branch = anchor.branch_id or anchor.id

    branch_msgs, copy_count = _copy_candidates(session, chat_id, anchor, anchor_branch)

    if len(branch_msgs) > BRANCH_COPY_MAX_MESSAGES:
        total = session.exec(copy_count).one()
        raise ValidationError(
            message=(
                f"Branching from this message would copy {total} messages, over the "
                f"{BRANCH_COPY_MAX_MESSAGES}-message limit. Branch from a later message, "
                "or start a new chat."
            ),
            field="message_id",
        )

    for msg in branch_msgs:
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
