"""Tests for Character Memory CRUD and semantic search endpoints."""
import pytest

from api.routes.world_vault import memories as memories_module
from api.routes.world_vault.memories import (
    MEMORY_PAGE_DEFAULT_LIMIT,
    MEMORY_PAGE_MAX_LIMIT,
    MEMORY_REINDEX_BATCH_SIZE,
    MEMORY_REINDEX_MAX_LIMIT,
)
from core.entities import Character, CharacterMemory


@pytest.fixture
def character(session):
    char = Character(name="MemoryCharacter", description="test")
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


@pytest.fixture
def memory_1(session, character):
    mem = CharacterMemory(
        character_id=character.id,
        content="The castle was built in the 14th century.",
        tags=["history", "castle"],
        importance=8,
    )
    session.add(mem)
    session.commit()
    session.refresh(mem)
    return mem


@pytest.fixture
def memory_2(session, character):
    mem = CharacterMemory(
        character_id=character.id,
        content="The secret passage is behind the tapestry.",
        tags=["secret", "hidden"],
        importance=9,
    )
    session.add(mem)
    session.commit()
    session.refresh(mem)
    return mem


def test_create_memory(client, session, character):
    response = client.post("/api/v2/memories", json={
        "character_id": character.id,
        "content": "A dragon lives in the mountain.",
        "tags": ["dragon", "mountain"],
        "importance": 8,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "A dragon lives in the mountain."
    assert data["character_id"] == character.id
    assert data["importance"] == 8


def test_list_memories(client, session, character, memory_1, memory_2):
    response = client.get(f"/api/v2/memories?character_id={character.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_list_memories_no_character(client, session, character, memory_1):
    response = client.get("/api/v2/memories")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


def test_get_memory(client, session, memory_1):
    response = client.get(f"/api/v2/memories/{memory_1.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == memory_1.content
    assert "history" in data["tags"]


def test_get_memory_not_found(client):
    response = client.get("/api/v2/memories/nonexistent-id")
    assert response.status_code == 404


def test_update_memory(client, session, memory_1):
    response = client.put(f"/api/v2/memories/{memory_1.id}", json={
        "content": "Updated memory content",
        "tags": ["updated", "history"],
        "importance": 5,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "Updated memory content"
    assert "updated" in data["tags"]


def test_delete_memory(client, session, memory_1):
    response = client.delete(f"/api/v2/memories/{memory_1.id}")
    assert response.status_code == 200
    response = client.get(f"/api/v2/memories/{memory_1.id}")
    assert response.status_code == 404


def test_memory_search_semantic(client, session, character, memory_1, memory_2):
    response = client.get(f"/api/v2/memories/search/semantic?character_id={character.id}&query=castle")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_character_memories_list(client, session, character, memory_1, memory_2):
    response = client.get(f"/api/v2/memories/character/{character.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(m["character_id"] == character.id for m in data)


# ---------------------------------------------------------------------------
# Bounded list
# ---------------------------------------------------------------------------


def _seed_memories(session, character, count, *, embedding=None):
    for i in range(count):
        session.add(CharacterMemory(
            character_id=character.id,
            content=f"memory {i}",
            importance=5,
            embedding=embedding,
        ))
    session.commit()


def test_list_memories_truncates_and_says_so(client, session, character):
    _seed_memories(session, character, 5)

    response = client.get("/api/v2/memories?limit=2")

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.headers["X-Total-Count"] == "5"
    assert response.headers["X-Has-More"] == "true"
    assert response.headers["X-Limit"] == "2"
    assert response.headers["X-Offset"] == "0"


def test_list_memories_last_page_reports_no_more(client, session, character):
    _seed_memories(session, character, 5)

    response = client.get("/api/v2/memories?limit=2&offset=4")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.headers["X-Has-More"] == "false"
    assert response.headers["X-Total-Count"] == "5"


def test_list_memories_default_cap_bounds_the_whole_vault(client, session, character):
    _seed_memories(session, character, MEMORY_PAGE_DEFAULT_LIMIT + 1)

    response = client.get("/api/v2/memories")

    assert response.status_code == 200
    assert len(response.json()) == MEMORY_PAGE_DEFAULT_LIMIT
    assert response.headers["X-Total-Count"] == str(MEMORY_PAGE_DEFAULT_LIMIT + 1)
    assert response.headers["X-Has-More"] == "true"


def test_list_memories_rejects_limit_over_max(client):
    assert client.get(f"/api/v2/memories?limit={MEMORY_PAGE_MAX_LIMIT + 1}").status_code == 422
    assert client.get("/api/v2/memories?limit=0").status_code == 422
    assert client.get("/api/v2/memories?offset=-1").status_code == 422


# ---------------------------------------------------------------------------
# Embedding durability on update
# ---------------------------------------------------------------------------


def test_update_memory_keeps_a_good_embedding_when_regeneration_fails(
    client, session, character, memory_1, fake_embeddings
):
    """A transient embedding failure must not destroy an existing vector.

    `update_memory` regenerates the vector whenever `content` changes. The
    regeneration is best-effort — the embedding service can be rate-limited,
    time out, or return 503 — and the write is committed either way. Nulling
    the column on failure therefore destroyed a *good* index entry because of a
    failure that had nothing to do with the row, and nothing puts it back except
    a manual `POST /reindex` sweep. The memory silently dropped out of semantic
    recall until an operator noticed.
    """
    memory_1.embedding = [0.5] * 384
    session.add(memory_1)
    session.commit()

    # Any transient failure: rate limit, timeout, provider 503.
    fake_embeddings(fail_on={"completely new text"})

    response = client.put(f"/api/v2/memories/{memory_1.id}", json={"content": "completely new text"})

    assert response.status_code == 200
    assert response.json()["content"] == "completely new text"

    session.expire_all()
    stored = session.get(CharacterMemory, memory_1.id)
    assert stored.embedding is not None, (
        "a failed embedding regeneration nulled a previously good vector; the "
        "memory is now unsearchable until someone runs POST /reindex"
    )
    assert stored.embedding == [0.5] * 384


def test_update_memory_still_writes_when_regeneration_fails(client, session, character, memory_1, fake_embeddings):
    """The content edit itself must land — only the vector is best-effort."""
    memory_1.embedding = [0.5] * 384
    session.add(memory_1)
    session.commit()

    fake_embeddings(fail_on={"brand new wording"})

    assert client.put(f"/api/v2/memories/{memory_1.id}", json={"content": "brand new wording"}).status_code == 200

    session.expire_all()
    stored = session.get(CharacterMemory, memory_1.id)
    assert stored.content == "brand new wording"


def test_update_memory_replaces_the_vector_on_success(client, session, character, memory_1, fake_embeddings):
    """The preservation rule must not become "never regenerate"."""
    memory_1.embedding = [0.5] * 384
    session.add(memory_1)
    session.commit()

    fake_embeddings()

    assert client.put(f"/api/v2/memories/{memory_1.id}", json={"content": "fresh text"}).status_code == 200

    session.expire_all()
    assert session.get(CharacterMemory, memory_1.id).embedding == [0.1] * 384


def test_update_memory_without_content_change_never_calls_the_embedding_service(
    client, session, character, memory_1, fake_embeddings
):
    memory_1.embedding = [0.5] * 384
    session.add(memory_1)
    session.commit()

    svc = fake_embeddings()

    assert client.put(f"/api/v2/memories/{memory_1.id}", json={"importance": 3}).status_code == 200

    assert svc.batch_sizes == [] and svc.single_calls == []
    session.expire_all()
    assert session.get(CharacterMemory, memory_1.id).embedding == [0.5] * 384


def test_create_memory_leaves_embedding_null_when_the_service_fails(
    client, session, character, fake_embeddings
):
    """A row that never had a vector must not gain one on failure."""
    fake_embeddings(fail_on={"A dragon lives in the mountain."})

    response = client.post("/api/v2/memories", json={
        "character_id": character.id,
        "content": "A dragon lives in the mountain.",
    })

    assert response.status_code == 200
    session.expire_all()
    assert session.get(CharacterMemory, response.json()["id"]).embedding is None


# ---------------------------------------------------------------------------
# Bounded, batched reindex
# ---------------------------------------------------------------------------


class FakeEmbeddingService:
    """Stands in for the local sentence-transformer.

    Records every batch call so the tests can assert the route batches its
    model calls instead of making one per row, which is the whole point of the
    bound: a per-row pass over a large vault is what pinned the thread.
    """

    def __init__(self, *, fail_on=None):
        self.batch_sizes: list[int] = []
        self.single_calls: list[str] = []
        self.fail_on = fail_on or set()

    def generate_embeddings(self, texts):
        self.batch_sizes.append(len(texts))
        if any(t in self.fail_on for t in texts):
            raise RuntimeError("batch failed")
        return [[0.1] * 384 for _ in texts]

    def generate_embedding(self, text):
        self.single_calls.append(text)
        if text in self.fail_on:
            raise RuntimeError("embedding failed")
        return [0.1] * 384


@pytest.fixture
def fake_embeddings(monkeypatch):
    def _install(**kwargs):
        svc = FakeEmbeddingService(**kwargs)
        monkeypatch.setattr(
            "services.embedding_service.get_embedding_service", lambda: svc
        )
        return svc

    return _install


def test_reindex_memories_only_embeds_one_bounded_batch(client, session, character, fake_embeddings):
    _seed_memories(session, character, 5)
    svc = fake_embeddings()

    response = client.post("/api/v2/memories/reindex?limit=2")

    assert response.status_code == 200
    data = response.json()
    assert data["reindexed"] == 2
    assert data["failed"] == 0
    assert data["total_missing"] == 5
    assert data["remaining"] == 3
    assert data["has_more"] is True
    assert data["limit"] == 2
    # Two rows is one batch, so the model is called once — not once per row.
    assert svc.batch_sizes == [2]
    assert svc.single_calls == []


def test_reindex_memories_drains_in_bounded_calls(client, session, character, fake_embeddings):
    _seed_memories(session, character, 5)
    svc = fake_embeddings()

    seen = [client.post("/api/v2/memories/reindex?limit=2").json() for _ in range(3)]

    assert [d["reindexed"] for d in seen] == [2, 2, 1]
    assert [d["has_more"] for d in seen] == [True, True, False]
    assert seen[-1]["remaining"] == 0
    # Every row got a vector, and no call ever exceeded the requested limit.
    assert session.query(CharacterMemory).filter(CharacterMemory.embedding.isnot(None)).count() == 5
    assert all(size <= 2 for size in svc.batch_sizes)


def test_reindex_memories_commits_in_batches(client, session, character, fake_embeddings, monkeypatch):
    monkeypatch.setattr(memories_module, "MEMORY_REINDEX_BATCH_SIZE", 2)
    _seed_memories(session, character, 5)
    svc = fake_embeddings()

    response = client.post("/api/v2/memories/reindex?limit=5")

    assert response.status_code == 200
    assert response.json()["reindexed"] == 5
    assert response.json()["batch_size"] == 2
    # 5 rows at a batch size of 2 is three model calls, not five.
    assert svc.batch_sizes == [2, 2, 1]


def test_reindex_memories_falls_back_to_per_row_when_a_batch_fails(client, session, character, fake_embeddings):
    _seed_memories(session, character, 2)
    svc = fake_embeddings(fail_on={"memory 1"})

    response = client.post("/api/v2/memories/reindex?limit=2")

    assert response.status_code == 200
    data = response.json()
    assert data["reindexed"] == 1
    assert data["failed"] == 1
    assert data["remaining"] == 1
    assert data["has_more"] is True
    # The readable row in the failed batch is still embedded.
    assert svc.batch_sizes == [2]
    assert svc.single_calls == ["memory 0", "memory 1"]


def test_reindex_memories_survives_an_embedding_service_that_always_fails(client, session, character, fake_embeddings):
    _seed_memories(session, character, 3)
    fake_embeddings(fail_on={"memory 0", "memory 1", "memory 2"})

    response = client.post("/api/v2/memories/reindex?limit=3")

    assert response.status_code == 200
    data = response.json()
    assert data["reindexed"] == 0
    assert data["failed"] == 3
    assert data["has_more"] is True


def test_reindex_memories_rejects_limit_over_max(client):
    assert client.post(f"/api/v2/memories/reindex?limit={MEMORY_REINDEX_MAX_LIMIT + 1}").status_code == 422
    assert client.post("/api/v2/memories/reindex?limit=0").status_code == 422


def test_reindex_memories_is_a_noop_when_nothing_is_missing(client, session, character, memory_1):
    memory_1.embedding = [0.2] * 384
    session.add(CharacterMemory(
        character_id=character.id,
        content="already indexed",
        embedding=[0.2] * 384,
    ))
    session.commit()

    data = client.post("/api/v2/memories/reindex").json()

    assert data["reindexed"] == 0
    assert data["total_missing"] == 0
    assert data["remaining"] == 0
    assert data["has_more"] is False


def test_reindex_default_batch_size_is_bounded():
    assert 0 < MEMORY_REINDEX_BATCH_SIZE <= MEMORY_REINDEX_MAX_LIMIT
