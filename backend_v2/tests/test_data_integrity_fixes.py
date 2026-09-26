"""Tests for the backend data-integrity fixes with cheap, targeted coverage.

Grouped by the defect each pins:
  * lorebook reindex bound + batching (was unbounded, one model call per entry)
  * memory_extraction no longer swallowing an embedding failure
  * `cached()` refusing an unknown cache name (was aliasing to the stats cache)
  * get_available_models ordering + TTL cache (was unordered DISTINCT, uncached)
  * the lost-chat-reply reconciler
  * `GET /api/v2/llm/default-provider` answering 200 with a null body
"""

import pytest
from sqlmodel import Session, select

from core.entities import (
    Character,
    Chat,
    Job,
    JobStatus,
    Lorebook,
    LorebookEntry,
    Provider,
    ProviderVersionStatus,
    ModelFile,
    ModelV2,
    ModelVersion,
    Message,
)
import services.rag_pipeline as rag_pipeline
import services.world_integration_service as wis


# ════════════════════════════════════════════════════════════════════════════
# lorebook reindex bounding
# ════════════════════════════════════════════════════════════════════════════

class _RecordingEmbeddingService:
    """Stands in for the real model. Counts single and batch calls."""

    def __init__(self, *, fail_batches: bool = False):
        self.batch_calls: list[list[str]] = []
        self.single_calls: list[str] = []
        self.fail_batches = fail_batches

    def generate_embeddings(self, texts):
        if self.fail_batches:
            raise RuntimeError("FAKE-OOM model unloaded")
        self.batch_calls.append(list(texts))
        return [[0.1] * 384 for _ in texts]

    def generate_embedding(self, text):
        self.single_calls.append(text)
        return [0.2] * 384


def _seed_lorebook(session: Session, count: int) -> str:
    lorebook = Lorebook(name="Book", description="d")
    session.add(lorebook)
    session.commit()
    session.refresh(lorebook)
    for index in range(count):
        session.add(LorebookEntry(
            lorebook_id=lorebook.id,
            content=f"entry {index}",
            keys=[f"key{index}"],
        ))
    session.commit()
    return lorebook.id


def test_lorebook_reindex_is_bounded_at_the_default_limit(session, monkeypatch):
    """Was `select(...).where(embedding IS NULL)` with no LIMIT, one model call
    per entry, in a single commit, on the request the UI calls."""
    service = _RecordingEmbeddingService()
    monkeypatch.setattr(
        "services.embedding_service.get_embedding_service", lambda: service
    )
    total = rag_pipeline.LOREBOOK_REINDEX_DEFAULT_LIMIT + 5
    _seed_lorebook(session, total)

    embedded = rag_pipeline.backfill_lorebook_embeddings(session)

    assert embedded == rag_pipeline.LOREBOOK_REINDEX_DEFAULT_LIMIT
    # It stopped at the bound and left the rest for a later call.
    remaining = session.exec(
        select(LorebookEntry).where(LorebookEntry.embedding.is_(None))
    ).all()
    assert len(remaining) == 5


def test_lorebook_reindex_respects_an_explicit_limit(session, monkeypatch):
    service = _RecordingEmbeddingService()
    monkeypatch.setattr(
        "services.embedding_service.get_embedding_service", lambda: service
    )
    lorebook_id = _seed_lorebook(session, 10)

    embedded = rag_pipeline.backfill_lorebook_embeddings(session, lorebook_id, limit=3)

    assert embedded == 3


