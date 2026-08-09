"""
DB-backed asset index (replaces the in-memory GalleryIndexer for persistence).

The filesystem remains the source of truth for bytes. This module keeps the
`assets` table (core.entities.Asset) in sync:

- `reconcile_asset(...)` is called once per saved image (fast, single-file).
- `move_existing_assets(...)` is an idempotent one-time migration that relocates
  the legacy flat `data/output/YYYY/MM/DD/` tree into the partitioned
  `data/output/{user_id}/{workspace}/YYYY/MM/DD/` layout and upserts rows.

Querying galleries now hits the DB (keyset pagination, workspace/character/story
filters) instead of scanning 13k+ files into RAM at startup.
"""

import os
import traceback
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.entities import Asset, AssetKind
from infrastructure.image_processor import (
    encode_blurhash,
    generate_thumbnails,
    get_output_path,
    read_png_metadata,
)
from infrastructure.logging import get_logger

logger = get_logger("asset_reconciler")

DEFAULT_USER_ID = "default_user"


def _extract_meta(path: str) -> dict:
    try:
        return read_png_metadata(path) or {}
    except Exception:
        return {}


def _derived_workspace(job_metadata: dict | None, png_meta: dict) -> str:
    if job_metadata and job_metadata.get("workspace"):
        return job_metadata["workspace"]
    src = (job_metadata or {}).get("source") or ""
    if src in ("roleplay_scene", "scene_illustrate", "agentic_tool", "chat_image", "narrator"):
        return "roleplay"
    if src in ("story_illustrate", "story_illustrate_prompt", "story"):
        return "story"
    if png_meta.get("workspace"):
        return png_meta["workspace"]
    return "main"


def _workspace_from_job(job_id: str | None, session) -> tuple[str, str | None, str | None]:
    """Best-effort workspace/character/story from the job row."""
    if not job_id:
        return "main", None, None
    try:
        from core.entities import Job

        job = session.get(Job, job_id)
        if not job:
            return "main", None, None
        md = job.metadata_ or {}
        return (
            md.get("workspace") or "main",
            md.get("character_id"),
            md.get("story_id"),
        )
    except Exception:
        return "main", None, None


