# Tests for services/asset_reconciler.py (DB-backed asset index)


from sqlmodel import select

from core.entities import Asset
from services.asset_reconciler import (
    MAX_COMPACT_TAGS,
    MAX_COMPACT_TRAINED_WORDS,
    _compact_checkpoint_metadata,
    _compact_lora_entry,
    _compact_metadata,
    _derived_workspace,
    reconcile_asset,
    upsert_asset,
)


def _png_bytes(width: int = 8, height: int = 8) -> bytes:
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (120, 40, 200)).save(buf, format="PNG")
    return buf.getvalue()


# ── _derived_workspace ──────────────────────────────────────────────────────

def test_derived_workspace_prefers_job_metadata():
    assert _derived_workspace({"workspace": "story"}, {}) == "story"
    assert _derived_workspace({"workspace": "chat"}, {"workspace": "main"}) == "chat"


def test_derived_workspace_from_source():
    assert _derived_workspace({"source": "roleplay_scene"}, {}) == "chat"
    assert _derived_workspace({"source": "agentic_tool"}, {}) == "chat"
    assert _derived_workspace({"source": "chat_image"}, {}) == "chat"
    assert _derived_workspace({"source": "narrator"}, {}) == "chat"
    assert _derived_workspace({"source": "story_illustrate"}, {}) == "story"
    assert _derived_workspace({"source": "story_illustrate_prompt"}, {}) == "story"
    assert _derived_workspace({"source": "story"}, {}) == "story"


def test_derived_workspace_from_png_meta_then_default():
    assert _derived_workspace(None, {"workspace": "chat"}) == "chat"
    assert _derived_workspace({}, {}) == "main"
    assert _derived_workspace({"source": "text2img"}, {}) == "main"


# ── upsert_asset ────────────────────────────────────────────────────────────

def test_upsert_asset_inserts_row(session):
    upsert_asset(session, relative_path="main/2026/08/11/a.png", filename="a.png")
    rows = session.exec(select(Asset)).all()
    assert len(rows) == 1
    assert rows[0].workspace == "main"
    assert rows[0].user_id == "default_user"


def test_upsert_asset_idempotent_on_relative_path(session):
    upsert_asset(
        session,
        relative_path="chat/2026/08/11/b.png",
        filename="b.png",
        workspace="main",
        width=512,
    )
    upsert_asset(
        session,
        relative_path="chat/2026/08/11/b.png",
        filename="b.png",
        workspace="chat",
        width=1024,
    )
    rows = session.exec(select(Asset)).all()
    assert len(rows) == 1
    assert rows[0].workspace == "chat"
    assert rows[0].width == 1024


def test_upsert_asset_different_paths_distinct_rows(session):
    upsert_asset(session, relative_path="main/a.png", filename="a.png")
    upsert_asset(session, relative_path="main/b.png", filename="b.png")
    assert len(session.exec(select(Asset)).all()) == 2


# ── reconcile_asset ─────────────────────────────────────────────────────────

def test_reconcile_asset_creates_row_with_dimensions(session, tmp_path):
    png_path = tmp_path / "test.png"
    png_path.write_bytes(_png_bytes(10, 20))

    reconcile_asset(
        session,
        str(png_path),
        output_dir=str(tmp_path),
        workspace="main",
        job_metadata={"source": "text2img"},
    )

    rows = session.exec(select(Asset)).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.relative_path == "test.png"
    assert row.filename == "test.png"
    assert row.width == 10
    assert row.height == 20
    assert row.workspace == "main"


def test_reconcile_asset_derives_workspace_from_job_metadata(session, tmp_path):
    png_path = tmp_path / "scene.png"
    png_path.write_bytes(_png_bytes())

    reconcile_asset(
        session,
        str(png_path),
        output_dir=str(tmp_path),
        job_metadata={"source": "scene_illustrate", "character_id": "ch-1"},
    )

    row = session.exec(select(Asset)).one()
    assert row.workspace == "chat"


