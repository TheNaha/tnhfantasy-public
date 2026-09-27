# Tests for model-tag provenance: `model_tags.source` and the user-tag writer.
#
# `_apply_civitai_metadata` used to `delete(ModelTag).where(model_id == ...)` —
# every tag on the model, whatever wrote it — and there was no writer path for
# a user tag at all, so a resync could only ever destroy. The column records who
# owns a row so the resync replaces only its own.

import pytest
from sqlmodel import select

from api.routes.models.maintenance import (
    MODEL_TAG_SOURCE_CIVITAI,
    MODEL_TAG_SOURCE_USER,
    _apply_civitai_metadata,
    add_user_model_tag,
    list_model_tags,
    remove_user_model_tag,
)
from core.entities import ModelTag, ModelV2

CIVITAI_PAYLOAD = {
    "name": "Boob Tent",
    "description": "A character LoRA.",
    "nsfw": False,
    "creator": {"username": "someuser"},
    "stats": {"downloadCount": 10, "thumbsUpCount": 2},
    "tags": ["boob tent", "breasts", "clothing"],
    "modelVersions": [],
}


@pytest.fixture(name="model")
def model_fixture(session):
    m = ModelV2(name="Boob Tent", type="LORA", directory="loras")
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _tags(session, model_id):
    return {t.tag: t.source for t in session.exec(select(ModelTag).where(ModelTag.model_id == model_id)).all()}


# ── resync scope ────────────────────────────────────────────────────────────

def test_resync_does_not_destroy_a_user_tag(session, model):
    """The bug: a hand-typed tag was deleted by the next resync."""
    add_user_model_tag(session, model.id, "character-loRA")
    _apply_civitai_metadata(model, CIVITAI_PAYLOAD, session)
    session.commit()

    tags = _tags(session, model.id)
    assert tags["character-loRA"] == MODEL_TAG_SOURCE_USER
    # ...and CivitAI's own tags still land.
    assert tags["boob tent"] == MODEL_TAG_SOURCE_CIVITAI


def test_resync_still_replaces_its_own_tags(session, model):
    add_user_model_tag(session, model.id, "character-loRA")
    _apply_civitai_metadata(model, CIVITAI_PAYLOAD, session)
    session.commit()

    # CivitAI dropped a tag upstream: it must not linger as a stale row.
    _apply_civitai_metadata(model, {**CIVITAI_PAYLOAD, "tags": ["boob tent"]}, session)
    session.commit()

    assert "breasts" not in _tags(session, model.id)
    assert "character-loRA" in _tags(session, model.id)


def test_resync_does_not_duplicate_a_tag_both_sources_know(session, model):
    """uq_model_tag is on (model_id, tag), so a shared tag is stored once."""
    add_user_model_tag(session, model.id, "boob tent")
    _apply_civitai_metadata(model, CIVITAI_PAYLOAD, session)
    session.commit()

    tags = _tags(session, model.id)
    assert list(tags).count("boob tent") == 1
    # The user's row wins, so their tag is not silently downgraded to a
    # scraped one (and so it is not deleted by the next resync).
    assert tags["boob tent"] == MODEL_TAG_SOURCE_USER


def test_resync_trims_and_skips_empty_civitai_tags(session, model):
    _apply_civitai_metadata(model, {**CIVITAI_PAYLOAD, "tags": ["  spaced  ", "", "   ", "ok"]}, session)
    session.commit()
    assert "spaced" in _tags(session, model.id)
    assert "" not in _tags(session, model.id)


# ── the user writer path ────────────────────────────────────────────────────

def test_add_user_tag_is_user_sourced(session, model):
    result = add_user_model_tag(session, model.id, "pose: kneeling")
    assert result == {"tag": "pose: kneeling", "source": MODEL_TAG_SOURCE_USER, "created": True}
    assert _tags(session, model.id) == {"pose: kneeling": MODEL_TAG_SOURCE_USER}


def test_add_user_tag_is_idempotent(session, model):
    add_user_model_tag(session, model.id, "pose: kneeling")
    second = add_user_model_tag(session, model.id, "  pose:   kneeling  ")
    assert second["created"] is False
    assert len(_tags(session, model.id)) == 1


def test_add_user_tag_rejects_empty(session, model):
    from core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        add_user_model_tag(session, model.id, "   ")


def test_add_user_tag_bounds_tag_length(session, model):
    from core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        add_user_model_tag(session, model.id, "x" * 65)


def test_add_user_tag_404s_on_an_unknown_model(session):
    from core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        add_user_model_tag(session, "no-such-model", "tag")


def test_remove_user_tag_deletes_only_user_rows(session, model):
    add_user_model_tag(session, model.id, "mine")
    _apply_civitai_metadata(model, CIVITAI_PAYLOAD, session)
    session.commit()

    assert remove_user_model_tag(session, model.id, "mine") is True
    assert "mine" not in _tags(session, model.id)
    # A scraped tag is not the user's to delete, and the next resync would put
    # it straight back anyway.
    assert remove_user_model_tag(session, model.id, "boob tent") is False
    assert "boob tent" in _tags(session, model.id)


