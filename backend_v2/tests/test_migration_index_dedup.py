"""Index de-duplication: the signature that decides "already indexed".

`SQLModel.metadata.create_all` runs immediately before the steps runner on a
fresh install, so every `Index(...)` in an entity's `__table_args__` and every
`Field(index=True)` already exists by the time a migration runs. Several
migrations then created a *second* index on the same column under a different
name, and nothing flagged it: each index is individually correct, which is why
the pair survived four audits. The cost was measured on this deployment — two
identical btrees maintained on every write, a planner choosing between two
indexes with identical definitions, and `idx_provider_status_legacy` reporting
`idx_tup_read = 1,867,540` against `idx_tup_fetch = 34`.

`_index_signature` is the comparison that makes "already indexed" mean
*equivalent*, not merely same-named. It is deliberately conservative: anything it
cannot compare exactly is `None`, which reads as "not equivalent", so an opclass,
a partial predicate or an expression can never be silently treated as a plain
column.
"""
import pytest

from infrastructure.migrations.steps import (
    _DUPLICATE_INDEX_TWINS,
    _index_signature,
    _migration_083_drop_duplicate_entity_indexes,
)


class TestIndexSignature:
    @pytest.mark.parametrize("definition", [
        "CREATE INDEX idx_file_version ON public.model_files USING btree (version_id)",
        "CREATE INDEX ix_model_files_version_id ON model_files USING btree (version_id)",
        "CREATE INDEX ix ON public.model_files USING BTREE (version_id)",
    ])
    def test_the_same_index_under_two_names_has_one_signature(self, definition):
        assert _index_signature(definition) == "model_files:version_id:nonunique"

    def test_a_unique_index_is_not_the_same_as_a_plain_one(self):
        unique = _index_signature(
            "CREATE UNIQUE INDEX uq_civitai_version_id ON public.model_versions "
            "USING btree (civitai_version_id)"
        )
        plain = _index_signature(
            "CREATE INDEX ix_model_versions_civitai_version_id ON public.model_versions "
            "USING btree (civitai_version_id)"
        )
        assert unique == "model_versions:civitai_version_id:unique"
        assert plain == "model_versions:civitai_version_id:nonunique"
        assert unique != plain

    def test_column_order_matters(self):
        a = _index_signature("CREATE INDEX i ON t USING btree (user_id, signature)")
        b = _index_signature("CREATE INDEX i ON t USING btree (signature, user_id)")
        assert a != b, "a btree on (a,b) cannot serve a prefix query on (b,a)"

    def test_the_schema_is_dropped_from_both_sides(self):
        """`pg_indexes.indexdef` is always schema-qualified and the migration's
        DDL strings never are, so without this nothing ever compares equal."""
        assert _index_signature("CREATE INDEX i ON public.sessions USING btree (user_id)") == (
            _index_signature("CREATE INDEX i ON sessions USING btree (user_id)")
        )

    @pytest.mark.parametrize("definition", [
        "CREATE INDEX i ON t USING gin (tags)",
        "CREATE INDEX i ON t USING btree (a) WHERE a > 1",
        "CREATE INDEX i ON t USING btree (lower(name))",
        "CREATE INDEX i ON t USING btree (a DESC)",
        "CREATE INDEX i ON t USING hnsw (embedding vector_cosine_ops)",
        "not an index definition",
        "",
    ])
    def test_anything_it_cannot_compare_exactly_is_none(self, definition):
        assert _index_signature(definition) is None


class TestDuplicateIndexList:
    def test_every_entry_names_a_keeper(self):
        """An entry with no keeper is a drop of the only index on a column.

        That mistake shipped once: `ix_model_files_civitai_file_id` was listed
        with `kept=None` and migration 083 removed the only index on that
        column, which migration 084 then had to put back.
        """
        unkept = [(t, n) for t, n, kept, _cols in _DUPLICATE_INDEX_TWINS if kept is None]
        assert unkept == [], f"these entries would drop the only index on their column: {unkept}"

    def test_no_index_is_listed_twice(self):
        names = [name for _t, name, _k, _c in _DUPLICATE_INDEX_TWINS]
        assert len(names) == len(set(names)), "a duplicate entry would try to drop twice"

    def test_the_kept_index_is_never_also_dropped(self):
        dropped = {name for _t, name, _k, _c in _DUPLICATE_INDEX_TWINS}
        kept = {kept for _t, _n, kept, _c in _DUPLICATE_INDEX_TWINS if kept}
        assert not (dropped & kept), f"an index is both kept and dropped: {dropped & kept}"


class TestMigration083IsANoOpOnSqlite:
    def test_it_returns_true_without_touching_anything(self):
        """SQLite stores these tables differently and the tests run on SQLite, so
        the step must be a clean no-op there rather than an error."""

        class _Conn:
            dialect = type("D", (), {"name": "sqlite"})()

            def execute(self, *args, **kwargs):  # pragma: no cover - must not run
                raise AssertionError("Postgres DDL must not run on SQLite")

        assert _migration_083_drop_duplicate_entity_indexes(_Conn()) is True