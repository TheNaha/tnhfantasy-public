# Tests for services/asset_reconciler.py (DB-backed asset index)


from sqlmodel import select

from core.entities import Asset
from services.asset_reconciler import (
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
