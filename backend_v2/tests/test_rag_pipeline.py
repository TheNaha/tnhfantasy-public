"""Tests for the canonical semantic retrieval pipeline (services/rag_pipeline.py)."""

import pytest
from sqlmodel import Session, select

from core.entities import Character, CharacterMemory, Lorebook, LorebookEntry


def _seed_lorebook(session: Session) -> Lorebook:
    lb = Lorebook(name="Test Lorebook", description="desc")
    session.add(lb)
    session.commit()
    session.refresh(lb)
    return lb


def _add_entry(session: Session, lorebook_id: str, keys, content) -> LorebookEntry:
    entry = LorebookEntry(lorebook_id=lorebook_id, keys=keys, content=content)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def _seed_character(session: Session, name: str) -> Character:
    char = Character(name=name, description="test")
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


class TestSearchMemories:
    def test_keyword_match_and_ranking(self, session):
        char = _seed_character(session, "MemChar")
        m1 = CharacterMemory(character_id=char.id, content="The castle is on the hill.", importance=8)
        m2 = CharacterMemory(character_id=char.id, content="She likes apples.", importance=5)
        session.add_all([m1, m2])
        session.commit()

        from services.rag_pipeline import search_memories

        results = search_memories(session, char.id, query="castle")
        assert [r.id for r in results] == [m1.id]

    def test_blank_query_returns_recent_first(self, session):
        char = _seed_character(session, "MemChar2")
        m1 = CharacterMemory(character_id=char.id, content="Old memory", importance=1)
        m2 = CharacterMemory(character_id=char.id, content="New memory", importance=9)
        session.add_all([m1, m2])
        session.commit()

        from services.rag_pipeline import search_memories

        results = search_memories(session, char.id, query="", limit=10)
        # importance desc wins over created_at ordering
        assert [r.id for r in results] == [m2.id, m1.id]

    def test_touch_last_accessed(self, session):
        char = _seed_character(session, "MemChar3")
        mem = CharacterMemory(character_id=char.id, content="Something worth recalling.")
        session.add(mem)
        session.commit()

        from services.rag_pipeline import search_memories

        results = search_memories(session, char.id, query="worth", limit=5, touch_last_accessed=True)
        session.refresh(mem)
        assert results and mem.last_accessed_at is not None

    def test_no_cross_character_leak(self, session):
        char_a = _seed_character(session, "LeakA")
        char_b = _seed_character(session, "LeakB")
        session.add(CharacterMemory(character_id=char_a.id, content="Secret of A."))
        session.commit()

        from services.rag_pipeline import search_memories

        results = search_memories(session, char_b.id, query="Secret", limit=10)
        assert results == []


class TestSearchLorebookEntries:
    def test_key_match(self, session):
        lb = _seed_lorebook(session)
        e1 = _add_entry(session, lb.id, ["dragon"], "The dragon slumbers.")
        _add_entry(session, lb.id, ["castle"], "The castle stands tall.")

        from services.rag_pipeline import search_lorebook_entries

        results = search_lorebook_entries(session, [lb.id], query="dragon", limit=5)
        assert [r.id for r in results] == [e1.id]

    def test_entries_without_keys_always_included(self, session):
        lb = _seed_lorebook(session)
        e1 = _add_entry(session, lb.id, [], "Unkeyed lore always relevant.")
        _add_entry(session, lb.id, ["sword"], "The sword of echoes.")

        from services.rag_pipeline import search_lorebook_entries

        results = search_lorebook_entries(session, [lb.id], query="unrelated", limit=5)
        assert [r.id for r in results] == [e1.id]

    def test_keyed_entry_matched_by_query(self, session):
        lb = _seed_lorebook(session)
        e1 = _add_entry(session, lb.id, ["dragon"], "The dragon sleeps.")
        _add_entry(session, lb.id, ["sword"], "The sword of echoes.")

        from services.rag_pipeline import search_lorebook_entries

        results = search_lorebook_entries(session, [lb.id], query="dragon is old", limit=5)
        assert [r.id for r in results] == [e1.id]

    def test_blank_query_returns_entries(self, session):
        lb = _seed_lorebook(session)
        e1 = _add_entry(session, lb.id, ["a"], "Entry A content.")
        e2 = _add_entry(session, lb.id, ["b"], "Entry B content.")

        from services.rag_pipeline import search_lorebook_entries

        results = search_lorebook_entries(session, [lb.id], query="", limit=5)
        assert {r.id for r in results} == {e1.id, e2.id}

    def test_empty_lorebook_ids(self, session):
        from services.rag_pipeline import search_lorebook_entries

        assert search_lorebook_entries(session, [], query="x") == []

    def test_multiple_lorebooks_deduped(self, session):
        lb1 = _seed_lorebook(session)
        lb2 = _seed_lorebook(session)
        _add_entry(session, lb1.id, ["wolf"], "Wolves howl at night.")
        _add_entry(session, lb2.id, ["wolf"], "Dire wolves roam.")

        from services.rag_pipeline import search_lorebook_entries

        results = search_lorebook_entries(session, [lb1.id, lb2.id], query="wolf", limit=5)
        assert len(results) == 2