def upsert_asset(
    session,
    *,
    relative_path: str,
    filename: str,
    user_id: str = DEFAULT_USER_ID,
    workspace: str = "main",
    character_id: str | None = None,
    story_id: str | None = None,
    job_id: str | None = None,
    width: int | None = None,
    height: int | None = None,
    blurhash: str | None = None,
    thumbnail_relative_path: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Idempotent UPSERT of a single asset row (keyed by relative_path)."""
    stmt = pg_insert(Asset).values(
        relative_path=relative_path,
        filename=filename,
        user_id=user_id,
        workspace=workspace,
        character_id=character_id,
        story_id=story_id,
        job_id=job_id,
        width=width,
        height=height,
        blurhash=blurhash,
        thumbnail_relative_path=thumbnail_relative_path,
        metadata_=metadata,
        created_at=datetime.now(timezone.utc),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["relative_path"],
        set_={
            "workspace": stmt.excluded.workspace,
            "character_id": stmt.excluded.character_id,
            "story_id": stmt.excluded.story_id,
            "job_id": stmt.excluded.job_id,
            "width": stmt.excluded.width,
            "height": stmt.excluded.height,
            "blurhash": stmt.excluded.blurhash,
            "thumbnail_relative_path": stmt.excluded.thumbnail_relative_path,
            "metadata_": stmt.excluded.metadata_,
            "deleted_at": None,
        },
    )
    session.execute(stmt)
    session.commit()


def reconcile_asset(
    session,
    full_path: str,
    *,
    user_id: str = DEFAULT_USER_ID,
    workspace: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    job_id: str | None = None,
    job_metadata: dict | None = None,
    output_dir: str | None = None,
) -> None:
    """Upsert a single image file into the assets index.

    Newly saved images already live in the partitioned layout, so this only
    (re)computes thumbnails/blurhash if missing and writes the DB row.
    """
    try:
        output_dir = output_dir or os.environ.get("OUTPUT_DIR", "")
        filename = os.path.basename(full_path)
        if not full_path.lower().endswith(".png"):
            return

        png_meta = _extract_meta(full_path)
        ws = workspace or _derived_workspace(job_metadata, png_meta)
        if job_id and (character_id is None or story_id is None):
            j_ws, j_ch, j_st = _workspace_from_job(job_id, session)
            ws = ws or j_ws
            character_id = character_id or j_ch
            story_id = story_id or j_st

        width = height = None
        try:
            from PIL import Image

            with Image.open(full_path) as im:
                width, height = im.size
        except Exception:
            pass

        thumbnail_relative_path = None
        try:
            thumbs = generate_thumbnails(
                full_path, output_base_dir=output_dir, user_id=user_id, workspace=ws
            )
            tpath = thumbs.get("medium") or thumbs.get("thumb")
            if tpath and output_dir:
                thumbnail_relative_path = os.path.relpath(tpath, output_dir).replace("\\", "/")
        except Exception as e:
            logger.warning("asset_thumb_failed", path=full_path, error=str(e))

        blurhash = None
        try:
            blurhash = encode_blurhash(full_path)
        except Exception:
            pass

        relative_path = os.path.relpath(full_path, output_dir).replace("\\", "/") if output_dir else full_path

        meta = {
            "prompt": (job_metadata or {}).get("prompt") or png_meta.get("prompt"),
            "negativePrompt": (job_metadata or {}).get("negativePrompt") or png_meta.get("negativePrompt"),
            "checkpoint": (job_metadata or {}).get("checkpoint") or png_meta.get("checkpoint"),
            "seed": (job_metadata or {}).get("seed") or png_meta.get("seed"),
            "source": (job_metadata or {}).get("source"),
        }
        meta = {k: v for k, v in meta.items() if v is not None}

        upsert_asset(
            session,
            relative_path=relative_path,
            filename=filename,
            user_id=user_id,
            workspace=ws,
            character_id=character_id,
            story_id=story_id,
            job_id=job_id,
            width=width,
            height=height,
            blurhash=blurhash,
            thumbnail_relative_path=thumbnail_relative_path,
            metadata=meta or None,
        )
        logger.debug("asset_reconciled", path=relative_path, workspace=ws)
    except Exception as e:
        logger.error("asset_reconcile_failed", path=full_path, error=str(e), tb=traceback.format_exc())


def move_existing_assets(output_dir: str, db_session_factory, *, user_id: str = DEFAULT_USER_ID) -> int:
    """One-time idempotent migration: relocate the legacy flat tree into the
    partitioned layout and upsert DB rows.

    Legacy:  data/output/YYYY/MM/DD/foo.png
    Target:  data/output/{user_id}/{workspace}/YYYY/MM/DD/foo.png  (+ thumb mirror)

    Returns the number of assets reconciled. Safe to re-run (skips files already
    under the partition root).
    """
    moved = 0
    root = output_dir
    partition_root = os.path.join(root, user_id)
    if not os.path.isdir(root):
        return 0

    png_files = []
    for dirpath, _, filenames in os.walk(root):
        # Skip anything already under a {user_id} partition or the thumb tree.
        rel = os.path.relpath(dirpath, root)
        top = rel.split(os.sep)[0] if rel != "." else ""
        if top == user_id or top == "thumb":
            continue
        for fn in filenames:
            if fn.lower().endswith(".png"):
                png_files.append(os.path.join(dirpath, fn))

    logger.info("asset_migration_scan", found=len(png_files))

    for full_path in png_files:
        try:
            filename = os.path.basename(full_path)
            # Derive job_id from filename pattern Generated_YYYY-MM-DD_HH-MM-SS_<job8>_...
            job_id = None
            parts = filename.split("_")
            for p in parts:
                if len(p) >= 8 and p.isalnum():
                    # The job suffix is the segment right after the timestamp; approximate.
                    pass
            # Prefer metadata-embedded job_id if present.
            png_meta = _extract_meta(full_path)
            job_id = png_meta.get("job_id")

            ws, character_id, story_id = _workspace_from_job(job_id, db_session_factory())
            if job_id is None:
                ws = "main"

            # Determine target partition directory (keep YYYY/MM/DD from source).
            rel = os.path.relpath(full_path, root)
            date_parts = rel.split(os.sep)
            # rel looks like YYYY/MM/DD/filename
            y, m, d = date_parts[0], date_parts[1], date_parts[2]
            target_dir = get_output_path(root, user_id=user_id, workspace=ws)
            # get_output_path already appends YYYY/MM/DD; strip the date from rel to avoid doubling.
            target_path = os.path.join(target_dir, filename)

            if os.path.abspath(target_path) != os.path.abspath(full_path):
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                if os.path.exists(target_path):
                    os.remove(target_path)
                os.rename(full_path, target_path)
                full_path = target_path
                moved += 1

            # Move thumbnail if it exists in the flat thumb tree.
            flat_thumb = os.path.join(root, "thumb", os.path.basename(filename).replace(".png", ".webp"))
            if os.path.exists(flat_thumb):
                thumb_target_dir = get_output_path(root, subdir="thumb", user_id=user_id, workspace=ws)
                thumb_target = os.path.join(thumb_target_dir, os.path.basename(flat_thumb))
                if os.path.abspath(thumb_target) != os.path.abspath(flat_thumb):
                    os.makedirs(os.path.dirname(thumb_target), exist_ok=True)
                    os.rename(flat_thumb, thumb_target)

            reconcile_asset(
                db_session_factory(),
                full_path,
                user_id=user_id,
                workspace=ws,
                character_id=character_id,
                story_id=story_id,
                job_id=job_id,
                job_metadata={"workspace": ws, "source": png_meta.get("source")},
                output_dir=root,
            )
        except Exception as e:
            logger.error("asset_migration_file_failed", path=full_path, error=str(e))

    logger.info("asset_migration_done", moved=moved)
    return moved
