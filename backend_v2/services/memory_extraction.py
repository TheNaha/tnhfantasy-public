"""Auto-extraction of character memories from chat conversations.

When a chat reply finalizes (no more tool calls), this service can enqueue
a background LLM job that reads recent messages and extracts durable memories
for the character's autobiographical memory store.
"""
import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from core.entities import CharacterMemory, Message, MessageRole
from infrastructure.logging import get_logger

logger = get_logger("memory_extraction")

EXTRACTION_PROMPT = """You are a memory extraction assistant. Given a conversation between a user and a character, extract durable, factual memories that the character should remember for future interactions.

Rules:
- Extract 1-5 memories maximum
- Each memory should be a single, concise sentence
- Focus on: user preferences, character relationships, important events, decisions, opinions, facts about the user
- Do NOT include trivial greetings or small talk
- Output ONLY a JSON array of strings, e.g. ["memory 1", "memory 2"]
- If nothing worth remembering, output: []

Conversation:
{messages}
"""


def should_extract_memories(session: Session, chat_id: str) -> bool:
    """Check if a chat has enough new messages to warrant memory extraction."""
    recent = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.desc()).limit(20)
    ).all()
    user_msgs = [m for m in recent if m.role == MessageRole.USER]
    return len(user_msgs) >= 2


def build_extraction_messages(session: Session, chat_id: str) -> list[str]:
    """Build the message list for the extraction LLM prompt."""
    messages = session.exec(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.desc()).limit(20)
    ).all()
    messages.reverse()
    lines = []
    for m in messages:
        role = "User" if m.role == MessageRole.USER else "Character"
        lines.append(f"{role}: {m.content}")
    return lines


async def enqueue_memory_extraction(
    session: Session,
    chat_id: str,
    character_id: str,
    job_service,
) -> bool:
    """Enqueue a background LLM job to extract memories from a chat."""
    if not should_extract_memories(session, chat_id):
        return False

    from services.llm_workflow import build_llm_workflow

    lines = build_extraction_messages(session, chat_id)
    if not lines:
        return False

    prompt = EXTRACTION_PROMPT.format(messages="\n".join(lines))
    workflow, metadata = build_llm_workflow(
        messages=[{"role": "user", "content": prompt}],
        type_="memory_extraction",
        chat_id=chat_id,
        character_id=character_id,
        workspace="chat",
        source="auto_memory",
    )

    try:
        job = await job_service.create_job(task_type="llm", workflow=workflow, metadata=metadata)
        from services.job_queue import queue_manager
        await queue_manager.enqueue(job.id, task_type="llm")
        logger.info("memory_extraction_enqueued", chat_id=chat_id, job_id=job.id)
        return True
    except Exception as exc:
        logger.warning("memory_extraction_enqueue_failed", chat_id=chat_id, error=str(exc))
        return False


def parse_extraction_result(text: str) -> list[str]:
    """Parse the LLM's JSON array output into a list of memory strings."""
    if not text:
        return []
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(m).strip() for m in parsed if str(m).strip()]
    except json.JSONDecodeError:
        pass
    return []


def create_memories_from_extraction(session: Session, character_id: str, memories: list[str]) -> int:
    """Persist extracted memories as CharacterMemory rows with embeddings."""
    if not memories:
        return 0

    from services.embedding_service import get_embedding_service
    emb_svc = get_embedding_service()

    created = 0
    for content in memories:
        mem = CharacterMemory(
            character_id=character_id,
            content=content,
            tags=["auto-extracted"],
            importance=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        try:
            mem.embedding = emb_svc.generate_embedding(content)
        except Exception:
            pass
        session.add(mem)
        created += 1

    session.commit()
    logger.info("memories_auto_created", character_id=character_id, count=created)
    return created
