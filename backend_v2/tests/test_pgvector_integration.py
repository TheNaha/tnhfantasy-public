"""
Opt-in PostgreSQL + pgvector integration tests (Phase 4).

These exercise the *production* DB path that the in-memory SQLite unit suite
cannot: Postgres + the `vector` extension + a real `Vector(384)` embedding
column + `cosine_distance` similarity search (the exact pattern used by
`api/routes/world_vault/lorebooks.py`).

They are **skipped by default**. To run them, point PGVECTOR_TEST_URL at a
throwaway, pgvector-enabled Postgres (NOT the live DB) and execute:

    PGVECTOR_TEST_URL="postgresql://postgres:pass@localhost:5433/comfy_test" \\
        python -m pytest backend_v2/tests/test_pgvector_integration.py -v

Run a throwaway pgvector instance for local verification:

    docker run --rm -d --name pgvector-test \
        -e POSTGRES_PASSWORD=pass -e POSTGRES_USER=postgres -e POSTGRES_DB=comfy_test \
        -p 5433:5432 pgvector/pgvector:pg16
"""
import os

import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from core.entities import Lorebook, LorebookEntry


PG_URL = os.getenv("PGVECTOR_TEST_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="PGVECTOR_TEST_URL not set — pgvector profile skipped (opt-in).",
)


def _unit_vector(dim: int = 384, at: int = 0) -> list[float]:
    """384-dim unit vector (matches all-MiniLM-L6-v2) with 1.0 at index `at`.

    Vectors at distinct indices are orthogonal -> cosine distance 1, which gives
    a deterministic, assertion-stable ordering."""
    vec = [0.0] * dim
    vec[at] = 1.0
    return vec


@pytest.fixture
def pg_engine():
    engine = create_engine(PG_URL)
    # Ensure pgvector is installed, then (re)create only the two tables we test.
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("DROP TABLE IF EXISTS lorebook_entries"))
        conn.execute(text("DROP TABLE IF EXISTS lorebooks"))
    Lorebook.__table__.create(engine)
    LorebookEntry.__table__.create(engine)
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS lorebook_entries"))
        conn.execute(text("DROP TABLE IF EXISTS lorebooks"))
    engine.dispose()


def test_vector_extension_is_available(pg_engine):
    with pg_engine.begin() as conn:
        ext = conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
    assert ext == "vector"


def test_vector_embedding_persists_and_similarity_searches(pg_engine):
    with Session(pg_engine) as session:
        lb = Lorebook(id="lb-vec-test", name="Vector Test")
        session.add(lb)
        session.commit()

        session.add(LorebookEntry(lorebook_id=lb.id, content="alpha", embedding=_unit_vector(at=0)))
        session.add(LorebookEntry(lorebook_id=lb.id, content="beta", embedding=_unit_vector(at=1)))
        session.commit()

        # Query vector is identical to "alpha" (index 0): cosine distance 0 for
        # alpha, 1 for beta -> ORDER BY ... ASC returns alpha first. This mirrors
        # the production search in lorebooks.py (cosine_distance).
        rows = session.exec(
            select(LorebookEntry)
            .where(LorebookEntry.embedding.is_not(None))
            .order_by(LorebookEntry.embedding.cosine_distance(_unit_vector(at=0)))
        ).all()

        assert len(rows) == 2
        assert rows[0].content == "alpha"
        assert rows[1].content == "beta"