class TestBackfillLorebookEmbeddings:
    def test_backfills_missing_embeddings(self, session, monkeypatch):
        """A lorebook reindex must not depend on the embedding model.

        This test used to patch only
        `EmbeddingService.generate_embedding` — the PER-ROW method. But the
        backfill calls `generate_embeddings`, the BATCH method, first, and only
        falls back to the per-row one when the batch call raises or returns the
        wrong count (`rag_pipeline.py:473`). The real model answered the batch
        call, so the patched fallback never ran and `entry.embedding` came back
        as a genuine 384-dimensional sentence-transformers vector:
        `[0.0387915782..., ...] != [0.1, 0.1, ...]`.

        The consequences were not just a wrong assertion. The suite is hermetic
        everywhere else, so this one test silently loaded the real model on every
        run — slow, and dependent on a model being downloaded — while asserting
        nothing about the backfill's own logic. It is also why STATUS.md records
        the reindex paths as "never executed by any suite": this test looked like
        coverage and was not.

        Both methods are patched, because which one runs is a property of the
        implementation, not of the test.
        """
        lb = _seed_lorebook(session)
        entry = _add_entry(session, lb.id, ["key"], "Some content")
        entry.embedding = None
        session.add(entry)
        session.commit()

        fake_vec = [0.1] * 384

        def fake_embedding(self, text: str):
            return fake_vec

        def fake_embeddings(self, texts: list[str]):
            return [fake_vec for _ in texts]

        # Patch the SERVICE module's class, and assert the patch took, because a
        # `rag_pipeline`-level late import (`from services.embedding_service import
        # get_embedding_service`, inside the function) means a setattr on the
        # wrong object fails exactly as silently as patching the wrong method.
        embedding_module = pytest.importorskip("services.embedding_service")
        monkeypatch.setattr(
            "services.embedding_service.EmbeddingService.generate_embedding",
            fake_embedding,
        )
        monkeypatch.setattr(
            "services.embedding_service.EmbeddingService.generate_embeddings",
            fake_embeddings,
        )

        from services.rag_pipeline import backfill_lorebook_embeddings

        updated = backfill_lorebook_embeddings(session, lb.id)
        assert updated == 1
        session.refresh(entry)
        assert entry.embedding == fake_vec

        # And the patch was actually installed on the class the pipeline resolves
        # lazily, rather than on a copy of it.
        assert embedding_module.EmbeddingService.generate_embeddings is fake_embeddings


class TestLorebookReindexRoute:
    def test_reindex_endpoint(self, client, session, monkeypatch):
        lb = _seed_lorebook(session)
        _add_entry(session, lb.id, ["a"], "Entry content")
        session.exec(select(LorebookEntry).where(LorebookEntry.lorebook_id == lb.id)).one().embedding = None
        session.commit()

        # Both methods, same reason as `test_backfills_missing_embeddings`
        # above: the backfill calls the BATCH method first and only falls back
        # to the per-row one, so patching only `generate_embedding` lets the real
        # sentence-transformers model answer — and the endpoint's `reindexed`
        # count then comes from the real model rather than from the stub.
        monkeypatch.setattr(
            "services.embedding_service.EmbeddingService.generate_embedding",
            lambda self, text: [0.2] * 384,
        )
        monkeypatch.setattr(
            "services.embedding_service.EmbeddingService.generate_embeddings",
            lambda self, texts: [[0.2] * 384 for _ in texts],
        )

        resp = client.post(f"/api/v2/lorebooks/{lb.id}/reindex")
        assert resp.status_code == 200, resp.text
        assert resp.json()["reindexed"] == 1

    def test_reindex_missing_lorebook_404(self, client):
        resp = client.post("/api/v2/lorebooks/nope/reindex")
        assert resp.status_code == 404

