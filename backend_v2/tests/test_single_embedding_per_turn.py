"""One embedding per turn, not one per retrieval path.

`build_system_prompt_sections` queries the SAME string twice — once for lorebook
entries and once for character memories — and each retrieval used to run its own
`_try_embedding`. That is two MiniLM forward passes over identical text,
serially, on the critical path of every chat turn.

Both now share one vector. `search_lorebook_entries` gained the same
`q_vec` / `q_vec_computed` parameters `search_memories` already had, so the two
retrieval paths are symmetric rather than one being the parsimonious one.
"""

from unittest.mock import patch

import pytest

from core.entities import (
    Chat,
    Character,
    CharacterMemory,
    Lorebook,
    LorebookEntry,
    Message,
    MessageKind,
    MessageRole,
    World,
)


@pytest.fixture
def turn():
    """A chat turn with a world, a character, a lorebook and a memory."""
    from datetime import datetime, timezone

    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)

    session.add(World(name="Ashfall"))
    session.flush()
    session.add(Character(
        id="char-1", name="Aria", description="A mage",
        personality="Curious", scenario="City of Aetheria",
    ))
    session.flush()
    session.add(Chat(id="chat-1", character_id="char-1", world_id="world_ashfall"))
    session.flush()
    session.add(Lorebook(id="lb-1", name="World Book"))
    session.add(LorebookEntry(
        id="entry-1", lorebook_id="lb-1",
        content="The capital is Aetheria.", keys=["Aetheria"],
    ))
    session.add(CharacterMemory(
        id="mem-1", character_id="char-1", content="Aria loves the sea.",
        importance=0.9, last_accessed_at=datetime.now(timezone.utc),
    ))
    session.add(Message(
        id="msg-1", chat_id="chat-1", role=MessageRole.USER,
        kind=MessageKind.USER, content="Tell me about the capital.",
    ))
    session.commit()
    return session


def _count_embeddings(session):
    """Build the prompt with a counting stub in place of the embedding call."""
    calls = []

    def _fake_embed(text, *a, **kw):
        calls.append(text)
        # None drives the keyword path, so the test does not need pgvector.
        return None

    from services import context_builder

    # Postgres-shaped, so the semantic branch runs at all and the vector is
    # actually computed. Without it the keyword path is taken, nothing is
    # embedded, and the count is trivially zero.
    with (
        patch("services.rag_pipeline.rag_enabled", lambda: True),
        patch("services.rag_pipeline._is_postgres", lambda session: True),
        patch("services.rag_pipeline._try_embedding", _fake_embed),
    ):
        context_builder.build_system_prompt_sections(
            session,
            characters=[session.get(Character, "char-1")],
            character_id="char-1",
            lorebook_ids=["lb-1"],
            _lorebook_query="Tell me about the capital.",
            _memory_query="Tell me about the capital.",
        )
    return calls


def test_the_embedding_is_computed_once_per_turn(turn):
    """The regression test for the double forward pass.

    `context_builder` calls `_try_embedding` exactly once and both retrieval
    paths consume that one vector. Two calls means the sharing regressed.
    """
    calls = _count_embeddings(turn)
    assert calls, "no embedding was computed at all"
    assert len(calls) == 1, (
        f"expected one embedding per turn, got {len(calls)}: {calls}"
    )


def test_the_lorebook_search_accepts_a_precomputed_vector():
    """The symmetry that makes sharing possible.

    Without this parameter the caller could not share with `search_memories`,
    which already had it — that asymmetry is why the duplication survived.
    """
    import inspect

    from services.rag_pipeline import search_lorebook_entries, search_memories

    lorebook = inspect.signature(search_lorebook_entries).parameters
    memories = inspect.signature(search_memories).parameters
    for name in ("q_vec", "q_vec_computed"):
        assert name in lorebook, f"search_lorebook_entries lacks {name}"
        assert name in memories, f"search_memories lacks {name}"
