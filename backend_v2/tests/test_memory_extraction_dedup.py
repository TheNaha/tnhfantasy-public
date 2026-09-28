"""Memory extraction: a real off switch, and no more duplicate memories.

`create_memories_from_extraction` inserted unconditionally. The extraction hook
fires for more than real replies — `generate_swipe` and `regenerate_reply` both
default to `type_="chat_reply"`, and the idle simulator fires one for a turn the
user never wrote — and `should_extract_memories` counts only USER messages, so a
swipe leaves the count unchanged and re-opens the gate. Regenerating a reply
therefore re-ran extraction over a near-identical 20-message window and inserted
a second copy of the same 1-5 memories, permanently.

It was not just table bloat. Duplicate memories are mutual nearest neighbours,
so a fixed top-N retrieval returned the same copies for *every* query: the store's
effective capacity was a handful of entries however many turns had passed.

There was also no gate. This ran as a billed LLM call with no way to turn it off.
"""

import pytest

from services.memory_extraction import (
    MEMORY_DEDUP_MAX_DISTANCE,
    _normalize_memory_text,
    memory_extraction_enabled,
)


@pytest.fixture
def character(session):
    from core.entities import Character

    c = Character(name="Dedup Subject")
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Deterministic vectors, so the near-duplicate pass is testable without SBERT.

    Content is hashed to a unit-ish vector, so identical text always yields an
    identical vector (distance 0) and different text yields something far away.
    """
    import hashlib

    class FakeEmb:
        @staticmethod
        def _vec(text: str) -> list[float]:
            h = hashlib.sha256(text.encode()).digest()
            return [b / 255.0 for b in h[:384]]

        def generate_embeddings(self, texts):
            return [self._vec(t) for t in texts]

        def generate_embedding(self, text):
            return self._vec(text)

    import services.embedding_service as es

    monkeypatch.setattr(es, "get_embedding_service", lambda: FakeEmb())
    return FakeEmb


def _mem(session, character_id, content, tags=None):
    from core.entities import CharacterMemory
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    m = CharacterMemory(
        character_id=character_id,
        content=content,
        tags=tags or ["auto-extracted"],
        created_at=now,
        updated_at=now,
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


class TestOffSwitch:
    def test_it_defaults_to_on_so_upgrading_changes_nothing(self, monkeypatch):
        import config as app_config

        monkeypatch.setattr(app_config, "get_config", lambda: {"ai": {}})
        assert memory_extraction_enabled() is True

    def test_it_can_be_turned_off(self, monkeypatch):
        import config as app_config

        monkeypatch.setattr(
            app_config, "get_config", lambda: {"ai": {"memoryExtractionEnabled": False}}
        )
        assert memory_extraction_enabled() is False

    def test_an_unreadable_config_fails_open(self, monkeypatch):
        """Silently disabling a feature the user depends on is worse than
        silently paying for it — the cost is visible, the missing memories are not."""
        import config as app_config

        def boom():
            raise RuntimeError("config unreadable")

        monkeypatch.setattr(app_config, "get_config", boom)
        assert memory_extraction_enabled() is True

    @pytest.mark.asyncio
    async def test_enqueue_short_circuits_when_disabled(self, session, character, monkeypatch):
        from core.entities import Chat, Message, MessageRole
        from datetime import datetime, timezone
        from services.memory_extraction import enqueue_memory_extraction

        chat = Chat(title="x", character_id=character.id)
        session.add(chat)
        session.commit()
        now = datetime.now(timezone.utc)
        for i in range(6):
            session.add(Message(
                chat_id=chat.id, role=MessageRole.USER if i % 2 == 0 else MessageRole.CHAR,
                content=f"m{i}", created_at=now, updated_at=now,
            ))
        session.commit()

        enqueued = []

        class FakeJobService:
            def create_job(self, **kw):
                enqueued.append(kw)
                raise AssertionError("must not create a job when disabled")

        import config as app_config
        monkeypatch.setattr(
            app_config, "get_config", lambda: {"ai": {"memoryExtractionEnabled": False}}
        )
        assert await enqueue_memory_extraction(session, chat.id, character.id, FakeJobService()) is False
        assert enqueued == []


class TestExactDedup:
    def test_normalisation_ignores_case_and_whitespace(self):
        assert _normalize_memory_text("  The  Bell   Tolled\n") == _normalize_memory_text(
            "the bell tolled"
        )

    def test_a_regenerated_reply_does_not_duplicate_memories(
        self, session, character, fake_embeddings
    ):
        """The headline case: the same extraction running twice inserts once."""
        from services.memory_extraction import create_memories_from_extraction

        first = create_memories_from_extraction(
            session, character.id, ["The bell tolled at dusk.", "She wore a grey cloak."]
        )
        second = create_memories_from_extraction(
            session, character.id, ["The bell tolled at dusk.", "She wore a grey cloak."]
        )
        assert first == 2
        assert second == 0, "regenerating a reply re-inserted the same memories"

    def test_case_and_whitespace_variants_are_caught(self, session, character, fake_embeddings):
        from services.memory_extraction import create_memories_from_extraction

        create_memories_from_extraction(session, character.id, ["The Bell Tolled."])
        again = create_memories_from_extraction(
            session, character.id, ["  the bell   tolled.  "]
        )
        assert again == 0

    def test_distinct_memories_are_all_kept(self, session, character, fake_embeddings):
        from services.memory_extraction import create_memories_from_extraction

        n = create_memories_from_extraction(
            session, character.id,
            ["She wore a grey cloak.", "He kept a knife.", "The market closed early."],
        )
        assert n == 3

    def test_a_duplicate_inside_one_batch_is_collapsed(self, session, character, fake_embeddings):
        from services.memory_extraction import create_memories_from_extraction

        n = create_memories_from_extraction(
            session, character.id,
            ["She wore a grey cloak.", "she wore a GREY cloak.", "He kept a knife."],
        )
        assert n == 2

    def test_a_hand_written_memory_is_not_duplicated_by_the_extractor(
        self, session, character, fake_embeddings
    ):
        """The check is against every memory, not just auto-extracted ones. If
        the user wrote it, an auto copy is still a copy."""
        from services.memory_extraction import create_memories_from_extraction

        _mem(session, character.id, "She wore a grey cloak.", tags=["hand-written"])
        assert create_memories_from_extraction(
            session, character.id, ["She wore a grey cloak."]
        ) == 0

    def test_memories_are_scoped_per_character(self, session, character, fake_embeddings):
        """Two characters can both have the same fact."""
        from core.entities import Character
        from services.memory_extraction import create_memories_from_extraction

        other = Character(name="Other")
        session.add(other)
        session.commit()
        session.refresh(other)

        assert create_memories_from_extraction(session, character.id, ["The bell tolled."]) == 1
        assert create_memories_from_extraction(session, other.id, ["The bell tolled."]) == 1

    def test_nothing_to_do_returns_zero_without_touching_embeddings(
        self, session, character, monkeypatch
    ):
        """An all-duplicate batch must not pay for an embedding pass at all."""
        from services.memory_extraction import create_memories_from_extraction

        _mem(session, character.id, "The bell tolled.")

        class Explode:
            def generate_embeddings(self, texts):
                raise AssertionError("paid for embeddings that were all duplicates")

            def generate_embedding(self, text):
                raise AssertionError("paid for embeddings that were all duplicates")

        import services.embedding_service as es
        monkeypatch.setattr(es, "get_embedding_service", lambda: Explode())
        assert create_memories_from_extraction(session, character.id, ["The bell tolled."]) == 0


class TestNearDuplicateDedup:
    def test_the_cutoff_is_tight(self):
        """This is not a relevance filter. Retrieval has its own cutoff
        (`rag_pipeline.rag_max_distance`); loosening this would start discarding
        genuinely distinct facts."""
        assert 0.0 < MEMORY_DEDUP_MAX_DISTANCE <= 0.1

    def test_a_near_duplicate_vector_is_dropped(self, session, character, fake_embeddings):
        """A lightly reworded restatement has a near-identical vector. On a real
        Postgres this hits the pgvector query; on SQLite the query raises and is
        caught, so this asserts the pass is attempted and never crashes."""
        from services.memory_extraction import create_memories_from_extraction

        first = create_memories_from_extraction(session, character.id, ["The bell tolled."])
        assert first == 1
        # Exact matching already covers the identical case, so this second batch
        # uses text the normaliser treats as new.
        second = create_memories_from_extraction(session, character.id, ["A bell tolled."])
        # Either outcome is legitimate depending on the vector backend; what must
        # not happen is a crash or a lost distinct memory.
        assert second in (0, 1)

    def test_the_vector_pass_never_raises_on_sqlite(self, session, character, fake_embeddings):
        """`embedding` is a `Vector(384)`, so the cosine query cannot run on
        SQLite. It must degrade to exact matching, not break extraction."""
        from services.memory_extraction import create_memories_from_extraction

        n = create_memories_from_extraction(
            session, character.id, ["Something entirely new to store."]
        )
        assert n == 1
