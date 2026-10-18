import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select
from sqlalchemy import func, delete

from api.deps import get_session, get_chat_repo, get_message_repo, get_character_repo, get_location_repo, get_story_repo, get_job_service
from infrastructure.repositories.chat_repo import ChatRepository
from infrastructure.repositories.message_repo import MessageRepository
from infrastructure.repositories.character_repo import CharacterRepository
from infrastructure.repositories.location_repo import LocationRepository
from infrastructure.repositories.story_repo import StoryRepository
from services.reference_cleanup import scrub_entity_references
from core.entities import (
    ACTIVE_JOB_STATUSES,
    Chat,
    Character,
    Job,
    JobStatus,
    Message,
    MessageKind,
    MessageRole,
    Persona,
    Scenario,
    Story,
    StoryChapter,
    VoiceModel,
)
from core.exceptions import ComfyError, NotFoundError, ValidationError
from core.sql_search import LIKE_ESCAPE_CHAR, like_contains
from core.upload_validation import (
    MAX_CARD_SIZE_MB,
    read_upload_bounded,
    require_declared_size,
)
from services.chat_utils import (
    insert_world_state_marker,
    link_embedded_lorebook,
    resolve_scenario_defaults,
    resolve_voice_for_character,
    substitute_tavern_vars,
)
from services.context_builder import (
    speaker_context,
    build_context,
    llm_turn_for,
    prune_context,
)
from services.job_submission_service import submit_llm_job, submit_tts_job
from services.orchestrator_service import (
    TOOL_BUDGETS,
    budget_metadata_for,
    get_tool_max,
)

# Every costed tool name, for the trace's budget block. Read from the table so a
# new costed tool appears in the inspector without a second list to update.
TOOL_NAMES = frozenset(TOOL_BUDGETS)
from services.llm_workflow import build_chat_llm_workflow, sampler_overrides
from services.world_ownership import link_to_world, require_world
from config import settings
from infrastructure.logging import get_logger

# Same convention as the sibling route modules (`lorebooks.py`, `memories.py`).
logger = get_logger("chats_route")

MAX_CONTEXT_MESSAGES = 200
# Hard cap for endpoints that stream an entire chat history into memory
# (rollback, regenerate, swipe). Bounds RAM on multi-year single-user campaigns
# without affecting normal context-window behavior.
CHAT_HISTORY_HARD_CAP = 5000
# Chat exports are JSON/JSONL text; 25 MB is far beyond any real campaign and
# keeps a hostile upload from exhausting memory during decode.
MAX_CHAT_IMPORT_BYTES = MAX_CARD_SIZE_MB * 1024 * 1024
# One chat row is small, but the list is unbounded by default if a caller asks
# for more than a page; `list_messages` allows 1000, so the chat list allows
# fewer — it is a navigation list, not a fetch.
MAX_CHAT_PAGE_SIZE = 200
# Ceiling on the chat-list `q` search term, in characters. An ILIKE against the
# chat table's title and character names; unbounded before, and the reader is
# unauthenticated.
MAX_SEARCH_LENGTH = 200

# Distinguishes "no world_id in this PATCH" from "detach from the world".
_WORLD_ID_UNSET = object()

router = APIRouter()


def _branch_scope(anchor: Message) -> tuple:
    """Restrict a query to the branch the anchor message belongs to.

    Branch copies are written with the *same* `chat_id` and the *same*
    `created_at` as the messages they were copied from (see branches.py), so a
    predicate on `chat_id` + `created_at` alone matches every branch. Rollback
    and regenerate would then delete an unrelated branch the user spent real
    tokens building. `branch_id IS NULL` is the original thread, so the
    `is_(None)` arm is what keeps branch-free chats behaving exactly as before.
    """
    if anchor.branch_id is None:
        return (Message.branch_id.is_(None),)
    return (Message.branch_id == anchor.branch_id,)


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


def _chat_context_prep_sync(
    session: Session, chat_repo: ChatRepository, chat_id: str
) -> tuple[Chat, list[Message], list]:
    """Load a chat, its context window and its characters.

    Synchronous on purpose: the routes that need it also await the context
    builder, so they cannot become plain `def` routes and these reads would
    otherwise run on the event loop. See `get_chat_system_prompt`.
    """
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

    return chat, past_messages, characters



def _model_for_kind(kind: str, override: str | None, session):
    """Resolve the model for a job kind, honouring a per-chat/Story pin.

    Declared here so the ~15 call sites in this module stay short, but the
    decision itself is `services.llm_config.model_for_kind` — the single
    authority shared with the story routes.
    """
    from services.llm_config import model_for_kind

    return model_for_kind(kind, override, session)


class UpdateChatRequest(BaseModel):
    name: str | None = None
    # See `CreateChatRequest.world_id`. `None` here means "not supplied" (the
    # field is `exclude_unset`), so a chat is only detached through an explicit
    # empty string, which `update_chat` maps to `None`.
    world_id: str | None = None
    scenario_id: str | None = None
    character_id: str | None = None
    # The group-chat roster. This was missing, and pydantic's default
    # `extra='ignore'` dropped it silently: `ChatContextPanel` PATCHed it and
    # the mutation applied an optimistic cache update, so the add/remove buttons
    # looked like they worked right up until the next refetch, then the roster
    # vanished. Everything downstream read the permanently-`[]` column — the
    # message list, the prompt context builder, the idle simulator, the
    # SillyTavern `group_characters` export and the reference scrubber — so the
    # whole group-chat feature was inert.
    additional_character_ids: list[str] | None = None
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
    # The per-exchange budget columns. Same failure as `additional_character_ids`
    # above, one entity over: the columns and migrations were in place
    # (`entities.py:1376,1381`), `budget_metadata_for` read them, and the
    # stories route whitelisted them, but `UpdateChatRequest` never declared
    # them — so `extra='ignore'` dropped them at the edge. `ChatContextPanel`
    # PATCHed exactly these two keys with an optimistic cache update, which
    # means the two budget sliders looked live and reverted on every refetch,
    # while the chat silently ran on the global `MAX_AGENTIC_*` defaults.
    max_agentic_images: int | None = None
    max_agentic_narrations: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    tts_voice_id: str | None = None
    idle_sim_enabled: bool | None = None
    persona_id: str | None = None
    authors_note: str | None = None
    authors_note_depth: int | None = None
    director_enabled: bool | None = None
    state_snapshot: dict | None = None


class NarrateRequest(BaseModel):
    """Optional per-message TTS voice override."""
    voice_id: str | None = None
    language: str | None = None


class CreateChatRequest(BaseModel):
    name: str = "New Chat"
    # Which World owns this chat. The column existed from the migration that
    # introduced the World entity and nothing ever wrote it, so a World could
    # not own a chat and the world page had no chats to show.
    world_id: str | None = None
    scenario_id: str | None = None
    character_id: str | None = None
    additional_character_ids: list[str] = []
    chat_type: str = "chat"
    persona_name: str | None = None
    override_greeting: str | None = None
    story_time: str | None = None
    story_location: str | None = None
    location_id: str | None = None
    active_lorebook_ids: list[str] = []
    max_agentic_depth: int | None = None
    # See `UpdateChatRequest.max_agentic_images` — a chat that never set its
    # budget could not be given one later without a PUT, which is a worse way
    # to start than editing it.
    max_agentic_images: int | None = None
    max_agentic_narrations: int | None = None
    idle_sim_enabled: bool = False
    persona_id: str | None = None
    director_enabled: bool = True
    state_snapshot: dict | None = None


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
    # Which thread to continue. Omitted means the original thread, which is the
    # same `branch_id IS NULL` convention the message read and `create_branch`
    # use. Without this field a forked thread could be read but never continued:
    # `Message.branch_id` was written by nothing except `create_branch`, so every
    # user message landed in the original thread and the branch stayed frozen at
    # the moment it was cut. The frontend already sends the branch on reads
    # (`useMessages`), so only the write side was missing.
    branch_id: str | None = None
    # One-shot player steering directive to guide the character or scene for this turn
    directive: str | None = None


