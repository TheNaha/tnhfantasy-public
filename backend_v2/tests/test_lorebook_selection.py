

class TestConstantEntriesSurviveSemanticSearch:
    """Always-on lore is not a *result* of relevance, so a relevance query
    must not filter it.

    `search_lorebook_entries`'s semantic branch selected only rows carrying an
    embedding. A keyless ("constant") entry has none until the backfill reaches
    it — a fresh SillyTavern import, the first turns after creating a lorebook,
    or any deployment where the embedding model never loaded. Those entries then
    did not appear at all, while the keyword path in the same function and
    `context_builder._load_constant_lorebook_entries` both treat them as
    always-on. The chat lost the cast's always-on facts precisely when the rest
    of the context was most relevant.

    Reproduced by making the pgvector query succeed and return one embedded row,
    which is the only way to reach the branch on SQLite.
    """

    @staticmethod
    def _session():
        from core.entities import Lorebook, LorebookEntry
        from sqlmodel import Session, SQLModel, create_engine

        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        s = Session(engine)
        s.add(Lorebook(id="lb1", name="World", character_id=None, chat_id=None, story_id=None))
        s.add(LorebookEntry(id="e_const", lorebook_id="lb1",
                             content="The Ashfall Kingdom is at war.",
                             keys=[], embedding=None))
        s.add(LorebookEntry(id="e_const2", lorebook_id="lb1",
                            content="The Order forbids open flame.",
                            keys=[], embedding=None))
        s.add(LorebookEntry(id="e_keyed", lorebook_id="lb1",
                            content="Ironhold keeps its gates shut.",
                            keys=["Ironhold"], embedding=[0.1] * 4))
        s.commit()
        return s

    @staticmethod
    def _patch_semantic(monkeypatch):
        """Force the semantic branch to succeed, returning one embedded row."""
        import services.rag_pipeline as rp
        from core.entities import LorebookEntry as _Entry
        from sqlmodel import Session as _Session, select

        real_exec = _Session.exec

        class _Rows:
            def __init__(self, session):
                self.session = session

            def all(self):
                return real_exec(
                    self.session, select(_Entry).where(_Entry.id == "e_keyed")
                ).all()

        def _exec(self, stmt, *a, **kw):
            try:
                params = stmt.compile().params
            except Exception:
                params = {}
            # The pgvector statement is the one carrying a float-vector bind.
            if any(isinstance(v, list) and v and isinstance(v[0], float)
                   for v in params.values()):
                return _Rows(self)
            return real_exec(self, stmt, *a, **kw)

        monkeypatch.setattr(rp, "_is_postgres", lambda session: True)
        monkeypatch.setattr(rp, "rag_enabled", lambda: True)
        monkeypatch.setattr(rp, "_try_embedding", lambda text: [0.2] * 4)
        monkeypatch.setattr(rp, "rag_max_distance", lambda: 10.0)
        monkeypatch.setattr(_Session, "exec", _exec)

    def test_keyless_entries_are_returned_alongside_semantic_results(self, monkeypatch):
        import services.rag_pipeline as rp

        session = self._session()
        self._patch_semantic(monkeypatch)

        results = rp.search_lorebook_entries(
            session, ["lb1"], "the gates of Ironhold", limit=5
        )

        ids = [e.id for e in results]
        assert "e_const" in ids, "always-on entry dropped by the semantic branch"
        assert "e_const2" in ids
        assert "e_keyed" in ids

    def test_the_budget_is_still_limit_across_both_sources(self, monkeypatch):
        """The always-on append is bounded, or it blows the paid prompt's budget."""
        import services.rag_pipeline as rp

        session = self._session()
        self._patch_semantic(monkeypatch)

        for limit in (1, 2, 3):
            results = rp.search_lorebook_entries(
                session, ["lb1"], "the gates of Ironhold", limit=limit
            )
            assert len(results) <= limit, (
                f"limit={limit} returned {len(results)} entries; "
                f"{[e.id for e in results]}"
            )

    def test_a_tight_budget_still_returns_at_least_the_semantic_hit(self, monkeypatch):
        """With limit=1 the relevance hit wins, and the constant is dropped.

        That is the right trade: `limit` is the budget the caller asked for and
        one row must be the most relevant one. It is also why this is not a
        silent regression — the entry is absent, not wrong.
        """
        import services.rag_pipeline as rp

        session = self._session()
        self._patch_semantic(monkeypatch)

        results = rp.search_lorebook_entries(session, ["lb1"], "gates", limit=1)
        assert [e.id for e in results] == ["e_keyed"]


class TestTheLorebookBudget:
    """The lorebook budget is one number, and it holds across both sources.

    Every entry is injected verbatim into a paid system prompt on every turn, so
    this is the knob that decides how much of an inference bill the World Vault
    spends. It was a bare `5` at each call site — twice in one function — which
    meant neither path could be re-budgeted with the other.
    """

    def test_the_budget_is_one_constant_used_at_both_call_sites(self):

        from services import context_builder

        assert hasattr(context_builder, "LOREBOOK_ENTRY_BUDGET")
        assert context_builder.LOREBOOK_ENTRY_BUDGET == 5
        source = open(context_builder.__file__).read()
        # A bare `limit=5` on either lorebook call would be a second budget.
        assert "limit=5" not in source, (
            "a lorebook call still passes a bare limit=5 instead of "
            "LOREBOOK_ENTRY_BUDGET"
        )

    def test_search_and_the_constant_fallback_agree_on_the_budget(self):
        """Two different numbers here is how one path quietly doubles the bill."""
        import inspect

        from services import context_builder
        from services import rag_pipeline

        assert context_builder.LOREBOOK_ENTRY_BUDGET == 5
        # rag_pipeline's own default is only a default; context_builder always
        # passes the budget explicitly, which the source check above pins.
        assert "limit" in inspect.signature(rag_pipeline.search_lorebook_entries).parameters
        assert "limit" in inspect.signature(
            context_builder._load_constant_lorebook_entries
        ).parameters