def test_remove_user_tag_reports_a_miss(session, model):
    assert remove_user_model_tag(session, model.id, "never-added") is False


def test_list_model_tags_reports_provenance(session, model):
    add_user_model_tag(session, model.id, "mine")
    _apply_civitai_metadata(model, CIVITAI_PAYLOAD, session)
    session.commit()

    assert list_model_tags(session, model.id) == [
        {"tag": "boob tent", "source": MODEL_TAG_SOURCE_CIVITAI},
        {"tag": "breasts", "source": MODEL_TAG_SOURCE_CIVITAI},
        {"tag": "clothing", "source": MODEL_TAG_SOURCE_CIVITAI},
        {"tag": "mine", "source": MODEL_TAG_SOURCE_USER},
    ]


# ── the endpoint ────────────────────────────────────────────────────────────

def test_tag_endpoints_round_trip(client, model):
    created = client.post(f"/api/v2/models/maintenance/{model.id}/tags", json={"tag": "character-loRA"})
    assert created.status_code == 201
    assert created.json()["source"] == MODEL_TAG_SOURCE_USER

    listed = client.get(f"/api/v2/models/maintenance/{model.id}/tags")
    assert listed.status_code == 200
    assert {"tag": "character-loRA", "source": MODEL_TAG_SOURCE_USER} in listed.json()["tags"]

    removed = client.delete(f"/api/v2/models/maintenance/{model.id}/tags/character-loRA")
    assert removed.status_code == 200
    assert client.get(f"/api/v2/models/maintenance/{model.id}/tags").json()["tags"] == []


def test_tag_endpoint_404s_on_an_unknown_model(client):
    assert client.post("/api/v2/models/maintenance/nope/tags", json={"tag": "x"}).status_code == 404
    assert client.delete("/api/v2/models/maintenance/nope/tags/x").status_code == 404


def test_tag_endpoint_404s_when_removing_a_civitai_tag(client, model, sample_model_v2_data):
    client.post("/api/v2/models", json=sample_model_v2_data)
    models = client.get("/api/v2/models/all").json()
    civitai_model = next(m for m in models if m["civitai_model_id"] == 12345)

    # "anime" came from the import, so it is civitai-sourced and not removable.
    assert client.delete(f"/api/v2/models/maintenance/{civitai_model['id']}/tags/anime").status_code == 404


def test_tag_endpoint_rejects_an_empty_tag(client, model):
    response = client.post(f"/api/v2/models/maintenance/{model.id}/tags", json={"tag": "  "})
    assert response.status_code in (400, 422)


# ── the migration ───────────────────────────────────────────────────────────

def test_migration_071_adds_and_backfills_the_source_column(tmp_path):
    """Every pre-existing row is a scraped tag, so all of them must be owned by
    'civitai' — a NULL source would match neither the resync delete filter nor
    the user add/remove paths, i.e. an invisible tag."""
    from sqlalchemy import create_engine, inspect, text

    from infrastructure.migrations.steps import _migration_071_add_model_tag_source

    engine = create_engine(f"sqlite:///{tmp_path / 'tags.db'}")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE model_tags (
                id VARCHAR PRIMARY KEY,
                model_id VARCHAR NOT NULL,
                tag VARCHAR NOT NULL,
                CONSTRAINT uq_model_tag UNIQUE (model_id, tag)
            )
        """))
        conn.execute(text(
            "INSERT INTO model_tags (id, model_id, tag) VALUES ('t1', 'm1', 'anime')"
        ))

    with engine.begin() as conn:
        assert _migration_071_add_model_tag_source(conn) is True
        columns = {c["name"] for c in inspect(conn).get_columns("model_tags")}
        rows = conn.execute(text("SELECT tag, source FROM model_tags")).all()

    assert "source" in columns
    assert rows == [("anime", "civitai")]

    # Idempotent: a second run must not fail on the already-added column.
    with engine.begin() as conn:
        assert _migration_071_add_model_tag_source(conn) is False


def test_migration_071_is_skipped_without_the_table(tmp_path):
    from sqlalchemy import create_engine

    from infrastructure.migrations.steps import _migration_071_add_model_tag_source

    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with engine.begin() as conn:
        assert _migration_071_add_model_tag_source(conn) is False


def test_migration_071_is_registered_after_070():
    from infrastructure.migrations.steps import _get_schema_migration_steps

    versions = [s.version for s in _get_schema_migration_steps()]
    assert "071_add_model_tag_source" in versions
    assert versions.index("071_add_model_tag_source") > versions.index("070_create_sessions")


def test_model_tag_source_defaults_to_civitai(session, model):
    """Every existing writer constructs ModelTag without a source; the column
    default is what keeps them CivitAI-owned without touching them."""
    session.add(ModelTag(model_id=model.id, tag="implicit"))
    session.commit()
    assert _tags(session, model.id) == {"implicit": MODEL_TAG_SOURCE_CIVITAI}