@router.get("", response_model=list[Chat])
def list_chats(
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo),
    limit: int = Query(50, ge=1, le=MAX_CHAT_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    workspace: str | None = None,
    q: str | None = Query(None, max_length=MAX_SEARCH_LENGTH),):
    # Capped because `list_messages` 380 lines below this one already is, in the
    # same file, with an explicit range check. A bare `limit: int = 50` meant
    # `?limit=100000` read the whole chat table, and a reader had no local signal
    # that the house style is the strict one.
    stmt = select(Chat).order_by(Chat.updated_at.desc()).offset(offset).limit(limit)
    if workspace:
        stmt = stmt.where(Chat.chat_type == workspace)
    if q and q.strip():
        stmt = stmt.where(Chat.name.ilike(like_contains(q.strip()), escape=LIKE_ESCAPE_CHAR))
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
        if not isinstance(active_index, int) or not 0 <= active_index < len(alternates):
            active_index = 0
        entry = {
            "name": _st_speaker_name(msg, chat, char_names),
            "is_user": msg.role == MessageRole.USER,
            "is_system": msg.role == MessageRole.SYSTEM,
            "send_date": msg.created_at.isoformat() if msg.created_at else created.isoformat(),
            "meta": {"tnh_kind": msg.kind.value if msg.kind else None},
            # `alternates` already contains the active text at `active_index` —
            # `swipe_message` appends the new text and sets the index to the end.
            # The old expression, `[msg.content] + [a for a in alternates if a !=
            # msg.content]`, rebuilt the list in a different order while leaving
            # `swipe_id` pointing at the old index, so the exported `swipe_id`
            # addressed a shifted list: ST would show a different reply than the
            # user was looking at. Emitting `alternates` verbatim and deriving
            # `mes` from the index keeps the two consistent.
            "swipes": list(alternates),
            "swipe_id": active_index,
            "mes": alternates[active_index],
            # Round-trips to `Message.pinned` on import. Without it a pinned
            # message came back unpinned, so context that the user had
            # deliberately protected from pruning was prunable after one export.
            "pinned": bool(msg.pinned),
            # `meta` is SillyTavern's own bag; our extras ride in `extra` so a
            # chat authored in ST keeps whatever it already had there.
            "extra": {k: v for k, v in meta.items() if k not in ("alternates", "active_index")},
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
            "active_lorebook_ids": chat.active_lorebook_ids or [],
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
    # Bounded read: a chat export is text, so a huge body is refused after the
    # first over-limit chunk instead of being decoded whole.
    require_declared_size(file, MAX_CHAT_IMPORT_BYTES)
    raw = await read_upload_bounded(file, MAX_CHAT_IMPORT_BYTES)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("Chat file must be UTF-8 encoded") from exc

    if not text.strip():
        raise ValidationError("Chat file is empty")

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

    # The whole persistence half runs in a worker thread: the upload read above
    # forces this route to stay `async def`, and everything below hits the
    # synchronous session.
    return await asyncio.to_thread(
        _import_chat_sync,
        session,
        character_repo,
        name,
        character_id,
        st_format,
        persona_name,
        source_chat,
        raw_messages,
    )


def _import_chat_sync(
    session: Session,
    character_repo: CharacterRepository,
    name: str | None,
    character_id: str | None,
    st_format: bool,
    persona_name: str | None,
    source_chat: dict,
    raw_messages: list[dict],
) -> Chat:
    """Persist a parsed chat export. Runs off the event loop (see `import_chat`)."""
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
        # Keep the imported character's embedded lorebook active in the new chat.
        active_lorebook_ids=link_embedded_lorebook(source_chat.get("active_lorebook_ids"), primary),
    )
    session.add(chat)
    session.flush()

    created_messages: list[Message] = []
    for i, obj in enumerate(raw_messages):
        meta: dict = {}
        pinned = False
        if st_format:
            content = str(obj.get("mes") or "").strip()
            if not content:
                continue
            # SillyTavern keeps the full swipe list in `swipes` and the selected
            # index in `swipe_id`, with `mes` holding the active text. Only `mes`
            # used to be read, so importing a chat this app had exported dropped
            # every alternate and the active index — and since export wrote
            # `swipes` and `swipe_id`, the round trip was lossy in *our* format.
            #
            # `content` is taken from `swipes[swipe_id]` rather than trusting
            # `mes`, because the two can disagree after an edit (see
            # `edit_message`) and `active_index` is the authority in this app.
            # Deriving from the index is what makes the round trip stable.
            swipes = obj.get("swipes")
            if isinstance(swipes, list):
                stripped = [str(s).strip() for s in swipes if str(s).strip()]
                if stripped:
                    swipe_id = obj.get("swipe_id")
                    idx = (
                        swipe_id
                        if isinstance(swipe_id, int) and 0 <= swipe_id < len(stripped)
                        else 0
                    )
                    content = stripped[idx]
                    meta = {"alternates": stripped, "active_index": idx}
            pinned = bool(obj.get("pinned"))
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
            # `extra` is SillyTavern's own metadata bag. Anything under
            # `tnh_kind` came from our exporter; the rest is preserved verbatim so
            # a chat authored in ST keeps whatever it carried.
            extra = obj.get("extra")
            if isinstance(extra, dict):
                for key, value in extra.items():
                    if key == "tnh_kind":
                        continue
                    meta.setdefault(key, value)
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
            # The JSON exporter writes `pinned` and `message_metadata` and the
            # JSON importer read neither, so a JSON round trip also lost the pin
            # state and every swipe. `message_metadata` is passed through rather
            # than re-derived, because it may hold alternates, an active index,
            # agentic flags or a world-state marker we do not want to rebuild.
            pinned = bool(obj.get("pinned"))
            raw_meta = obj.get("message_metadata")
            if isinstance(raw_meta, dict):
                meta = dict(raw_meta)
        created_messages.append(
            Message(
                chat_id=chat.id,
                role=role,
                kind=kind,
                content=content,
                character_id=cid,
                created_at=ts,
                updated_at=ts,
                pinned=pinned,
                message_metadata=meta or None,
            )
        )
    for msg in created_messages:
        session.add(msg)
    session.commit()
    session.refresh(chat)
    return chat


@router.post("", response_model=Chat)
def create_chat(req: CreateChatRequest, session: Session = Depends(get_session), character_repo: CharacterRepository = Depends(get_character_repo)):
    character = None
    persona = None
    scenario = None
    if req.character_id:
        character = character_repo.get(req.character_id)
        if not character:
            raise NotFoundError("Character", req.character_id)
    if req.persona_id:
        persona = session.get(Persona, req.persona_id)
        if not persona:
            raise NotFoundError("Persona", req.persona_id)
    if req.scenario_id:
        scenario = session.get(Scenario, req.scenario_id)
        if not scenario:
            raise NotFoundError("Scenario", req.scenario_id)
    require_world(session, req.world_id)

    # A character card's embedded ("character_book") lorebook is active in every
    # chat with that character, so link it alongside any requested lorebooks.
    active_lorebook_ids = link_embedded_lorebook(req.active_lorebook_ids, character if req.character_id else None)

    story_location = req.story_location or (character.default_location if character and character.default_location else None)
    story_time = req.story_time or (character.default_time if character and character.default_time else None)
    location_id = req.location_id
    if story_location and not location_id:
        from core.entities import Location
        loc_stmt = select(Location).where(func.lower(Location.name) == story_location.strip().lower())
        effective_world_id = req.world_id or (character.world_id if character else None)
        if effective_world_id:
            loc_stmt = loc_stmt.where(Location.world_id == effective_world_id)
        matched_loc = session.exec(loc_stmt).first()
        if matched_loc:
            location_id = matched_loc.id

    additional_chars = _load_characters_ordered(session, None, req.additional_character_ids or [])

    from services.updater_service import seed_initial_state_snapshot
    initial_snapshot = dict(req.state_snapshot or {})
    if character or scenario or req.override_greeting or req.state_snapshot:
        initial_snapshot = seed_initial_state_snapshot(
            character=character,
            scenario=scenario,
            persona=persona,
            persona_name=req.persona_name or (persona.name if persona else None),
            story_location=story_location,
            story_time=story_time,
            override_greeting=req.override_greeting,
            additional_characters=additional_chars,
            existing_snapshot=initial_snapshot,
        )

    chat = Chat(
        name=req.name,
        character_id=req.character_id,
        additional_character_ids=list(req.additional_character_ids or []),
        scenario_id=req.scenario_id,
        chat_type=req.chat_type,
        persona_name=req.persona_name or (persona.name if persona else None),
        persona_description=persona.description if persona and persona.description else None,
        story_time=story_time,
        story_location=story_location,
        location_id=location_id,
        active_lorebook_ids=active_lorebook_ids,
        max_agentic_depth=req.max_agentic_depth,
        max_agentic_images=req.max_agentic_images,
        max_agentic_narrations=req.max_agentic_narrations,
        idle_sim_enabled=req.idle_sim_enabled,
        persona_id=req.persona_id,
        director_enabled=req.director_enabled,
        state_snapshot=initial_snapshot,
    )
    chat.created_at = datetime.now(timezone.utc)
    chat.updated_at = chat.created_at
    link_to_world(session, chat, req.world_id)
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
                persona_description=chat.persona_description or "",
                original=character.description or "",
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
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    # Deletes the messages first, as a direct SQL DELETE plus a flush, so the
    # FK constraint is satisfied before the chat row goes: the ORM unit of work
    # can reorder `session.delete()` calls and issue the chat DELETE ahead of the
    # message DELETEs, which `messages_chat_id_fkey` then rejects. It also drops
    # the world-graph node, which the route's own copy of this never could.
    scrub_entity_references(session, "chat", chat_id)
    session.delete(chat)
    session.commit()
    return {"message": "Chat deleted"}


@router.get("/{chat_id}/messages", response_model=list[Message])
def list_messages(chat_id: str, branch_id: str | None = None, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo),   limit: int = 100, offset: int = 0, q: str | None = Query(None, max_length=MAX_SEARCH_LENGTH), tail: bool = False):
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
    if limit < 1 or limit > 1000:
        raise ValidationError("limit must be between 1 and 1000")
    if offset < 0:
        raise ValidationError("offset must be non-negative")
    query = select(Message).where(Message.chat_id == chat_id)
    if branch_id:
        query = query.where(Message.branch_id == branch_id)
    else:
        # No `branch_id` means "the thread the user is looking at", and the
        # frontend's `activeBranch` is null exactly when that is the original
        # thread (`useMessages` omits the param, and `branch_id IS NULL` is the
        # documented convention — see `_branch_scope`).
        #
        # The filter used to be applied only when a branch was passed, so the
        # main timeline returned EVERY branch's copies as well. Branch copies
        # carry the same `chat_id` and the same `created_at` as their originals
        # (branches.py), so they interleaved into the conversation among equal
        # timestamps, and the same unfiltered read fed the LLM from `add_message`
        # and `_swipe_prep_sync` — the model received the same conversation
        # duplicated and interleaved. `regenerate`/`rollback` were already
        # branch-scoped, which is what made the inconsistency visible.
        query = query.where(Message.branch_id.is_(None))
    if q:
        query = query.where(
            Message.content.ilike(like_contains(q), escape=LIKE_ESCAPE_CHAR)
        )
    if tail:
        rows = list(session.exec(query.order_by(Message.created_at.desc()).offset(offset).limit(limit)).all())
        rows.reverse()
        return rows
    return session.exec(query.order_by(Message.created_at).offset(offset).limit(limit)).all()