def test_reconcile_asset_skips_non_png(session, tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("not an image")
    reconcile_asset(session, str(txt), output_dir=str(tmp_path))
    assert session.exec(select(Asset)).all() == []


def test_reconcile_asset_updates_existing_row(session, tmp_path):
    from core.entities import Job

    png_path = tmp_path / "upd.png"
    png_path.write_bytes(_png_bytes())

    # Seed a Job row so _workspace_from_job can populate character/story columns
    job = Job(task_type="image", workflow={"nodes": {}}, metadata_={"workspace": "story", "story_id": "s-9"})
    session.add(job)
    session.commit()
    session.refresh(job)

    reconcile_asset(session, str(png_path), output_dir=str(tmp_path), workspace="main")
    reconcile_asset(
        session, str(png_path), output_dir=str(tmp_path),
        job_id=job.id, job_metadata={"workspace": "story", "story_id": "s-9"},
    )

    rows = session.exec(select(Asset)).all()
    assert len(rows) == 1
    assert rows[0].workspace == "story"
    assert rows[0].story_id == "s-9"
    assert rows[0].deleted_at is None


# ── LoRA / checkpoint compaction ────────────────────────────────────────────

# The uncompacted shape read off a real legacy sidecar. Every field after
# "weight" was being dropped, which is why "show me images that used this
# LoRA" was only answerable by filename string and never by model id.
LEGACY_LORA_ENTRY = {
    "name": "boob_tent.safetensors",
    "display_name": "Boob Tent",
    "filename": "boob_tent.safetensors",
    "model_id": 21,
    "civitai_id": 1009342,
    "base_model": "Illustrious",
    "trained_words": ["boob tent"],
    "tags": ["boob tent", "breasts", "clothing"],
    "strength": 0.8,
    "weight": 0.8,
}


def test_compact_lora_entry_keeps_the_ids_and_search_keys():
    compact = _compact_lora_entry(LEGACY_LORA_ENTRY)

    assert compact["model_id"] == 21
    assert compact["civitai_id"] == 1009342
    assert compact["base_model"] == "Illustrious"
    assert compact["trained_words"] == ["boob tent"]
    assert compact["tags"] == ["boob tent", "breasts", "clothing"]
    # The display fields the gallery UI reads are untouched.
    assert compact["name"] == "boob_tent.safetensors"
    assert compact["display_name"] == "Boob Tent"
    assert compact["strength"] == 0.8
    assert compact["weight"] == 0.8


def test_compact_lora_entry_bounds_the_tag_array():
    """The full CivitAI array would be written into every asset's JSONB, so it
    is capped; model_tags keeps the full list."""
    many = {**LEGACY_LORA_ENTRY, "tags": [f"tag{i}" for i in range(95)]}
    compact = _compact_lora_entry(many)

    assert len(compact["tags"]) == MAX_COMPACT_TAGS
    assert compact["tags"][0] == "tag0"
    assert compact["tags"][-1] == f"tag{MAX_COMPACT_TAGS - 1}"


def test_compact_lora_entry_bounds_trained_words_far_more_loosely():
    """Trained words are the trigger vocabulary: dropping one silently breaks
    reproducing the image, so they get a much looser cap than the tag array."""
    many = {**LEGACY_LORA_ENTRY, "trained_words": [f"w{i}" for i in range(150)]}
    compact = _compact_lora_entry(many)

    assert len(compact["trained_words"]) == MAX_COMPACT_TRAINED_WORDS
    assert len(compact["tags"]) == 3


def test_compact_lora_entry_dedupes_and_drops_junk_tags():
    assert _compact_lora_entry({**LEGACY_LORA_ENTRY, "tags": ["a", " a ", "", None, 7]})["tags"] == ["a"]


def test_compact_lora_entry_omits_absent_keys_rather_than_nulling_them():
    compact = _compact_lora_entry({"name": "a.safetensors", "strength": 1.0})
    assert set(compact) == {"name", "strength", "weight"}


def test_compact_lora_entry_still_handles_the_bare_string_shape():
    assert _compact_lora_entry("a.safetensors") == {"name": "a.safetensors", "strength": 1.0}


def test_compact_checkpoint_metadata_keeps_the_ids():
    compact = _compact_checkpoint_metadata({
        "name": "nova_xl.safetensors",
        "display_name": "Nova XL",
        "filename": "nova_xl.safetensors",
        "type": "Checkpoint",
        "size": 123,
        "id": "cf-1",
        "model_id": 7,
        "civitai_id": 42,
        "base_model": "SDXL 1.0",
        "trained_words": ["nova"],
        "tags": ["sd15", "anime"],
    })

    assert compact["model_id"] == 7
    assert compact["civitai_id"] == 42
    assert compact["base_model"] == "SDXL 1.0"
    assert compact["trained_words"] == ["nova"]
    assert compact["tags"] == ["sd15", "anime"]
    assert compact["type"] == "Checkpoint"
    assert compact["size"] == 123


def test_compact_metadata_keeps_the_enriched_lora_ids_end_to_end():
    """The whole funnel, because a fix inside _compact_lora_entry is worthless
    if _compact_metadata drops the entry."""
    compact = _compact_metadata({
        "prompt": "a scene",
        "loras": [LEGACY_LORA_ENTRY],
        "checkpoint": {"name": "nova_xl.safetensors", "model_id": 7, "civitai_id": 42},
    })

    assert compact["loras"][0]["model_id"] == 21
    assert compact["loras"][0]["civitai_id"] == 1009342
    assert compact["loras"][0]["trained_words"] == ["boob tent"]
    assert compact["loras"][0]["tags"] == ["boob tent", "breasts", "clothing"]
    assert compact["checkpoint"]["model_id"] == 7
    assert compact["prompt"] == "a scene"
