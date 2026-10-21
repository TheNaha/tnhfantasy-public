"""Regression tests for audit-2026-10-21 findings 4 and 12: the pgvector
lorebook path ignored `enabled`, and the `probability` / `selective_logic`
columns were write-only.

Finding 4: the semantic (embedding-distance) path selected rows by distance
alone. The keyword path checked `entry_is_enabled` and the always-on path
checked it too, so a DISABLED entry was injected into the PAID prompt by
exactly one of the three paths. The SQLite test path never took the semantic
branch, so no test saw it.

Finding 12: `LorebookEntry.probability`, `.selective_logic` and `.depth` were
imported, exported and never consulted. `probability` is a percentage chance
to activate and `selective_logic` is SillyTavern's AND/OR combination rule;
both are implemented here. `depth` is an INSERTION position in SillyTavern
and this vault's prompt assembly does not read it, so it stays
accepted-but-not-acted-on.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from core.entities import Lorebook, LorebookEntry


def _seed_lorebook(session: Session) -> Lorebook:
    lb = Lorebook(name="Book", description="d")
    session.add(lb)
    session.commit()
    session.refresh(lb)
    return lb


def _add_entry(session: Session, lorebook_id: str, **kwargs) -> LorebookEntry:
    entry = LorebookEntry(lorebook_id=lorebook_id, **kwargs)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@pytest.fixture
def semantic_distance(monkeypatch):
    """Make the pgvector distance operator work on SQLite.

    `LorebookEntry.embedding.cosine_distance(q)` renders pgvector's `<=>`
    operator, which SQLite does not have, so the semantic branch raised and
    the keyword path answered instead. Production runs on PostgreSQL, where
    the operator exists; the TEST path has to fake the DISTANCE, not the
    selection, so the branch under test is the real one.

    The fake distance is 0.0, i.e. "everything is within the cutoff", so
    what the query returns is decided by the WHERE clause under test and
    nothing else.
    """
    from pgvector.sqlalchemy import Vector
    from sqlalchemy import literal

    def _fake_cosine_distance(self, other):
        return literal(0.0)

    monkeypatch.setattr(
        Vector.Comparator, "cosine_distance", _fake_cosine_distance
    )


class TestTheSemanticPathHonoursEnabled:
    def test_a_disabled_entry_with_an_embedding_is_not_selected(
        self, session, semantic_distance
    ):
        from services.rag_pipeline import search_lorebook_entries

        lb = _seed_lorebook(session)
        disabled = _add_entry(
            session,
            lb.id,
            keys=["dragon"],
            content="The dragon sleeps in the vault.",
            embedding=[0.1] * 384,
            enabled=False,
        )
        enabled = _add_entry(
            session,
            lb.id,
            keys=["castle"],
            content="The castle stands on the cliff.",
            embedding=[0.2] * 384,
            enabled=True,
        )

        results = search_lorebook_entries(
            session,
            [lb.id],
            "dragon",
            limit=5,
            q_vec=[0.15] * 384,
            q_vec_computed=True,
        )

        returned = {e.id for e in results}
        assert disabled.id not in returned, "a disabled entry reached the prompt"
        # The enabled entry comes back even though its key does NOT match the
        # query — proof that the SEMANTIC branch ran and not the keyword one.
        assert enabled.id in returned

    def test_a_book_of_only_disabled_entries_returns_nothing(
        self, session, semantic_distance
    ):
        from services.rag_pipeline import search_lorebook_entries

        lb = _seed_lorebook(session)
        _add_entry(
            session,
            lb.id,
            keys=["dragon"],
            content="The dragon sleeps in the vault.",
            embedding=[0.1] * 384,
            enabled=False,
        )

        results = search_lorebook_entries(
            session,
            [lb.id],
            "dragon",
            limit=5,
            q_vec=[0.15] * 384,
            q_vec_computed=True,
        )

        assert results == []

    def test_the_keyword_path_agrees_with_the_semantic_one(self, session):
        """The two paths have to mean the same thing by "disabled"."""
        from services.rag_pipeline import search_lorebook_entries

        lb = _seed_lorebook(session)
        _add_entry(
            session,
            lb.id,
            keys=["dragon"],
            content="The dragon sleeps in the vault.",
            enabled=False,
        )

        results = search_lorebook_entries(session, [lb.id], "dragon", limit=5)
        assert results == []


class TestTheProbabilityGate:
    def test_a_zero_probability_entry_never_activates(self, session):
        from services.rag_pipeline import search_lorebook_entries

        lb = _seed_lorebook(session)
        entry = _add_entry(
            session,
            lb.id,
            keys=["dragon"],
            content="The dragon sleeps in the vault.",
            probability=0,
        )

        results = search_lorebook_entries(session, [lb.id], "dragon", limit=5)
        assert entry.id not in {e.id for e in results}

    def test_a_full_probability_entry_always_activates(self, session):
        from services.rag_pipeline import search_lorebook_entries

        lb = _seed_lorebook(session)
        entry = _add_entry(
            session,
            lb.id,
            keys=["dragon"],
            content="The dragon sleeps in the vault.",
            probability=100,
        )

        results = search_lorebook_entries(session, [lb.id], "dragon", limit=5)
        assert entry.id in {e.id for e in results}

    def test_an_unset_probability_always_activates(self, session):
        from services.rag_pipeline import search_lorebook_entries

        lb = _seed_lorebook(session)
        entry = _add_entry(
            session,
            lb.id,
            keys=["dragon"],
            content="The dragon sleeps in the vault.",
        )

        results = search_lorebook_entries(session, [lb.id], "dragon", limit=5)
        assert entry.id in {e.id for e in results}

    def test_the_roll_decides(self):
        """The gate is a percentage, not a coin-flip in the dark."""
        from services.rag_pipeline import entry_passes_probability

        entry = LorebookEntry(lorebook_id="x", content="c", probability=30)

        # A roll of 0.10 is 10% — inside 30%.
        assert entry_passes_probability(entry, roll=0.10) is True
        # A roll of 0.90 is 90% — outside 30%.
        assert entry_passes_probability(entry, roll=0.90) is False

    def test_the_roll_is_not_taken_twice(self):
        """An entry at 50% must fire half the time, not a quarter.

        The gate is applied once, at the point the results are assembled. If
        the keyword path and the final filter both rolled it, the effective
        probability would be squared.
        """
        from services.rag_pipeline import entry_passes_probability, entry_matches_keys

        entry = LorebookEntry(
            lorebook_id="x", content="c", keys=["dragon"], probability=50
        )
        # The KEY rule is deterministic: it does not roll.
        assert entry_matches_keys(entry, "a dragon appears") is True
        assert entry_matches_keys(entry, "nothing here") is False
        # And the gate is a single decision.
        rolls = [0.4, 0.6]
        assert [entry_passes_probability(entry, roll=r) for r in rolls] == [True, False]

    def test_a_probability_of_one_hundred_is_always(self):
        from services.rag_pipeline import entry_passes_probability

        entry = LorebookEntry(lorebook_id="x", content="c", probability=100)
        assert entry_passes_probability(entry, roll=0.999) is True


class TestTheSelectiveLogicGate:
    def test_and_needs_both_the_primary_and_the_secondary_key(self, session):
        from services.rag_pipeline import search_lorebook_entries

        lb = _seed_lorebook(session)
        entry = _add_entry(
            session,
            lb.id,
            keys=["dragon"],
            secondary_keys=["sword"],
            selective_logic="0",
            content="The dragon guards a sword.",
        )
        # A filler that always matches, so the "the context must never be
        # empty" fallback does not run and mask the selective rule.
        _add_entry(
            session,
            lb.id,
            keys=["goblin"],
            content="A goblin watches.",
        )

        # Only the primary key: the entry is selective, so it does not fire.
        assert entry.id not in {
            e.id
            for e in search_lorebook_entries(session, [lb.id], "a dragon and a goblin", limit=5)
        }
        # Both keys: it fires.
        assert entry.id in {
            e.id
            for e in search_lorebook_entries(
                session, [lb.id], "a dragon and a sword and a goblin", limit=5
            )
        }

    def test_or_fires_on_either_key(self, session):
        from services.rag_pipeline import search_lorebook_entries

        lb = _seed_lorebook(session)
        entry = _add_entry(
            session,
            lb.id,
            keys=["dragon"],
            secondary_keys=["sword"],
            selective_logic="1",
            content="The dragon guards a sword.",
        )
        _add_entry(
            session,
            lb.id,
            keys=["goblin"],
            content="A goblin watches.",
        )

        assert entry.id in {
            e.id
            for e in search_lorebook_entries(session, [lb.id], "a sword and a goblin", limit=5)
        }
        assert entry.id in {
            e.id
            for e in search_lorebook_entries(session, [lb.id], "a dragon and a goblin", limit=5)
        }

    def test_the_keyword_path_agrees(self):
        from services.rag_pipeline import entry_matches_keys

        entry = LorebookEntry(
            lorebook_id="x",
            content="c",
            keys=["dragon"],
            secondary_keys=["sword"],
            selective_logic="1",
        )
        assert entry_matches_keys(entry, "only the sword") is True
        assert entry_matches_keys(entry, "only the dragon") is True
        assert entry_matches_keys(entry, "neither of them") is False


class TestTheDepthColumn:
    def test_depth_is_accepted_but_not_acted_on(self):
        """Documented, not silently ignored.

        `depth` is SillyTavern's INSERTION position. Honouring it means
        changing where `context_builder` puts the entry in the prompt, which
        is a different subsystem. The column is accepted, exported and
        readable; the activation rules do not read it.
        """
        from services.rag_pipeline import entry_matches_keys

        entry = LorebookEntry(
            lorebook_id="x", content="c", keys=["dragon"], depth=0
        )
        # A depth of 0 does not change whether the entry matches.
        assert entry_matches_keys(entry, "a dragon") is True
        assert entry_matches_keys(entry, "nothing") is False