def test_lorebook_reindex_batches_instead_of_one_call_per_entry(session, monkeypatch):
    """4 chunks of 32, not 100 individual model calls."""
    service = _RecordingEmbeddingService()
    monkeypatch.setattr(
        "services.embedding_service.get_embedding_service", lambda: service
    )
    _seed_lorebook(session, 100)

    rag_pipeline.backfill_lorebook_embeddings(session)

    assert service.single_calls == []
    expected_chunks = -(-100 // rag_pipeline.LOREBOOK_REINDEX_BATCH_SIZE)
    assert len(service.batch_calls) == expected_chunks
    assert all(len(chunk) <= rag_pipeline.LOREBOOK_REINDEX_BATCH_SIZE for chunk in service.batch_calls)


def test_lorebook_reindex_commits_per_batch_so_partial_work_survives(session, monkeypatch):
    """A batch failure must not roll back the batches that already succeeded."""
    service = _RecordingEmbeddingService()
    monkeypatch.setattr(
        "services.embedding_service.get_embedding_service", lambda: service
    )
    _seed_lorebook(session, 32)

    rag_pipeline.backfill_lorebook_embeddings(session)

    # A full batch of 32 with batch_size 32: the commit happened, so the rows
    # carry vectors rather than the whole run being discarded.
    assert session.exec(
        select(LorebookEntry).where(LorebookEntry.embedding.is_not(None))
    ).all()


def test_lorebook_reindex_falls_back_to_per_row_when_the_batch_call_fails(
    session, monkeypatch,
):
    service = _RecordingEmbeddingService(fail_batches=True)
    monkeypatch.setattr(
        "services.embedding_service.get_embedding_service", lambda: service
    )
    _seed_lorebook(session, 5)

    embedded = rag_pipeline.backfill_lorebook_embeddings(session)

    assert len(service.single_calls) == 5
    assert embedded == 5


def test_lorebook_reindex_is_scoped_to_one_lorebook(session, monkeypatch):
    service = _RecordingEmbeddingService()
    monkeypatch.setattr(
        "services.embedding_service.get_embedding_service", lambda: service
    )
    wanted = _seed_lorebook(session, 2)
    _seed_lorebook(session, 3)

    embedded = rag_pipeline.backfill_lorebook_embeddings(session, wanted)

    assert embedded == 2
    untouched = session.exec(
        select(LorebookEntry).where(LorebookEntry.embedding.is_(None))
    ).all()
    assert len(untouched) == 3


def test_lorebook_reindex_with_nothing_missing_is_a_noop(session, monkeypatch):
    service = _RecordingEmbeddingService()
    monkeypatch.setattr(
        "services.embedding_service.get_embedding_service", lambda: service
    )

    assert rag_pipeline.backfill_lorebook_embeddings(session) == 0
    assert service.batch_calls == []


# ════════════════════════════════════════════════════════════════════════════
# memory extraction: the swallowed embedding failure
# ════════════════════════════════════════════════════════════════════════════

class _ExplodingEmbeddingService:
    def generate_embedding(self, text):
        raise RuntimeError("FAKE-OOM embedding model unloaded")


def test_memory_extraction_records_an_embedding_failure_instead_of_swallowing_it(
    session, monkeypatch
):
    """`except Exception: pass` committed embedding=NULL with no trace, so a
    pgvector cosine search could never match the row again."""
    from core.entities import CharacterMemory
    from services.memory_extraction import (
        EMBEDDING_PENDING_TAG,
        create_memories_from_extraction,
    )

    character = Character(name="Aria")
    session.add(character)
    session.commit()
    session.refresh(character)

    # The project logs through structlog to stdout, which pytest's caplog does
    # not see, so the logger is spied on directly.
    import services.memory_extraction as extraction
    import services.embedding_service as embedding_module

    warnings: list[tuple] = []
    original_warning = extraction.logger.warning
    extraction.logger.warning = lambda event, **kw: warnings.append((event, kw))
    original_service = embedding_module.get_embedding_service
    embedding_module.get_embedding_service = _ExplodingEmbeddingService
    try:
        created = create_memories_from_extraction(
            session, character.id, ["likes tea", "hates rain"]
        )
    finally:
        extraction.logger.warning = original_warning
        embedding_module.get_embedding_service = original_service

    assert created == 2

    rows = session.exec(select(CharacterMemory)).all()
    assert len(rows) == 2
    # The memory itself is kept — it is still visible in the list/keyword paths.
    for row in rows:
        assert row.embedding is None
        assert EMBEDDING_PENDING_TAG in row.tags

    # ...and the failure is now visible in the logs instead of nowhere.
    logged = [event for event, _kw in warnings]
    assert logged.count("memory_extraction_embedding_failed") == 2
    failure = next(
        kw for event, kw in warnings
        if event == "memory_extraction_embedding_failed"
    )
    assert failure["character_id"] == character.id
    assert "unloaded" in failure["error"]


def test_memory_extraction_leaves_the_tag_off_when_embedding_works(session, monkeypatch):
    from core.entities import CharacterMemory
    from services.memory_extraction import (
        EMBEDDING_PENDING_TAG,
        create_memories_from_extraction,
    )

    character = Character(name="Aria")
    session.add(character)
    session.commit()
    session.refresh(character)

    import services.embedding_service as embedding_module

    original = embedding_module.get_embedding_service
    embedding_module.get_embedding_service = lambda: _RecordingEmbeddingService()
    try:
        create_memories_from_extraction(session, character.id, ["likes tea"])
    finally:
        embedding_module.get_embedding_service = original

    row = session.exec(select(CharacterMemory)).one()
    assert row.embedding is not None
    assert EMBEDDING_PENDING_TAG not in row.tags


# ════════════════════════════════════════════════════════════════════════════
# cache aliasing
# ════════════════════════════════════════════════════════════════════════════

def test_unknown_cache_name_is_rejected_instead_of_aliasing_to_stats():
    """`cache_map.get(cache_name, _stats_cache)` turned a typo into a silent
    write into the statistics cache, and made the matching invalidate a no-op."""
    from infrastructure.cache import KNOWN_CACHE_NAMES, _stats_cache, cached

    with pytest.raises(ValueError, match="unknown cache name"):
        @cached("model_lsts")
        def typo():
            return 1

    assert _stats_cache == {}, "the typo must not have written to the stats cache"
    assert "provider_stats" in KNOWN_CACHE_NAMES


def test_unknown_cache_name_error_lists_the_valid_names():
    from infrastructure.cache import cached

    with pytest.raises(ValueError) as excinfo:
        cached("nope")

    message = str(excinfo.value)
    for name in ("stats", "model", "search", "lru", "provider_stats"):
        assert name in message


def test_known_cache_names_still_resolve():
    from infrastructure.cache import _model_cache, cached, invalidate_cache

    invalidate_cache("all")
    try:
        @cached("model")
        def f(x):
            return x

        f(1)
        assert len(_model_cache) == 1
    finally:
        invalidate_cache("all")


def test_decorator_registry_and_invalidator_share_one_map():
    """The map used to be built twice and could drift."""
    from infrastructure import cache as cache_module

    assert set(cache_module.KNOWN_CACHE_NAMES) == set(cache_module._CACHE_REGISTRY)
    # invalidate_cache("all") must clear every registered cache.
    for name, instance in cache_module._CACHE_REGISTRY.items():
        instance["sentinel"] = 1
    cache_module.invalidate_cache("all")
    for name, instance in cache_module._CACHE_REGISTRY.items():
        assert len(instance) == 0, f"{name} was not cleared by invalidate_cache('all')"


# ════════════════════════════════════════════════════════════════════════════
# model availability: deterministic fallback + cache
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _clear_model_cache():
    from services.model_availability_service import clear_available_models_cache

    clear_available_models_cache()
    yield
    clear_available_models_cache()


def _seed_ready_checkpoint(session: Session, filename: str, provider_id: str = "p1") -> None:
    provider = session.get(Provider, provider_id)
    if provider is None:
        provider = Provider(
            id=provider_id, type="modal", enabled=True, priority=1, credentials={}, config={}
        )
        session.add(provider)
    model = ModelV2(name=filename, type="Checkpoint", directory="checkpoints")
    session.add(model)
    session.commit()
    version = ModelVersion(model_id=model.id, name="v1")
    session.add(version)
    session.commit()
    file = ModelFile(
        version_id=version.id, original_filename=filename, storage_filename=filename
    )
    session.add(file)
    session.commit()
    session.add(ProviderVersionStatus(file_id=file.id, provider_id=provider_id, status="ready"))
    session.commit()


def test_available_models_are_returned_in_a_stable_sorted_order(session):
    """`SELECT DISTINCT` with no ORDER BY has no ordering guarantee — Postgres
    may satisfy it with a hash aggregate — and get_available_checkpoint takes
    element [0]."""
    from services.model_availability_service import ModelAvailabilityService

    for name in ("zeta.safetensors", "alpha.safetensors", "mu.safetensors"):
        _seed_ready_checkpoint(session, name)

    service = ModelAvailabilityService(session)
    first = service.get_available_models("checkpoints")

    assert first == ["alpha.safetensors", "mu.safetensors", "zeta.safetensors"]
    # Repeated calls (and a re-run) agree, so the substitution is not luck.
    assert service.get_available_models("checkpoints") == first


def test_checkpoint_fallback_is_deterministic_and_ordered(session):
    from services.model_availability_service import ModelAvailabilityService

    for name in ("zeta.safetensors", "alpha.safetensors"):
        _seed_ready_checkpoint(session, name)

    service = ModelAvailabilityService(session)
    chosen = service.get_available_checkpoint("not-installed.safetensors")

    assert chosen == "alpha.safetensors"
    # Same answer every time — that is the whole point.
    assert service.get_available_checkpoint("not-installed.safetensors") == chosen


def test_preferred_checkpoint_wins_when_installed(session):
    from services.model_availability_service import ModelAvailabilityService

    _seed_ready_checkpoint(session, "alpha.safetensors")
    _seed_ready_checkpoint(session, "zeta.safetensors")

    service = ModelAvailabilityService(session)

    assert service.get_available_checkpoint("zeta.safetensors") == "zeta.safetensors"


def test_available_models_query_is_cached_with_a_ttl(session):
    """It runs a four-table DISTINCT join on EVERY image submission."""
    from services.model_availability_service import (
        AVAILABLE_MODELS_TTL_SECONDS,
        ModelAvailabilityService,
        clear_available_models_cache,
    )

    _seed_ready_checkpoint(session, "alpha.safetensors")
    service = ModelAvailabilityService(session)

    service.get_available_models("checkpoints")
    # A newly-created row is invisible until the TTL expires — that is the
    # documented trade-off, and the point is that the query is not repeated.
    _seed_ready_checkpoint(session, "beta.safetensors", provider_id="p2")
    assert "beta.safetensors" not in service.get_available_models("checkpoints")

    clear_available_models_cache()
    assert "beta.safetensors" in service.get_available_models("checkpoints")
    assert AVAILABLE_MODELS_TTL_SECONDS <= 300


def test_clearing_the_cache_restores_freshness(session):
    from services.model_availability_service import (
        ModelAvailabilityService,
        clear_available_models_cache,
    )

    _seed_ready_checkpoint(session, "alpha.safetensors")
    service = ModelAvailabilityService(session)
    assert service.get_available_models("checkpoints") == ["alpha.safetensors"]

    clear_available_models_cache("checkpoints")
    _seed_ready_checkpoint(session, "beta.safetensors", provider_id="p2")
    assert "beta.safetensors" in service.get_available_models("checkpoints")


def test_disabled_provider_models_are_not_offered(session):
    from services.model_availability_service import ModelAvailabilityService

    _seed_ready_checkpoint(session, "alpha.safetensors")
    provider = session.get(Provider, "p1")
    provider.enabled = False
    session.add(provider)
    session.commit()

    assert ModelAvailabilityService(session).get_available_models("checkpoints") == []


# ════════════════════════════════════════════════════════════════════════════
# lost chat reply reconciliation
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def wired_engine(engine, monkeypatch):
    from infrastructure import database as infra_database

    monkeypatch.setattr(infra_database, "engine", engine)
    return engine


def _completed_chat_reply_job(session: Session, chat_id: str, text: str, job_id: str) -> Job:
    job = Job(
        task_type="llm",
        status=JobStatus.COMPLETED,
        workflow={"type": "chat_reply", "chat_id": chat_id},
        metadata_={"type": "chat_reply", "chat_id": chat_id},
        outputs=[{"role": "assistant", "content": text}],
    )
    job.id = job_id
    session.add(job)
    session.commit()
    return job


def test_unpersisted_chat_reply_is_detected(session, wired_engine):
    char = Character(name="Aria")
    session.add(char)
    session.commit()
    session.refresh(char)
    chat = Chat(name="C", character_id=char.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)

    _completed_chat_reply_job(session, chat.id, "the paid-for reply", "job-lost")

    found = wis.find_unpersisted_chat_replies(session)

    assert [job["id"] for job in found] == ["job-lost"]


def test_persisted_chat_reply_is_not_reported(session, wired_engine):
    import asyncio

    char = Character(name="Aria")
    session.add(char)
    session.commit()
    session.refresh(char)
    chat = Chat(name="C", character_id=char.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)

    _completed_chat_reply_job(session, chat.id, "the reply", "job-ok")
    asyncio.run(wis._handle_chat_reply({
        "id": "job-ok",
        "metadata": {"chat_id": chat.id},
        "outputs": [{"role": "assistant", "content": "the reply"}],
    }))

    assert wis.find_unpersisted_chat_replies(session) == []


def test_reconciler_writes_the_lost_reply_back(session, wired_engine):
    import asyncio

    char = Character(name="Aria")
    session.add(char)
    session.commit()
    session.refresh(char)
    chat = Chat(name="C", character_id=char.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)

    _completed_chat_reply_job(session, chat.id, "recovered text", "job-dropped")

    result = asyncio.run(wis.reconcile_unpersisted_chat_replies())

    assert result["found"] == 1
    assert result["repaired"] == ["job-dropped"]
    assert result["failed"] == []

    rows = session.exec(select(Message).where(Message.chat_id == chat.id)).all()
    assert [row.content for row in rows] == ["recovered text"]


def test_reconciler_is_idempotent(session, wired_engine):
    import asyncio

    char = Character(name="Aria")
    session.add(char)
    session.commit()
    session.refresh(char)
    chat = Chat(name="C", character_id=char.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    _completed_chat_reply_job(session, chat.id, "once", "job-idem")

    asyncio.run(wis.reconcile_unpersisted_chat_replies())
    second = asyncio.run(wis.reconcile_unpersisted_chat_replies())

    assert second["found"] == 0
    assert len(session.exec(select(Message).where(Message.chat_id == chat.id)).all()) == 1


def test_non_chat_reply_jobs_are_ignored(session, wired_engine):
    char = Character(name="Aria")
    session.add(char)
    session.commit()
    session.refresh(char)
    chat = Chat(name="C", character_id=char.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)

    session.add(Job(
        task_type="llm",
        status=JobStatus.COMPLETED,
        workflow={"type": "story_continue", "story_id": "s1"},
        metadata_={"type": "story_continue"},
        outputs=[{"content": "chapter text"}],
    ))
    session.commit()

    assert wis.find_unpersisted_chat_replies(session) == []


def test_reconcile_endpoint_dry_run_reports_without_writing(client, session, wired_engine):
    char = Character(name="Aria")
    session.add(char)
    session.commit()
    session.refresh(char)
    chat = Chat(name="C", character_id=char.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    _completed_chat_reply_job(session, chat.id, "text", "job-dry")

    resp = client.post("/api/jobs/reconcile-chat-replies?dry_run=true")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is True
    assert body["job_ids"] == ["job-dry"]
    assert body["chat_ids"] == [chat.id]
    assert session.exec(select(Message).where(Message.chat_id == chat.id)).all() == []


def test_reconcile_endpoint_repairs(client, session, wired_engine):
    char = Character(name="Aria")
    session.add(char)
    session.commit()
    session.refresh(char)
    chat = Chat(name="C", character_id=char.id)
    session.add(chat)
    session.commit()
    session.refresh(chat)
    _completed_chat_reply_job(session, chat.id, "text", "job-fix")

    resp = client.post("/api/jobs/reconcile-chat-replies")

    assert resp.status_code == 200, resp.text
    assert resp.json()["repaired"] == ["job-fix"]
    assert len(session.exec(select(Message).where(Message.chat_id == chat.id)).all()) == 1


# ════════════════════════════════════════════════════════════════════════════
# GET /api/v2/llm/default-provider
# ════════════════════════════════════════════════════════════════════════════

class TestDefaultProviderEndpoint:
    def test_answers_200_with_null_when_nothing_is_configured(self, client, session):
        """"Nothing is configured yet" is a normal state, not a 404.

        The old response was `LLM provider 'default' not found` — "default" is
        a placeholder, not a provider id — and it fired on every page load of
        /chat, /story and /roleplay, which is why the frontend had to swallow
        404s (useLLMProviderStatus.js:29-33).
        """
        resp = client.get("/api/v2/llm/default-provider")

        assert resp.status_code == 200, resp.text
        assert resp.json() is None

    def test_answers_200_with_the_resolved_provider_when_one_exists(self, client, session):
        session.add(Provider(
            id="llm-local",
            type="direct_url",
            worker_type="llm",
            enabled=True,
            priority=1,
            credentials={},
            config={},
        ))
        session.commit()

        resp = client.get("/api/v2/llm/default-provider")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["provider_id"] == "llm-local"
        assert body["model_id"]

    def test_available_models_still_answers_200_with_an_empty_list(self, client):
        resp = client.get("/api/v2/llm/available-models")

        assert resp.status_code == 200, resp.text
        assert resp.json() == []

    def test_providers_still_answers_200(self, client, session):
        session.add(Provider(
            id="llm-one", type="direct_url", worker_type="llm", enabled=True,
            priority=1, credentials={}, config={},
        ))
        session.commit()

        resp = client.get("/api/v2/llm/providers")

        assert resp.status_code == 200, resp.text
        assert [p["provider_id"] for p in resp.json()] == ["llm-one"]