class TestRagEnabledGate:
    def test_enabled_by_default(self, session, monkeypatch):
        import services.rag_pipeline as rag
        import config as app_config

        monkeypatch.setattr(
            app_config, "get_config", lambda: {"ai": {}}, raising=False
        )
        assert rag.rag_enabled() is True

    def test_disabled_still_returns_results_via_fallback(self, session, monkeypatch):
        """Disabling RAG must remove only the SEMANTIC step, not retrieval.

        This asserted `== []`, which contradicted the settings UI's own
        description that context "falls back to recent/recency-based retrieval
        only" — turning the toggle off silently deleted a character's history
        and made every activated lorebook inert. Both functions already had a
        keyword/recency path for a blank query; the fix routes a disabled RAG
        into it instead of returning nothing.
        """
        import services.rag_pipeline as rag
        import config as app_config

        char = _seed_character(session, "RAGGate")
        session.add(CharacterMemory(character_id=char.id, content="secret memory"))
        session.commit()

        lb = _seed_lorebook(session)
        _add_entry(session, lb.id, ["gate"], "gated entry")

        monkeypatch.setattr(
            app_config, "get_config", lambda: {"ai": {"ragEnabled": False}}, raising=False
        )
        assert not rag.rag_enabled()

        # Still retrieved, by recency.
        memories = rag.search_memories(session, char.id)
        assert [m.content for m in memories] == ["secret memory"]

        # Still retrieved, by key match — keyword search never needed an embedding.
        entries = rag.search_lorebook_entries(session, [lb.id], "gate")
        assert [e.content for e in entries] == ["gated entry"]

    def test_explicit_true_still_searches(self, session, monkeypatch):
        import services.rag_pipeline as rag
        import config as app_config

        char = _seed_character(session, "RAGOn")
        session.add(CharacterMemory(character_id=char.id, content="visible memory"))
        session.commit()

        monkeypatch.setattr(
            app_config, "get_config", lambda: {"ai": {"ragEnabled": True}}, raising=False
        )
        results = rag.search_memories(session, char.id)
        assert len(results) == 1
        assert results[0].content == "visible memory"


class TestRagDisabledFallsBackRatherThanReturningNothing:
    """`ai.ragEnabled` used to gate both search functions with an early
    `return []`, which contradicted the settings UI's own description that
    context "falls back to recent/recency-based retrieval only". Turning the
    semantic layer off must remove only the embedding step."""

    def test_memories_still_returned_when_rag_disabled(self, monkeypatch):
        from sqlmodel import Session, create_engine
        from sqlmodel.pool import StaticPool
        from sqlmodel import SQLModel
        import core.entities  # noqa: F401
        from core.entities import CharacterMemory
        from services import rag_pipeline

        monkeypatch.setattr(rag_pipeline, "rag_enabled", lambda: False)

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        SQLModel.metadata.create_all(engine, tables=[CharacterMemory.__table__])
        with Session(engine) as s:
            s.add(CharacterMemory(character_id="c1", content="the user likes tea"))
            s.add(CharacterMemory(character_id="c1", content="unrelated note"))
            s.commit()

            # No query -> the recency path, exactly as a blank query behaves.
            assert len(rag_pipeline.search_memories(s, "c1", limit=5)) == 2
            # With a query -> keyword matching still works, because keyword
            # search never needed an embedding.
            hits = rag_pipeline.search_memories(s, "c1", query="tea", limit=5)
            assert [h.content for h in hits] == ["the user likes tea"]

    def test_lorebook_entries_still_returned_when_rag_disabled(self, monkeypatch):
        from sqlmodel import Session, create_engine
        from sqlmodel.pool import StaticPool
        from sqlmodel import SQLModel
        import core.entities  # noqa: F401
        from core.entities import LorebookEntry
        from services import rag_pipeline

        monkeypatch.setattr(rag_pipeline, "rag_enabled", lambda: False)

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        SQLModel.metadata.create_all(engine, tables=[LorebookEntry.__table__])
        with Session(engine) as s:
            s.add(LorebookEntry(lorebook_id="lb1", content="Zeta is a cat girl", keys=["zeta"]))
            s.add(LorebookEntry(lorebook_id="lb1", content="unrelated lore", keys=["other"]))
            s.commit()

            out = rag_pipeline.search_lorebook_entries(s, ["lb1"], limit=5)
            assert len(out) == 2, "a disabled RAG must not make lorebooks inert"