@router.get("/{chat_id}/system-prompt")
async def get_chat_system_prompt(chat_id: str, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo)):
    """Return the assembled system prompt (with per-section breakdown) for this chat."""
    from services.context_builder import estimate_tokens

    # The context builders below are awaited, so this route cannot be a plain
    # `def` — but everything they need is read up front, in a worker thread.
    chat, past_messages, characters = await asyncio.to_thread(
        _chat_context_prep_sync, session, chat_repo, chat_id
    )

    # One assembly through the unified context builder.
    system_prompt, context, sections = await asyncio.to_thread(
        build_context, session, "chat", chat, past_messages,
        characters=characters,
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
    # Validate the group roster: every id must resolve, and the primary
    # character must not also sit in it. A dangling id here is not a rendering
    # problem, it silently drops that speaker from the prompt context, so the
    # failure would surface as "the character I added just never replies".
    if "additional_character_ids" in update_fields and update_fields["additional_character_ids"] is not None:
        roster = [cid for cid in update_fields["additional_character_ids"] if cid]
        for cid in roster:
            if not session.get(Character, cid):
                raise NotFoundError("Character", cid)
        if chat.character_id and chat.character_id in roster:
            raise ValidationError("The primary character is already the speaker; it does not need to be in the group roster")
        # Preserve the panel's order, drop duplicates, keep it deterministic.
        update_fields["additional_character_ids"] = list(dict.fromkeys(roster))
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
    # Validate persona_id if provided (null clears the library link)
    if "persona_id" in update_fields and update_fields["persona_id"] is not None:
        persona = session.get(Persona, update_fields["persona_id"])
        if not persona:
            raise NotFoundError("Persona", update_fields["persona_id"])
    if "scenario_id" in update_fields:
        scen_id = (update_fields["scenario_id"] or "").strip() or None
        if scen_id is not None and not session.get(Scenario, scen_id):
            raise NotFoundError("Scenario", scen_id)
        update_fields["scenario_id"] = scen_id
    # An explicit empty string detaches; an unknown id is a 404 rather than a
    # silent drop, so a typo is visible instead of leaving a chat that looks
    # owned and is not. `_UNSET` rather than `None` because `None` is also the
    # answer to "detach" — conflating the two would unlink every world's chat
    # on any unrelated PATCH.
    requested_world_id: str | None | object = _WORLD_ID_UNSET
    if "world_id" in update_fields:
        requested_world_id = (update_fields.pop("world_id") or "").strip() or None
        require_world(session, requested_world_id)
    # Author's-note depth sanity: 0 pins the note to the very end
    if "authors_note_depth" in update_fields and update_fields["authors_note_depth"] is not None:
        if update_fields["authors_note_depth"] < 0 or update_fields["authors_note_depth"] > 100:
            raise ValidationError("authors_note_depth must be between 0 and 100")
    # A per-chat context budget is a *paid prompt size*. The global setting is
    # range-checked (config.py:767, 1024–32768) but this per-chat override
    # bypassed that check entirely and was returned verbatim by
    # `resolve_context_tokens`, so one PATCH could set it to 10**7 and every
    # subsequent send would carry the full 200-message window plus the full
    # system block. Same bounds, same numbers, so the two cannot disagree.
    if "max_context_tokens" in update_fields and update_fields["max_context_tokens"] is not None:
        _tokens = update_fields["max_context_tokens"]
        if _tokens < 1024 or _tokens > 32768:
            raise ValidationError("max_context_tokens must be between 1024 and 32768")
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
    if requested_world_id is not _WORLD_ID_UNSET:
        link_to_world(session, chat, requested_world_id)
    chat.updated_at = datetime.now(timezone.utc)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    if changed_state:
        insert_world_state_marker(session, chat_id, changed_state)

    return chat


# ---------------------------------------------------------------------------
# Model resolution.
#
# `_model_for_kind` is defined above, near the other request-scoped helpers; the
# bare `get_default_llm_model` import that used to live here is used only inside
# `resolve_model_for_kind` now, so a route file never names it directly.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helper: resolve effective context window for a chat
# ---------------------------------------------------------------------------
from services.chat_utils import resolve_context_tokens as _resolve_context_tokens


def _add_message_prep_sync(
    session: Session,
    chat_repo: ChatRepository,
    message_repo: MessageRepository,
    chat_id: str,
    request: SendMessageRequest,
) -> tuple[Message, str, Chat, list[Message], dict | None]:
    """Persist a user message and assemble the context its reply would use.

    Synchronous on purpose: the reply job is awaited, so the route cannot be a
    plain `def` and these writes would otherwise land on the event loop. The
    context is only assembled for a message that will actually get a reply,
    matching what the route used to fetch inline. The new id is returned
    separately because creating the reply job commits, which expires `message`.
    """
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    if request.branch_id and not session.exec(
        select(Message.id)
        .where(Message.chat_id == chat_id, Message.branch_id == request.branch_id)
        .limit(1)
    ).first():
        # A branch id from another chat, or one that was never created, would
        # write the message into a thread no read path can reach and the reply it
        # triggers would never be shown. Refuse instead of orphaning it.
        raise NotFoundError("Message branch", request.branch_id)

    if request.image_path:
        output_root = os.path.realpath(settings.output_dir)
        image_candidate = os.path.realpath(
            request.image_path
            if os.path.isabs(request.image_path)
            else os.path.join(output_root, request.image_path.lstrip("/\\"))
        )
        if os.path.commonpath([image_candidate, output_root]) != output_root:
            raise ValidationError("Image path is outside the output directory")

    # Validated BEFORE the write, not after it. This used to be checked in the
    # route, after `session.commit()` had already persisted the user message —
    # so asking for narration on a chat that has it disabled returned a failure
    # *and* left the message behind. The frontend reads the error as "send
    # failed" and the user sends it again.
    if request.narrate and request.role == MessageRole.USER and not request.no_reply:
        if not chat.allow_narration:
            raise ValidationError("Narration is disabled for this chat")

    message = Message(
        chat_id=chat_id,
        role=request.role,
        content=request.content,
        image_path=request.image_path,
        branch_id=request.branch_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

    session.add(message)
    session.commit()
    session.refresh(message)

    past_messages: list[Message] = []
    ctx_overrides: dict | None = None
    if message.role == MessageRole.USER and not request.no_reply:
        # The most recent MAX_CONTEXT_MESSAGES, fetched newest-first so the
        # database does the limiting. This was `list_by_chat(chat_id)` with no
        # limit — the whole transcript materialised and ORM-instantiated on every
        # send, then handed to `prune_context`, which keeps at most
        # MAX_CONTEXT_MESSAGES of it anyway.
        #
        # `branch_id=message.branch_id` — the thread this message was posted
        # into, not "every message sharing its chat_id". Branch copies carry the
        # originals' `created_at`, so an unfiltered read hands the model the same
        # conversation duplicated and interleaved. The read route was fixed for
        # this; this is the other read of the same data, on the paid path.
        past_messages = message_repo.list_by_chat(
            chat_id,
            limit=MAX_CONTEXT_MESSAGES,
            newest_first=True,
            branch_id=message.branch_id,
        )

        characters = _load_characters_ordered(session, chat.character_id, chat.additional_character_ids or [])

        ctx_overrides = {
            "characters": characters,
            "lorebook_ids": request.lorebook_ids,
            "max_context_tokens": _resolve_context_tokens(chat),
            "active_character_id": request.target_character_id,
        }
    return message, message.id, chat, past_messages, ctx_overrides


@router.post("/{chat_id}/messages")
async def add_message(
    chat_id: str,
    request: SendMessageRequest,
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    message_repo: MessageRepository = Depends(get_message_repo),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    """Send a message and (unless `no_reply`) dispatch the reply job.

    `Idempotency-Key` is opt-in, matching `POST /api/jobs`. Without it a
    double submit is two user rows and two paid LLM jobs: the client guard
    only covers one tab, since network retries and a second tab both bypass it.
    """
    from infrastructure.request_dedup import deduplicated, make_key

    if idempotency_key and idempotency_key.strip():
        # Concurrent identical sends collapse onto one execution. Key includes
        # the chat and the client-supplied key; the request body is not hashed,
        # because a client that resends the same key means the same thought —
        # and a body-keyed guard would make a legitimately repeated message
        # (a "hello" twice) collapse instead of deduplicating a retry.
        dedup_key = make_key("send_message", chat_id, idempotency_key.strip())
        return await deduplicated(
            dedup_key,
            lambda: _send_message(
                session, chat_repo, message_repo, chat_id, request
            ),
        )

    return await _send_message(
        session, chat_repo, message_repo, chat_id, request
    )


async def _send_message(
    session: Session,
    chat_repo: ChatRepository,
    message_repo: MessageRepository,
    chat_id: str,
    request: SendMessageRequest,
) -> dict:
    # Persisting the message and assembling its context are synchronous session
    # work; the reply job below is awaited, so the route stays `async def` and
    # the reads run in a worker thread.
    message, message_id, chat, past_messages, ctx_overrides = await asyncio.to_thread(
        _add_message_prep_sync, session, chat_repo, message_repo, chat_id, request
    )

    job_id = None

    if message.role == MessageRole.USER and not request.no_reply:
        director_decision_dict: dict[str, Any] | None = None
        if getattr(chat, "director_enabled", True) and ctx_overrides is not None:
            try:
                from services.decision_service import DecisionService
                from services.updater_service import record_director_decision

                chars_list = ctx_overrides.get("characters") or []
                primary_char_name = chars_list[0].name if chars_list and getattr(chars_list[0], "name", None) else "Character"
                recent_transcript = [
                    {
                        "role": m.role.value if hasattr(m.role, "value") else str(m.role),
                        "content": m.content or "",
                    }
                    for m in (past_messages or [])[-6:]
                ]
                decision = await DecisionService(session).evaluate_scene(
                    character_name=primary_char_name,
                    user_name=chat.persona_name or "User",
                    story_location=chat.story_location,
                    story_time=chat.story_time,
                    state_snapshot=chat.state_snapshot or {},
                    recent_messages=recent_transcript,
                    last_speaker="user",
                    has_secondary_character=bool(chat.additional_character_ids),
                    allow_image_generation=bool(chat.allow_image_generation),
                    allow_narration=bool(chat.allow_narration),
                )
                director_decision_dict = decision.to_dict()
                updated_snap = await asyncio.to_thread(
                    record_director_decision, session, chat_id, decision
                )
                ctx_overrides["state_snapshot"] = updated_snap

                # Format human-readable pacing directive for the actor LLM
                directive_map = {
                    "continue_conversation": "Continue the dialogue and interaction naturally.",
                    "sensory_detail": "Slow down and emphasize rich sensory, physical, and atmospheric detail.",
                    "escalate_tension": "Escalate dramatic tension, stakes, or emotional intensity.",
                    "advance_time_or_scene": "Advance the scene forward in time or transition to the next beat.",
                    "de_escalate_reflect": "Slow the pace down for emotional reflection, comfort, or aftermath.",
                }
                speed_map = {1: "Slow-motion", 2: "Real-time", 3: "Fast-forward"}
                speed_label = speed_map.get(round(decision.pacing_speed), "Real-time")
                ctx_overrides["director_directive"] = (
                    f"{directive_map.get(decision.pacing_directive, decision.pacing_directive)} "
                    f"(Pacing speed: {speed_label}; Emotional tone: {decision.emotional_tone}; "
                    f"Suggested expression: {decision.character_expression})"
                )

                # Group chat secondary character auto-routing when user didn't pin target_character_id
                if (
                    decision.next_speaker == "secondary_character"
                    and not request.target_character_id
                    and chat.additional_character_ids
                ):
                    ctx_overrides["active_character_id"] = chat.additional_character_ids[0]
            except Exception as dir_exc:
                logger.debug("send_message_director_eval_skipped", chat_id=chat_id, error=str(dir_exc))

        if request.directive and request.directive.strip():
            ctx_overrides["user_directive"] = request.directive.strip()

        # One assembly through the unified context builder, run off the event
        # loop like the previous async builder. The trace is the only record of
        # what THIS reply was actually told.
        context_trace: dict[str, Any] = {}
        system_prompt, context, _sections = await asyncio.to_thread(
            build_context, session, "chat", chat, past_messages,
            trace_out=context_trace, **ctx_overrides,
        )
        if request.directive and request.directive.strip():
            context_trace["user_directive"] = request.directive.strip()
        if director_decision_dict is not None:
            context_trace["director_decision"] = director_decision_dict

        try:
            if request.narrate:
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
                    model=_model_for_kind("narrator", chat.llm_model, session),
                    samplers=sampler_overrides(chat),
                    type_="narrator",
                    source="narrator",
                )
            else:
                # `chat_reply`, not `suggest_reply`. Both kinds currently map to
                # the same "rp" role in `ROLE_BY_KIND`, so the mismatch was
                # invisible — but the primary reply path is a *reply*, and it
                # must not silently follow the suggest/impersonate model if the
                # role table is ever reordered.
                workflow, metadata = build_chat_llm_workflow(
                    messages=context,
                    chat_id=chat_id,
                    character_id=request.target_character_id or chat.character_id,
                    system_prompt=system_prompt or None,
                    model=_model_for_kind("chat_reply", chat.llm_model, session),
                    samplers=sampler_overrides(chat),
                )

            metadata["autonomous_turn_count"] = 1
            metadata["max_autonomous_turns"] = getattr(chat, "max_autonomous_turns", 4) or 4
            metadata["director_autonomy_level"] = getattr(chat, "director_autonomy_level", "balanced") or "balanced"

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
                # The costed-tool caps travel with the depth cap. Both are per
                # exchange, so both have to be decided once, at the start, or the
                # first hop is the only one that knew the limit.
                metadata.update(budget_metadata_for(chat))
                # The resolved caps, on the exchange record, so the inspector can
                # show "3 images allowed" next to the turns that asked for them.
                # Read back off the metadata rather than re-resolved, so what is
                # displayed is what the gate used.
                context_trace["budgets"] = {
                    name: {
                        "spent": 0,
                        "max": get_tool_max(name, metadata=metadata),
                    }
                    for name in TOOL_NAMES
                }

            if request.generator_checkpoint:
                metadata["generator_checkpoint"] = request.generator_checkpoint

            # The exchange record travels on the job, so the handler that writes
            # the reply can put it on the message row. Kept as one blob rather
            # than spread over the metadata, so it has a single name to look for
            # and cannot be confused with a routing field.
            if context_trace:
                metadata["context_trace"] = context_trace

            if message.branch_id:
                # Carried so the reply lands on the thread the question was asked
                # on. `_handle_chat_reply` is the only writer of CHAR messages and
                # it has no other way to know which fork this answer belongs to —
                # without this the branch shows the question and the answer appears
                # in the original thread, so the fork is still not continuable.
                metadata["branch_id"] = message.branch_id

            job = await submit_llm_job(
                session,
                workflow,
                metadata,
            )
            job_id = job.id

        except ComfyError:
            # A domain error keeps its own status and code. Re-wrapping it as a
            # bare `ComfyError` turned every 4xx raised in here into a 500 and
            # discarded the `code`.
            raise
        except Exception as e:
            raise ComfyError(str(e))

    return {
        "user_message_id": message_id,
        "job_id": job_id,
        "director_decision": director_decision_dict if (message.role == MessageRole.USER and not request.no_reply) else None,
        "context_trace": context_trace if (message.role == MessageRole.USER and not request.no_reply) else None,
    }

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
            # Every status except CANCELLED — the jobs a chat owns, including the
            # ones still moving. Built from the shared sets rather than listed
            # inline, which had already dropped RETRYING.
            Job.status.in_([
                JobStatus.PENDING,
                *ACTIVE_JOB_STATUSES,
                JobStatus.COMPLETED,
                JobStatus.FAILED,
            ]),
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


class GenerateSwipeRequest(BaseModel):
    directive: str | None = None


@router.post("/{chat_id}/messages/{message_id}/narrate", response_model=dict)
async def narrate_message(
    chat_id: str,
    message_id: str,
    data: NarrateRequest | None = None,
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    character_repo: CharacterRepository = Depends(get_character_repo),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Trigger a TTS job to narrate a specific message.

    `Idempotency-Key` is opt-in, matching `POST /{chat_id}/messages`. Without it
    a double click is two TTS jobs: there is no client-side guard on the
    narrator button, and `_handle_chat_tts` writes the same `audio_path` twice,
    so the second job's cost is invisible in the UI.
    """
    from infrastructure.request_dedup import deduplicated, make_key

    if idempotency_key and idempotency_key.strip():
        # Key includes the message, so narrating a different message is never
        # collapsed into the first, and a replayed request for the same message
        # returns the first job.
        dedup_key = make_key(
            "narrate_message", chat_id, message_id, idempotency_key.strip()
        )
        return await deduplicated(
            dedup_key,
            lambda: _narrate_message(session, chat_repo, character_repo, chat_id, message_id, data),
        )

    return await _narrate_message(
        session, chat_repo, character_repo, chat_id, message_id, data
    )


async def _narrate_message(
    session: Session,
    chat_repo: ChatRepository,
    character_repo: CharacterRepository,
    chat_id: str,
    message_id: str,
    data: NarrateRequest | None,
):
    # Voice resolution, the capability guard and the graph build are synchronous
    # session work; the job enqueue below is awaited, so they move to a worker
    # thread.
    message_id, workflow, metadata = await asyncio.to_thread(
        _narrate_message_prep_sync,
        session,
        chat_repo,
        character_repo,
        chat_id,
        message_id,
        data,
    )

    job = await submit_tts_job(
        session,
        workflow,
        metadata,
    )

    return {"message_id": message_id, "job_id": job.id}


def _narrate_message_prep_sync(
    session: Session,
    chat_repo: ChatRepository,
    character_repo: CharacterRepository,
    chat_id: str,
    message_id: str,
    data: NarrateRequest | None,
) -> tuple[str, dict, dict]:
    """Load the message and resolve its voice, then build the TTS workflow.

    Synchronous on purpose: the enqueue is awaited, so the route stays
    `async def` and these queries would otherwise run on the event loop.
    """
    from services.tts_workflow_builder import (
        _require_tts_capable,
        build_voice_speak_workflow,
    )

    # The same guard `voices.py` calls, first, before it reads anything or builds
    # a graph. It runs here rather than in the route body because this function
    # is already the route's off-loop prologue, and the guard is a session query.
    # Fail now with a 400 naming the missing capability, instead of accepting a
    # job that dies inside a container naming a node that is not installed.
    _require_tts_capable(session)

    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    message = session.get(Message, message_id)
    if not message or message.chat_id != chat_id:
        raise NotFoundError("Message", message_id)

    if not message.content:
        raise ComfyError("Message has no content to narrate")

    # Resolve voice profile: explicit voice_id → chat override → character voice → scenario default → default
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
    if not voice_profile:
        _, scenario_voice = resolve_scenario_defaults(session, chat)
        if scenario_voice:
            voice_profile = scenario_voice
    if data and data.language:
        language = data.language

    # `build_tts_workflow` emitted `XTTS_v2` + `SaveAudio` node types that exist
    # in no provider image, and the job went out as `task_type="image"`, so it
    # was routed to a worker that could not build its graph. The dedicated TTS
    # worker is a separate provider capability; the graph comes from the builder
    # that targets it, and the metadata keys are unchanged so
    # `_handle_chat_tts` still selects on `source == "chat_tts"`.
    workflow, metadata = build_voice_speak_workflow(
        message.content,
        voice_profile=voice_profile,
        language=language,
        filename_prefix=f"chat_tts/{chat_id}/{message_id}",
        extra_metadata={
            "chat_id": chat_id,
            "character_id": chat.character_id,
            "voice_model_id": voice_model_id,
            "source": "chat_tts",
            "message_id": message_id,
            # `_handle_narrator` is the only writer of narrator messages; without
            # this a narration of a forked thread is written to the original one,
            # where the user reading the fork never sees it.
            "branch_id": message.branch_id,
        },
    )
    return message.id, workflow, metadata


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
    req: GenerateSwipeRequest | None = None,
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo)
) -> dict:
    # Reading up to CHAT_HISTORY_HARD_CAP messages is synchronous session work
    # and the context build below is awaited, so the reads run in a thread.
    chat, remaining, prev_agentic, ctx_overrides = await asyncio.to_thread(
        _swipe_prep_sync, session, chat_repo, chat_id, message_id
    )

    if req and req.directive and req.directive.strip():
        ctx_overrides["user_directive"] = req.directive.strip()

    context_trace: dict[str, Any] = {}
    system_prompt, context, _sections = await asyncio.to_thread(
        build_context, session, "chat", chat, remaining,
        trace_out=context_trace, **ctx_overrides,
    )
    if req and req.directive and req.directive.strip():
        context_trace["user_directive"] = req.directive.strip()


    workflow, metadata = build_chat_llm_workflow(
        messages=context,
        chat_id=chat_id,
        character_id=chat.character_id,
        system_prompt=system_prompt or None,
        model=_model_for_kind("chat_reply", chat.llm_model, session),
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
        # This is a re-generation of a turn the user already has, not a new
        # conversational turn, so it must not trigger memory extraction.
        #
        # The extraction hook fires for every job classified `chat_reply`, and
        # this one is exactly that. `should_extract_memories` counts only USER
        # messages, so a swipe leaves the count unchanged and RE-OPENS the gate —
        # the extractor then runs over a near-identical 20-message window and
        # produces a second copy of the same memories. Deduplication catches the
        # identical case, but a regeneration deletes the messages the window was
        # built from, so the two windows differ and the same fact can come back
        # reworded and slip past an exact match.
        #
        # Suppressing it here is the actual fix; the dedup in
        # `memory_extraction` is the backstop for every other re-run path.
        metadata["suppress_memory_extraction"] = True
        metadata["max_agentic_depth"] = chat.max_agentic_depth or 3
        metadata.update(budget_metadata_for(chat))
        context_trace["budgets"] = {
            name: {"spent": 0, "max": get_tool_max(name, metadata=metadata)}
            for name in TOOL_NAMES
        }

    if context_trace:
        metadata["context_trace"] = context_trace

    job = await submit_llm_job(session, workflow, metadata)
    await asyncio.to_thread(session.commit)

    # Agentic chaining happens when the job completes with tool calls
    # (see job_processing.py) — this route only enqueues the job.

    return {"job_id": job.id}


def _swipe_prep_sync(
    session: Session, chat_repo: ChatRepository, chat_id: str, message_id: str
) -> tuple[Chat, list[Message], bool, dict]:
    """Load the swipe target, the history before it and the context kwargs.

    Synchronous on purpose: the context build and the job enqueue are awaited,
    so the route cannot be a plain `def` and these reads would otherwise run on
    the event loop.
    """
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    target_msg = session.get(Message, message_id)
    if not target_msg or target_msg.chat_id != chat_id:
        raise NotFoundError("Message", message_id)
    if target_msg.role != MessageRole.CHAR:
        raise ValidationError("Only character messages can generate swipes")

    # `_branch_scope(target_msg)`, so a swipe on a forked thread is answered from
    # that thread only. Without it this read matched every branch's copies —
    # they share the originals' `chat_id` and `created_at` — and the paid
    # regeneration was conditioned on the conversation duplicated and
    # interleaved. The message read route was already scoped this way; this is
    # the same data on the paid path.
    all_messages = session.exec(
        select(Message).where(
            Message.chat_id == chat_id,
            *_branch_scope(target_msg),
        ).order_by(Message.created_at.desc()).limit(CHAT_HISTORY_HARD_CAP)
    ).all()
    all_messages.reverse()

    target_index = next((i for i, m in enumerate(all_messages) if m.id == target_msg.id), -1)
    if target_index < 0:
        raise NotFoundError("Message", message_id)

    remaining = all_messages[:target_index]

    characters = _load_characters_ordered(session, chat.character_id, chat.additional_character_ids or [])

    ctx_overrides = {
        "characters": characters,
        "max_context_tokens": _resolve_context_tokens(chat),
    }
    # Mirror agentic state
    prev_agentic = target_msg.tool_calls is not None or (target_msg.message_metadata or {}).get("agentic", False)
    return chat, remaining, prev_agentic, ctx_overrides


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
    directive: str | None = None

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
    # Keep the swipe list in step with the text the user can actually see.
    #
    # This assigned `content` and left `message_metadata` alone, so after an edit
    # the displayed text appeared nowhere in `alternates` while `active_index`
    # still pointed at the old entry. Two things then went wrong:
    #
    #   * the next `swipe_message` does `if content not in alternates:
    #     alternates.insert(0, content)` — so the edited text was pushed to the
    #     FRONT, shifting every stored index by one, and "swipe right" landed on
    #     a different reply than the UI implied;
    #   * the ST export wrote `swipe_id=active_index` against that same shifted
    #     list, so a re-import showed the wrong text as active.
    #
    # Editing IN PLACE is the small change: the user asked to change the message
    # they are looking at, and that is the slot `active_index` already names. It
    # also preserves the other alternates, which replacing the list would throw
    # away, and it makes the `content not in alternates` guard a no-op
    # afterwards, so the shift cannot happen.
    meta = dict(message.message_metadata or {})
    alternates: list[str] = list(meta.get("alternates") or [])
    if alternates:
        idx = meta.get("active_index", 0)
        if not isinstance(idx, int) or not 0 <= idx < len(alternates):
            idx = 0
        alternates[idx] = data.content
        message.message_metadata = {
            **meta,
            "alternates": alternates,
            "active_index": idx,
        }
    message.content = data.content
    message.updated_at = datetime.now(timezone.utc)
    session.add(message)
    session.commit()
    session.refresh(message)
    return message

async def _cancel_inflight_chat_jobs(session: Session, chat_id: str, *, reason: str) -> int:
    """Cancel every LLM job still in flight for `chat_id`. Returns how many.

    The existence check is the one already used by the idle simulator
    (`agent_simulation.py`): `select(Job.id)` with the status set, so it fetches
    ids rather than whole `Job` rows with their `workflow`, `metadata_` and
    `outputs` jsonb. Then the id list is handed to `job_processing.cancel_job`,
    which also signals the provider.

    A job that reached a terminal state between the read and the cancel raises
    `ValidationError` from `cancel_job`. That is the COMMON case for a rollback,
    not an edge case — the reply usually already landed, which is the situation
    the user is rolling back from — so it is swallowed per job. One job failing to
    cancel must not 500 the rollback and leave the conversation half-rewound.
    """
    from services.agent_simulation import IN_FLIGHT_JOB_STATUSES
    from services.job_processing import cancel_job as cancel_job_processing
    from services.job_service import JobService

    in_flight = session.exec(
        select(Job.id).where(
            Job.task_type == "llm",
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
            Job.metadata_["chat_id"].as_string() == chat_id,
        )
    ).all()
    if not in_flight:
        return 0

    job_service = JobService(session)
    cancelled = 0
    for job_id in in_flight:
        try:
            await cancel_job_processing(
                job_service=job_service, job_id=job_id, reason=reason
            )
            cancelled += 1
        except ValidationError:
            # Finished between the read and the cancel. Nothing left to stop.
            continue
        except Exception as exc:
            logger.warning(
                "chat_rollback_job_cancel_failed",
                job_id=job_id, chat_id=chat_id, error=str(exc),
            )
    if cancelled:
        logger.info(
            "chat_rollback_jobs_cancelled", chat_id=chat_id, cancelled=cancelled
        )
    return cancelled


def _rollback_prep_sync(
    session: Session, chat_repo: ChatRepository, chat_id: str, message_id: str | None
):
    """Resolve the anchor and delete from it onward. Returns the deleted count.

    Synchronous on purpose, and for the same reason `_regenerate_prep_sync` is:
    the route has to stay `async def` because it awaits
    `_cancel_inflight_chat_jobs`, and every one of these reads is a synchronous
    SQLModel call. Left inline they run on the event loop, and this route issues
    a bulk DELETE against up to CHAT_HISTORY_HARD_CAP (5000) messages plus a
    commit — the single largest blocking span of any route in this file.
    """
    from sqlalchemy import delete

    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    anchor = session.get(Message, message_id)
    if not anchor or anchor.chat_id != chat_id:
        raise NotFoundError("Message", message_id)

    # Delete at the SQL level — never loads the full chat history into Python.
    result = session.execute(
        delete(Message).where(
            Message.chat_id == chat_id,
            Message.created_at >= anchor.created_at,
            *_branch_scope(anchor),
        )
    )
    deleted = result.rowcount
    session.commit()
    return deleted


@router.post("/{chat_id}/rollback")
async def rollback_chat(
    chat_id: str,
    req: RollbackRequest,
    session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), ):
    """Delete the target message and everything after it (undo mistakes)."""
    # Everything synchronous — the anchor read, the DELETE and the commit — runs
    # in a worker thread, so only the job cancellation below is on the loop.
    deleted = await asyncio.to_thread(
        _rollback_prep_sync, session, chat_repo, chat_id, req.message_id
    )

    # Stop any reply that is still in flight AFTER deleting the messages it is
    # replying to.
    #
    # Neither this nor `regenerate_reply` looked at the job table at all. The
    # user hits undo, the messages are deleted, and twenty seconds later the
    # already-paid job completes and `_handle_chat_reply` appends its reply at
    # the tail — content the user just undid, reappearing with nothing to tell
    # it apart from a new reply. For `regenerate_reply` it is worse: two jobs
    # race, and the loser appends a duplicate.
    #
    # Uses `job_processing.cancel_job` rather than `JobService.cancel_job` so
    # the provider is signalled too. An LLM job mid-generation is
    # mid-generation; cancelling only the local record leaves the token spend
    # running on the provider.
    #
    # Ordered AFTER the delete deliberately: cancelling first would leave a
    # window where the in-flight job's handler re-reads the messages it is about
    # to have removed and appends against a tail that still exists. The delete is
    # committed before the cancel is issued, so a reply that lands between the
    # two finds nothing to append to.
    await _cancel_inflight_chat_jobs(session, chat_id, reason="chat rollback")

    def _kept_count() -> int:
        return session.exec(
            select(func.count(Message.id)).where(Message.chat_id == chat_id)
        ).one()

    kept = await asyncio.to_thread(_kept_count)
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
    # The delete + history load is synchronous session work and the context
    # build below is awaited, so the whole prologue runs in a worker thread.
    chat, anchor_character_id, anchor_branch_id, deleted, prev_agentic, prev_checkpoint, remaining, ctx_overrides = await asyncio.to_thread(
        _regenerate_prep_sync, session, chat_repo, chat_id, req.message_id
    )

    # Before the new job is created, or it would cancel itself. `_regenerate_prep_sync`
    # has already deleted the messages the previous reply was going to answer, so
    # leaving that job running means it completes against a tail that no longer
    # exists and appends a duplicate of the reply we are about to regenerate.
    await _cancel_inflight_chat_jobs(session, chat_id, reason="chat regenerate")

    if req.directive and req.directive.strip():
        ctx_overrides["user_directive"] = req.directive.strip()

    context_trace: dict[str, Any] = {}
    system_prompt, context, _sections = await asyncio.to_thread(
        build_context, session, "chat", chat, remaining,
        trace_out=context_trace, **ctx_overrides,
    )
    if req.directive and req.directive.strip():
        context_trace["user_directive"] = req.directive.strip()


    workflow, metadata = build_chat_llm_workflow(
        messages=context,
        chat_id=chat_id,
        character_id=anchor_character_id or chat.character_id,
        system_prompt=system_prompt or None,
        model=_model_for_kind("chat_reply", chat.llm_model, session),
        samplers=sampler_overrides(chat),
        extra_metadata={
            "regenerated": True,
            # Same reason as the send path: `_handle_chat_reply` has no other way
            # to know which fork the regenerated answer belongs to.
            "branch_id": anchor_branch_id,
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
        # This is a re-generation of a turn the user already has, not a new
        # conversational turn, so it must not trigger memory extraction.
        #
        # The extraction hook fires for every job classified `chat_reply`, and
        # this one is exactly that. `should_extract_memories` counts only USER
        # messages, so a swipe leaves the count unchanged and RE-OPENS the gate —
        # the extractor then runs over a near-identical 20-message window and
        # produces a second copy of the same memories. Deduplication catches the
        # identical case, but a regeneration deletes the messages the window was
        # built from, so the two windows differ and the same fact can come back
        # reworded and slip past an exact match.
        #
        # Suppressing it here is the actual fix; the dedup in
        # `memory_extraction` is the backstop for every other re-run path.
        metadata["suppress_memory_extraction"] = True
        effective_max = chat.max_agentic_depth
        if effective_max is not None:
            metadata["max_agentic_depth"] = effective_max
        metadata.update(budget_metadata_for(chat))
        context_trace["budgets"] = {
            name: {"spent": 0, "max": get_tool_max(name, metadata=metadata)}
            for name in TOOL_NAMES
        }
    if prev_checkpoint:
        metadata["generator_checkpoint"] = prev_checkpoint

    if context_trace:
        metadata["context_trace"] = context_trace

    try:
        await asyncio.to_thread(session.commit)
        job = await submit_llm_job(session, workflow, metadata)
    except ComfyError:
        await asyncio.to_thread(session.rollback)
        raise
    except Exception as e:
        await asyncio.to_thread(session.rollback)
        raise ComfyError(str(e))

    return {"job_id": job.id, "removed_messages": deleted}


def _regenerate_prep_sync(
    session: Session, chat_repo: ChatRepository, chat_id: str, message_id: str | None
) -> tuple[Chat, str | None, str | None, int, bool, object, list[Message], dict]:
    """Drop everything after the anchor message and assemble its context.

    Synchronous on purpose: the context build and the job enqueue are awaited,
    so the route stays `async def` and these deletes/reads would otherwise run
    on the event loop.
    """
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    anchor = None
    if message_id:
        anchor = session.get(Message, message_id)
        if not anchor or anchor.chat_id != chat_id:
            raise NotFoundError("Message", message_id)
    else:
        # Find the most recent user message without scanning full history.
        # `branch_id IS NULL` for the same reason every other read in this file
        # scopes by branch: without it a branch's copy of a user message — same
        # `chat_id`, same `created_at` — can be chosen as the anchor, and the
        # regeneration would then delete the ORIGINAL thread's tail. The request
        # carries no branch, so "the conversation" means the original thread.
        anchor = session.exec(
            select(Message)
            .where(
                Message.chat_id == chat_id,
                Message.role == MessageRole.USER,
                Message.branch_id.is_(None),
            )
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
            *_branch_scope(anchor),
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
        .where(
            Message.chat_id == chat_id,
            Message.created_at <= anchor.created_at,
            *_branch_scope(anchor),
        )
        .order_by(Message.created_at.desc())
        .limit(CHAT_HISTORY_HARD_CAP)
    ).all()
    remaining = list(reversed(recent))
    characters = _load_characters_ordered(session, chat.character_id, chat.additional_character_ids or [])

    ctx_overrides = {
        "characters": characters,
        "max_context_tokens": _resolve_context_tokens(chat),
    }
    return (
        chat,
        getattr(anchor, "character_id", None),
        getattr(anchor, "branch_id", None),
        deleted,
        prev_agentic,
        prev_checkpoint,
        remaining,
        ctx_overrides,
    )


class ImpersonateRequest(BaseModel):
    hint: str = ""  # Optional direction for the impersonation


@router.post("/{chat_id}/impersonate")
async def impersonate(chat_id: str, req: ImpersonateRequest, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), character_repo: CharacterRepository = Depends(get_character_repo)) -> dict:
    """Generate a user-voice message and insert it as a USER turn, then trigger the char reply.

    Unlike /suggest (which streams text into the input box), impersonation inserts
    a completed user message directly and immediately fires the character's response.
    The LLM writes *as the user*, not as the character.
    """
    # The prologue (history, character, world-state kwargs) is synchronous
    # session work and the world-state sections below are awaited, so it runs in
    # a worker thread.
    chat, user_name, char_name, ctx_overrides, past_messages = await asyncio.to_thread(
        _impersonate_prep_sync, session, chat_repo, character_repo, chat_id
    )

    # Build world-state context without character identity (same approach as suggest)
    world_context_str = await asyncio.to_thread(
        build_context, session, "chat", chat, None,
        sections_only=True, **ctx_overrides,
    )

    hint_clause = f" Specifically: {req.hint.strip()}." if req.hint.strip() else ""
    imp_system = (
        f"You are {user_name}, the human participant in this roleplay with {char_name}. "
        f"Write ONE in-character message or action that {user_name} would realistically say or do next.{hint_clause} "
        f"Output ONLY the raw message text — no labels, no quotes around the whole reply."
        + (f"\n\n{world_context_str}" if world_context_str else "")
    )

    # Swap roles for the impersonation LLM call: char→user, user→assistant
    msg_list = []
    # Mirrored, for the same reason as `suggest_reply`: the model writes as
    # the USER, so a prior user message is `assistant` from its seat and a
    # character message is the `user` it answers.
    speaker_names, speaker_total = speaker_context(past_messages, session)
    for msg in past_messages:
        turn = llm_turn_for(
            msg,
            speaker_names=speaker_names,
            participants=max(speaker_total, 1),
            as_user=True,
        )
        if turn is None:
            continue
        if turn["role"] == "system":
            msg_list.append({"role": "user", "content": f"[{turn['content']}]"})
        else:
            msg_list.append(turn)

    all_msgs = [{"role": "system", "content": imp_system}] + msg_list
    all_msgs = prune_context(all_msgs, imp_system, [], _resolve_context_tokens(chat))

    try:
        workflow, metadata = build_chat_llm_workflow(
            messages=all_msgs,
            chat_id=chat_id,
            character_id=chat.character_id,
            model=_model_for_kind("suggest_reply", chat.llm_model, session),
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

        imp_job = await submit_llm_job(
            session,
            workflow,
            metadata,
        )
        return {"job_id": imp_job.id}
    except ComfyError:
        raise
    except Exception as e:
        raise ComfyError(str(e))


def _impersonate_prep_sync(
    session: Session,
    chat_repo: ChatRepository,
    character_repo: CharacterRepository,
    chat_id: str,
) -> tuple[Chat, str, str, dict, list[Message]]:
    """Load everything the impersonation prompt is assembled from.

    Synchronous on purpose: the world-state sections and the job enqueue are
    awaited, so the route stays `async def` and these reads would otherwise run
    on the event loop.
    """
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

    ctx_overrides = {
        "character": None,
        "include_roleplay_default": False,
    }
    return (
        chat,
        chat.persona_name or "User",
        character.name if character else "the AI",
        ctx_overrides,
        past_messages,
    )


class SuggestReplyRequest(BaseModel):
    draft: str | None = None

@router.post("/{chat_id}/suggest")
async def suggest_reply(chat_id: str, req: SuggestReplyRequest, session: Session = Depends(get_session), chat_repo: ChatRepository = Depends(get_chat_repo), character_repo: CharacterRepository = Depends(get_character_repo)) -> dict:

    # The prologue (history, character, world-state kwargs) is synchronous
    # session work and the world-state sections below are awaited, so it runs in
    # a worker thread.
    chat, user_name, char_name, original, ctx_overrides, past_messages = await asyncio.to_thread(
        _suggest_prep_sync, session, chat_repo, character_repo, chat_id
    )

    from config import get_system_prompt_blocks

    world_context_str = await asyncio.to_thread(
        build_context, session, "chat", chat, None,
        sections_only=True, **ctx_overrides,
    )

    # Macro inputs shared by both suggest instructions: SillyTavern config
    # prompts may reference {{persona}} / {{original}} as well as {{user}}.
    macro_ctx = {
        "char": char_name,
        "user": user_name,
        "persona_description": chat.persona_description or "",
        "original": original,
    }

    if req.draft and req.draft.strip():
        # Draft provided: Refine the user's draft
        suggest_instruction = (
            "CRITICAL INSTRUCTION: You are acting as {user}, the human user in this roleplay. "
            "You have written a rough draft of your next message, but you need to refine it. "
            "Rewrite the draft to be more descriptive, in-character, and engaging, while keeping the original intent. "
            "Write only the raw text of the final response — no labels, no quotes around the whole reply, no meta-commentary."
        )
        suggest_instruction = substitute_tavern_vars(suggest_instruction, **macro_ctx)
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
        suggest_instruction = substitute_tavern_vars(suggest_instruction, **macro_ctx)
        suggest_system = (
            f"You are {user_name}, the human participant in the following roleplay conversation "
            f"with {char_name}. Your job is to suggest what {user_name} might say or do next.\n\n"
            + (f"{world_context_str}\n\n" if world_context_str else "")
            + suggest_instruction
        )

    # The same turn mapping as the reply path (`llm_turn_for`), mirrored: this
    # job writes as the USER, so a prior user message is `assistant` from the
    # model's seat and a character message is the `user` it answers. This was a
    # fourth copy of the if/elif, and it was the one that had already drifted —
    # it dropped narrator turns entirely while the reply path sent them as
    # `system`.
    msg_list = []
    speaker_names, speaker_total = speaker_context(past_messages, session)
    for msg in past_messages:
        turn = llm_turn_for(
            msg,
            speaker_names=speaker_names,
            participants=max(speaker_total, 1),
            as_user=True,
        )
        if turn is None:
            continue
        # A plain system turn is an instruction, and from the user's seat it
        # belongs on the `user` channel, bracketed, as before.
        if turn["role"] == "system":
            msg_list.append({"role": "user", "content": f"[{turn['content']}]"})
        else:
            msg_list.append(turn)

    # Prune to stay within context budget
    all_msgs = [{"role": "system", "content": suggest_system}] + msg_list
    
    if req.draft and req.draft.strip():
        all_msgs.append({"role": "user", "content": f"[User's rough draft to refine]:\n{req.draft}"})
        
    all_msgs = prune_context(all_msgs, suggest_system, [], _resolve_context_tokens(chat))

    try:
        workflow, metadata = build_chat_llm_workflow(
            messages=all_msgs,
            chat_id=chat_id,
            character_id=chat.character_id,
            model=_model_for_kind("suggest_reply", chat.llm_model, session),
            samplers=sampler_overrides(chat),
            type_="suggest_reply",
            extra_metadata={"is_suggestion": True, "max_agentic_depth": chat.max_agentic_depth},
        )

        job = await submit_llm_job(
            session,
            workflow,
            metadata,
        )
        return {"job_id": job.id}

    except ComfyError:
        raise
    except Exception as e:
        raise ComfyError(str(e))

def _suggest_prep_sync(
    session: Session,
    chat_repo: ChatRepository,
    character_repo: CharacterRepository,
    chat_id: str,
) -> tuple[Chat, str, str, str, dict, list[Message]]:
    """Load everything the /suggest prompt is assembled from.

    Synchronous on purpose: the world-state sections and the job enqueue are
    awaited, so the route stays `async def` and these reads would otherwise run
    on the event loop.
    """
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

    ctx_overrides = {
        "character": None,
        "include_roleplay_default": False,
    }
    return (
        chat,
        chat.persona_name or "User",
        character.name if character else "the AI",
        (character.description if character else "") or "",
        ctx_overrides,
        past_messages,
    )

@router.post("/{chat_id}/scene")
async def generate_scene(
    chat_id: str, 
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    character_repo: CharacterRepository = Depends(get_character_repo),
    message_repo: MessageRepository = Depends(get_message_repo),
):
    # History, character and checkpoint resolution are synchronous session
    # work; only the job enqueue below is awaited, so they run in a thread.
    chat, workflow, metadata = await asyncio.to_thread(
        _scene_job_prep_sync, session, chat_repo, character_repo, message_repo, chat_id
    )

    prompt_job = await submit_llm_job(session, workflow, metadata)

    # The scene LLM job is agentic: it calls the generate_image tool (or, when
    # the model cannot call tools, its plain-text output is chained into an
    # image job by the scene_prompt finalize branch in job_processing.py).
    return {"job_id": prompt_job.id, "status": "queued", "message": "Scene generation started"}


def _scene_job_prep_sync(
    session: Session,
    chat_repo: ChatRepository,
    character_repo: CharacterRepository,
    message_repo: MessageRepository,
    chat_id: str,
) -> tuple[Chat, dict, dict]:
    """Validate the chat and build the scene-prompt job.

    Synchronous on purpose: only the job creation and enqueue are awaited, so
    the route stays `async def` and these reads would otherwise run on the event
    loop.
    """
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
    if not chat.allow_image_generation:
        raise ValidationError("Image generation is disabled for this chat")

    # Only the last 10 turns are used, so ask the database for the last 10 rather
    # than loading the whole transcript and slicing it. This was an unbounded
    # `list_by_chat(chat_id)` on a long roleplay.
    past_messages = message_repo.list_by_chat(chat_id, newest_first=True)
    if not past_messages:
        raise ValidationError("No messages in chat to base scene on")

    context_text = "\n".join([f"{m.role.value}: {m.content}" for m in past_messages[-10:] if m.content])

    # Resolve checkpoint: character > scenario default > configured default > any installed model
    checkpoint = None
    if chat.character_id:
        character = character_repo.get(chat.character_id)
        if character and character.checkpoint:
            checkpoint = character.checkpoint
    if not checkpoint:
        scenario_ckpt, _ = resolve_scenario_defaults(session, chat)
        checkpoint = scenario_ckpt
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

    from services.orchestrator_service import AGENTIC_TOOLS, filter_agentic_tools

    workflow, metadata = build_chat_llm_workflow(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\n{context_text}"}
        ],
        chat_id=chat_id,
        character_id=chat.character_id,
        model=_model_for_kind("chat_reply", chat.llm_model, session),
        samplers=sampler_overrides(chat),
        type_="chat_reply",
        workspace="roleplay",
        source="scene_prompt",
        extra_metadata={
            "scene_checkpoint": checkpoint,
            "generator_checkpoint": checkpoint,
            "agentic": True,
            "orchestrator_depth": 0,
            # Carried through the agentic chain so the image it spawns is filed
            # on the same thread the scene was asked for, not the original one.
            "branch_id": past_messages[0].branch_id if past_messages else None,
        },
    )
    workflow["tools"] = filter_agentic_tools(
        AGENTIC_TOOLS,
        allow_image=chat.allow_image_generation,
        allow_narration=chat.allow_narration,
    )
    return chat, workflow, metadata


class ChatIllustrateRequest(BaseModel):
    image_prompt: str = ""
    # The thread the illustration belongs to. A branch's copies share their
    # originals' `chat_id` and `created_at`, so an image message written without
    # it lands in the original thread and the fork the user is reading never
    # shows it. Mirrors `ChatMessageRequest.branch_id`.
    branch_id: str | None = None


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
    the     image lands in the chat as a kind=IMAGE message via the chat_image
    event (world_integration_service) and in the roleplay workspace.
    """
    from services.image_submission import submit_image_job

    # Fallback prompt, character and checkpoint are resolved by a worker thread
    # (the route awaits the image submission below).
    character_id, image_prompt, checkpoint, lora_name, branch_id = await asyncio.to_thread(
        _illustrate_prep_sync, session, chat_repo, character_repo, chat_id, request
    )

    job = await submit_image_job(
        session,
        prompt=image_prompt,
        checkpoint=checkpoint,
        lora=lora_name,
        filename_prefix="ChatIllustrate",
        source="chat_image",
        workspace="chat",
        chat_id=chat_id,
        character_id=character_id,
        branch_id=branch_id,
        extra_metadata={"image_context": image_prompt},
    )
    return {"job_id": job.id, "status": "queued", "message": "Illustration started"}


def _illustrate_prep_sync(
    session: Session,
    chat_repo: ChatRepository,
    character_repo: CharacterRepository,
    chat_id: str,
    request: ChatIllustrateRequest,
) -> tuple[str | None, str, str, str | None, str | None]:
    """Resolve the image prompt, checkpoint, LoRA and thread for an illustration.

    Synchronous on purpose: the image submission is awaited, so the route stays
    `async def` and these queries would otherwise run on the event loop.
    """
    from services.model_availability_service import ModelAvailabilityService

    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)
    if not chat.allow_image_generation:
        raise ValidationError("Image generation is disabled for this chat")

    prompt = (request.image_prompt or "").strip()
    last_char = None
    if not prompt:
        last_char = session.exec(
            select(Message)
            .where(
                Message.chat_id == chat_id,
                # Must use the enum, not the lowercase literals: on Postgres
                # messages.role is a native enum stored under its member NAMES
                # (CHAR/USER), so a string-literal IN ('char','user') predicate
                # matched zero rows and this endpoint could never find a
                # fallback prompt.
                Message.role.in_([MessageRole.CHAR, MessageRole.USER]),
                Message.content.is_not(None),
            )
            .order_by(Message.created_at.desc())
            # .first() applies no LIMIT: psycopg2 buffers the whole result set
            # into the process, so this used to transfer and ORM-instantiate
            # every message in the chat, `content` TEXT included, and discard all
            # but the first.
            .limit(1)
        ).first()
        if last_char and last_char.content.strip():
            prompt = last_char.content.strip()
    if not prompt:
        raise ValidationError("No prompt and no character reply to illustrate")

    character = character_repo.get(chat.character_id) if chat.character_id else None

    checkpoint = (character.checkpoint if character and character.checkpoint else None)
    if not checkpoint:
        scenario_ckpt, _ = resolve_scenario_defaults(session, chat)
        checkpoint = scenario_ckpt
    if not checkpoint:
        checkpoint = ModelAvailabilityService(session).resolve_checkpoint()

    # Explicit branch wins; otherwise the thread the fallback prompt came from.
    # Without this an illustration of a branched message is filed into the
    # original thread.
    branch_id = request.branch_id or (last_char.branch_id if last_char else None)

    return (
        chat.character_id,
        prompt,
        checkpoint,
        character.lora if character and character.lora else None,
        branch_id,
    )


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


@router.post("/{chat_id}/export-story")
def export_chat_to_story(
    chat_id: str,
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    character_repo: CharacterRepository = Depends(get_character_repo),
    story_repo: StoryRepository = Depends(get_story_repo),
):
    """Convert an existing roleplay chat session into a full Story in World Vault."""
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    messages = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    ).all()

    character = character_repo.get(chat.character_id) if chat.character_id else None
    char_name = character.name if character else "Character"
    user_name = chat.persona_name or "User"

    # Assemble dialogue and narration into story prose
    prose_lines: list[str] = []
    for msg in messages:
        meta = msg.message_metadata or {}
        if meta.get("source") == "world_state":
            loc = meta.get("location")
            tim = meta.get("time")
            if loc or tim:
                prose_lines.append(f"\n*— {' · '.join(filter(None, [loc, tim]))} —*\n")
            continue

        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        content = (msg.content or "").strip()
        if not content:
            continue

        if role == "user":
            prose_lines.append(f'**{user_name}:** "{content}"\n')
        elif role == "char":
            speaker = char_name
            if msg.character_id and msg.character_id != chat.character_id:
                other_char = character_repo.get(msg.character_id)
                if other_char:
                    speaker = other_char.name
            prose_lines.append(f'**{speaker}:** "{content}"\n')
        else:
            prose_lines.append(f"*{content}*\n")

    chapter_content = "\n".join(prose_lines).strip()

    char_ids = [chat.character_id] if chat.character_id else []
    for cid in (chat.additional_character_ids or []):
        if cid and cid not in char_ids:
            char_ids.append(cid)

    lore_ids = list(chat.active_lorebook_ids or [])
    loc_ids = [chat.location_id] if chat.location_id else []

    story_title = chat.name or f"Story of {char_name}"
    story = Story(
        title=story_title,
        description=f"Story adapted from roleplay chat '{story_title}' with {char_name}.",
        world_id=chat.world_id,
        character_ids=char_ids,
        lorebook_ids=lore_ids,
        location_ids=loc_ids,
        scenario_id=chat.scenario_id,
        llm_model=chat.llm_model,
        persona_name=chat.persona_name,
        persona_description=chat.persona_description,
    )
    story.created_at = datetime.now(timezone.utc)
    story.updated_at = story.created_at
    link_to_world(session, story, chat.world_id)
    session.add(story)
    session.commit()
    session.refresh(story)

    # Initialise Chapter 1 with the converted prose
    chapter = StoryChapter(
        story_id=story.id,
        chapter_number=1,
        title="Chapter 1: The Encounter",
        content=chapter_content,
    )
    session.add(chapter)
    session.commit()
    session.refresh(story)

    return {
        "story_id": story.id,
        "title": story.title,
        "chapter_id": chapter.id,
    }


class TriggerDirectorRequest(BaseModel):
    run_updater: bool = False
    force_updater: bool = False


class PatchStateSnapshotRequest(BaseModel):
    state_snapshot: dict[str, Any] | None = None
    character_mood: str | None = None
    current_activity: str | None = None
    character_outfit: str | None = None
    relationship_status: str | None = None
    relationships: list[dict[str, Any]] | None = None
    character_skills: list[str] | None = None
    user_skills: list[str] | None = None
    wardrobe: list[dict[str, Any]] | None = None
    fate_check_enabled: bool | None = None
    fate_difficulty: str | None = None
    fate_outcome_override: str | None = None
    world_clock: dict[str, Any] | None = None
    crossover_context: str | None = None
    scene_summary: str | None = None
    inventory: list[str] | None = None
    scene_tension: float | None = None
    emotional_tone: str | None = None
    character_expression: str | None = None
    story_location: str | None = None
    story_time: str | None = None


@router.post("/{chat_id}/director/evaluate")
async def evaluate_chat_director(
    chat_id: str,
    request: TriggerDirectorRequest | None = None,
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo),
    character_repo: CharacterRepository = Depends(get_character_repo),
    message_repo: MessageRepository = Depends(get_message_repo),
    job_service: Any = Depends(get_job_service),
):
    """Evaluate the 13-question System 1 Director on this chat and optionally enqueue the Statekeeper."""
    from services.decision_service import DecisionService
    from services.updater_service import (
        enqueue_state_updater_if_needed,
        record_director_decision,
    )

    req = request or TriggerDirectorRequest()
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    character = character_repo.get(chat.character_id) if chat.character_id else None
    char_name = character.name if character else "Character"
    recent = message_repo.list_by_chat(chat_id, limit=8, newest_first=True)
    recent_transcript = [
        {
            "role": m.role.value if hasattr(m.role, "value") else str(m.role),
            "content": m.content or "",
        }
        for m in recent
    ]
    last_speaker = "user"
    if recent:
        last_msg = recent[-1]
        if last_msg.kind == MessageKind.NARRATOR:
            last_speaker = "narrator"
        elif last_msg.role == MessageRole.CHAR:
            last_speaker = "character"

    decision = await DecisionService(session).evaluate_scene(
        character_name=char_name,
        user_name=chat.persona_name or "User",
        story_location=chat.story_location,
        story_time=chat.story_time,
        state_snapshot=chat.state_snapshot or {},
        recent_messages=recent_transcript,
        last_speaker=last_speaker,
        has_secondary_character=bool(chat.additional_character_ids),
        allow_image_generation=bool(chat.allow_image_generation),
        allow_narration=bool(chat.allow_narration),
    )
    updated_snapshot = await asyncio.to_thread(
        record_director_decision, session, chat_id, decision
    )

    updater_job_id = None
    if req.run_updater or req.force_updater:
        updater_job_id = await enqueue_state_updater_if_needed(
            session,
            chat_id=chat_id,
            character_id=chat.character_id,
            decision=decision,
            job_service=job_service,
            force=req.force_updater,
        )

    return {
        "chat_id": chat_id,
        "decision": decision.to_dict(),
        "state_snapshot": updated_snapshot,
        "updater_job_id": updater_job_id,
    }


