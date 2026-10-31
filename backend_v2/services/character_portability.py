"""What a character has that a SillyTavern card cannot carry.

A card is a portable interchange format with a small, fixed vocabulary:
a name, some prose fields, a greeting, an example, a lorebook, and an
avatar. This app's characters are much larger than that, and the export used
to say nothing about the difference — a character with six expression images,
a voice model, a world with three locations and twelve chats exported as a
card that simply had none of them, and the UI showed nothing.

So the difference is enumerated here, in one place, from the character's own
rows. The export names what is missing; the bundle (Phase 4) carries it.

What a card CAN carry, for the record: the prose fields, the greetings, the
example, `mes_example`, the tags, the avatar, the generation settings and the
scene defaults (through `data.extensions`), and the card's own embedded
lorebook. Everything below is outside that vocabulary.
"""

from __future__ import annotations

from sqlmodel import Session, select

from infrastructure.logging import get_logger
from core.entities import (
    Character,
    CharacterMemory,
    Chat,
    Collection,
    Location,
    Lorebook,
    World,
)

logger = get_logger("character_portability")

def not_portable_features(session: Session, character: Character) -> list[dict[str, str]]:
    """The features of `character` that a SillyTavern card cannot express.

    Each entry is `{"name", "field", "detail"}` — the same shape the import
    report uses, so one renderer serves both directions.
    """
    out: list[dict[str, str]] = []

    expressions = character.expressions or {}
    if expressions:
        out.append(
            {
                "name": "Expression images",
                "field": "expressions",
                "detail": f"{len(expressions)} expression(s): {', '.join(sorted(expressions)[:6])}"
                + ("..." if len(expressions) > 6 else ""),
            }
        )

    if character.expressions_lora:
        out.append(
            {
                "name": "Expression LoRA triggers",
                "field": "expressions_lora",
                "detail": f"{len(character.expressions_lora)} trigger(s)",
            }
        )

    if character.voice_model_id:
        out.append(
            {
                "name": "Voice model",
                "field": "voice_model_id",
                "detail": "bound to a voice model in this vault; a card can only name one",
            }
        )
    elif character.voice_profile:
        out.append(
            {
                "name": "Voice profile",
                "field": "voice_profile",
                "detail": "a TTS profile this app resolves locally",
            }
        )

    if character.world_id:
        world = session.get(World, character.world_id)
        location_count = 0
        try:
            location_count = len(
                session.exec(
                    select(Location).where(Location.world_id == character.world_id)
                ).all()
            )
        except Exception as exc:
            logger.warning("character_portability_query_failed", field="locations", error=str(exc))
            location_count = 0
        detail = "belongs to a world in this vault"
        if world is not None and getattr(world, "name", None):
            detail = f"belongs to the world '{world.name}'"
        if location_count:
            detail += f", with {location_count} location(s)"
        out.append({"name": "World membership", "field": "world_id", "detail": detail})

    if character.lorebook_ids:
        names = []
        for lorebook_id in character.lorebook_ids:
            lorebook = session.get(Lorebook, lorebook_id)
            if lorebook is not None:
                names.append(lorebook.name)
        out.append(
            {
                "name": "Vault lorebooks",
                "field": "lorebook_ids",
                "detail": f"{len(character.lorebook_ids)} book(s)"
                + (f": {', '.join(names[:4])}" if names else ""),
            }
        )

    try:
        gallery_count = len(
            session.exec(
                select(Collection).where(Collection.character_id == character.id)
            ).all()
        )
    except Exception as exc:
        logger.warning("character_portability_query_failed", field="gallery", error=str(exc))
        gallery_count = 0
    if gallery_count:
        out.append(
            {
                "name": "Scene gallery",
                "field": "gallery",
                "detail": f"{gallery_count} collection(s) of generated scene images",
            }
        )

    try:
        chat_count = len(
            session.exec(select(Chat).where(Chat.character_id == character.id)).all()
        )
    except Exception as exc:
        logger.warning("character_portability_query_failed", field="chats", error=str(exc))
        chat_count = 0
    if chat_count:
        out.append(
            {
                "name": "Chat history",
                "field": "chats",
                "detail": f"{chat_count} conversation(s) with this character",
            }
        )

    try:
        memory_count = len(
            session.exec(
                select(CharacterMemory).where(CharacterMemory.character_id == character.id)
            ).all()
        )
    except Exception as exc:
        logger.warning("character_portability_query_failed", field="memories", error=str(exc))
        memory_count = 0
    if memory_count:
        out.append(
            {
                "name": "Memories",
                "field": "memories",
                "detail": f"{memory_count} remembered episode(s)",
            }
        )

    return out


def portable_summary(features: list[dict[str, str]]) -> str:
    """One line for the export menu: "6 expressions, 1 voice model, ..."."""
    if not features:
        return "Nothing outside a card's vocabulary."
    names = [f["name"] for f in features]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"