@router.patch("/{chat_id}/state-snapshot")
def patch_chat_state_snapshot(
    chat_id: str,
    request: PatchStateSnapshotRequest,
    session: Session = Depends(get_session),
    chat_repo: ChatRepository = Depends(get_chat_repo),
):
    """Directly update fields inside `Chat.state_snapshot` from the UI Statekeeper panel."""
    chat = chat_repo.get(chat_id)
    if not chat:
        raise NotFoundError("Chat", chat_id)

    snapshot = dict(chat.state_snapshot or {})
    updates = request.model_dump(exclude_unset=True)
    nested = updates.pop("state_snapshot", None)
    new_loc = updates.pop("story_location", None)
    new_time = updates.pop("story_time", None)
    if isinstance(nested, dict):
        for k, v in nested.items():
            snapshot[k] = v
    for k, v in updates.items():
        snapshot[k] = v
    if new_loc is not None:
        chat.story_location = new_loc
        wc = dict(snapshot.get("world_clock") or {})
        wc["location"] = new_loc
        snapshot["world_clock"] = wc
    if new_time is not None:
        chat.story_time = new_time
        wc = dict(snapshot.get("world_clock") or {})
        wc["time_of_day"] = new_time
        snapshot["world_clock"] = wc
    snapshot["statekeeper_updated_at"] = datetime.now(timezone.utc).isoformat()

    chat.state_snapshot = snapshot
    chat.updated_at = datetime.now(timezone.utc)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    return {
        "chat_id": chat_id,
        "story_location": chat.story_location,
        "story_time": chat.story_time,
        "state_snapshot": chat.state_snapshot,
    }



