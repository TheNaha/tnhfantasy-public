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

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.entities import Asset
from infrastructure.image_processor import (
    encode_blurhash,
    generate_thumbnails,
    get_output_path,
    read_image_metadata,
)
from infrastructure.logging import get_logger

logger = get_logger("asset_reconciler")

DEFAULT_USER_ID = "default_user"

# Schema version stamped onto every asset row's `metadata_` by
# `_compact_metadata`. Bump when the compacted shape changes incompatibly.
METADATA_VERSION = "2.0"

# Upper bound on the CivitAI tag list copied onto each per-asset LoRA/checkpoint
# entry. A popular character LoRA carries 30-80 tags and this array is written
# into every single asset's JSONB column, so an unbounded copy would multiply
# megabytes across the table for metadata the gallery UI never reads. 20 is the
# observed useful width — CivitAI orders tags by weight, so the truncation keeps
# the most significant ones — and it still keeps "find images that used a LoRA
# tagged X" answerable for the overwhelming majority of real tags. The full
# array stays on `model_tags`; this is a per-asset convenience copy only.
MAX_COMPACT_TAGS = 20

# A much looser bound on `trained_words`, which is the LoRA's *trigger
# vocabulary* rather than taxonomy: dropping a trigger word silently breaks
# reproducing an image from its metadata, so the cap here is only a guard
# against a pathological list, and no real LoRA comes near it.
MAX_COMPACT_TRAINED_WORDS = 100

# Scalar fields kept on every compacted model reference, so an asset row can be
# joined back to `models_v2` by id instead of by a filename string. `type` and
# `size` are checkpoint-only, matching the two original key lists.
_CHECKPOINT_KEYS = (
    "name",
    "display_name",
    "filename",
    "type",
    "size",
    "id",
    "model_id",
    "civitai_id",
    "base_model",
)
_LORA_KEYS = (
    "name",
    "display_name",
    "filename",
    "strength",
    "weight",
    "id",
    "model_id",
    "civitai_id",
    "base_model",
)


def _copy_bounded_strings(value: Any, limit: int) -> list[str] | None:
    """Copy up to `limit` cleaned, de-duplicated strings, or None if there are none."""
    if not isinstance(value, (list, tuple)):
        return None
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned or cleaned in strings:
            continue
        strings.append(cleaned)
        if len(strings) >= limit:
            break
    return strings or None


def _copy_identity_fields(value: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in keys:
        if key in value:
            compact[key] = value.get(key)
    return compact


def _compact_checkpoint_metadata(value: Any) -> Any:
    """Reduce checkpoint metadata to UI/statistics-relevant fields plus identity.

    `model_id` / `civitai_id` are what make an image joinable to a model row.
    Without them the only surviving link was the checkpoint filename string,
    so "which images used this checkpoint" was not answerable by id.
    """
    if not isinstance(value, dict):
        return value

    compact = _copy_identity_fields(value, _CHECKPOINT_KEYS)

    # trained_words is the trigger vocabulary; tags is the CivitAI taxonomy
    # (bounded). Both are what a "find me the LoRA for this character" search
    # needs, and both were being dropped.
    trained_words = _copy_bounded_strings(value.get("trained_words"), MAX_COMPACT_TRAINED_WORDS)
    if trained_words:
        compact["trained_words"] = trained_words
    tags = _copy_bounded_strings(value.get("tags"), MAX_COMPACT_TAGS)
    if tags:
        compact["tags"] = tags

    if not compact:
        fallback_name = value.get("name") or value.get("filename") or value.get("display_name")
        if fallback_name:
            compact["name"] = fallback_name
    return compact


def _compact_lora_entry(value: Any) -> Any:
    """Reduce a LoRA entry to display/reuse parameters, identity, and search keys.

    `model_id` / `civitai_id` are what make an image joinable to a model row.
    A real legacy sidecar carries `model_id: 21`, `civitai_id: 1009342`,
    `base_model: "Illustrious"`, `trained_words: ["boob tent"]` and
    `tags: ["boob tent", "breasts", "clothing"]`, and the previous version
    kept only the display strings — so an image's link to its LoRA survived as
    a filename that could not be resolved to a model id, and "show me images
    that used this LoRA" was not answerable.
    """
    if isinstance(value, str):
        return {"name": value, "strength": 1.0}
    if not isinstance(value, dict):
        return value

    compact = _copy_identity_fields(value, _LORA_KEYS)

    trained_words = _copy_bounded_strings(value.get("trained_words"), MAX_COMPACT_TRAINED_WORDS)
    if trained_words:
        compact["trained_words"] = trained_words
    tags = _copy_bounded_strings(value.get("tags"), MAX_COMPACT_TAGS)
    if tags:
        compact["tags"] = tags

    if "strength" not in compact and "weight" in compact:
        compact["strength"] = compact.get("weight")
    if "weight" not in compact and "strength" in compact:
        compact["weight"] = compact.get("strength")

    if not compact:
        fallback_name = value.get("name") or value.get("filename")
        if fallback_name:
            compact["name"] = fallback_name
    return compact


def _compact_metadata(metadata: Any) -> dict[str, Any]:
    """
    Keep scalar metadata and compact known heavy nested structures.

    Mirrors the legacy GalleryIndexer._compact_metadata so statistics and
    gallery UI keep consuming the same metadata shape from the DB-backed index.

    `metadata_version` is stamped here rather than at the call site because this
    is the single funnel every asset row passes through. Nothing else in the
    codebase wrote it, so the statistics endpoints reported every real asset as
    "legacy" (15867 of 16058 on this deployment) and the enriched/legacy split
    could never be anything but all-legacy.
    """
    if not isinstance(metadata, dict):
        return {}

    compact: dict[str, Any] = {"metadata_version": METADATA_VERSION}
    passthrough_dict_keys = {"job", "dimensions", "thumbnails"}
    passthrough_list_keys = {"embeddings", "tags"}

    for key, value in metadata.items():
        if key == "checkpoint":
            compact[key] = _compact_checkpoint_metadata(value)
            continue

        if key == "loras":
            if isinstance(value, list):
                compact[key] = [_compact_lora_entry(item) for item in value]
            continue

        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
            continue

        if isinstance(value, dict) and key in passthrough_dict_keys:
            compact[key] = value
            continue

        if isinstance(value, list) and key in passthrough_list_keys:
            compact[key] = value
            continue

    return compact


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, (float, str)):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _checkpoint_name(value: Any) -> str | None:
    """Checkpoint name from either the object or the legacy bare-string form."""
    if isinstance(value, dict):
        name = value.get("name") or value.get("filename")
        return str(name) if name else None
    if isinstance(value, str) and value:
        return value
    return None


def derive_stat_columns(metadata: dict | None) -> dict[str, Any]:
    """The `Asset` rollup columns implied by a `metadata_` document.

    This is the single place that derives them. `upsert_asset` is the only
    supported way to write an `Asset` row, so a column can never disagree with
    the document it summarises.

    Nothing here raises: a metadata value of an unexpected shape leaves its
    column NULL rather than failing the write of an otherwise-valid asset.
    """
    metadata = metadata if isinstance(metadata, dict) else {}
    job = metadata.get("job")
    duration = job.get("duration_seconds") if isinstance(job, dict) else None
    duration_seconds = _coerce_float(duration)
    if duration_seconds is not None and duration_seconds <= 0:
        duration_seconds = None

    return {
        "duration_seconds": duration_seconds,
        "job_completed_at": _resolve_job_completed_at(metadata),
        "checkpoint_name": _checkpoint_name(metadata.get("checkpoint")),
        "sampler": _as_optional_str(metadata.get("sampler")),
        "scheduler": _as_optional_str(metadata.get("scheduler")),
        "vae": _as_optional_str(metadata.get("vae")),
        "steps": _coerce_int(metadata.get("steps")),
        "cfg": _coerce_float(metadata.get("cfg")),
        "seed": _coerce_int(metadata.get("seed")),
        "metadata_version": _as_optional_str(metadata.get("metadata_version")),
    }


def _resolve_job_completed_at(metadata: dict[str, Any]) -> datetime | None:
    """The job's recorded completion time, as an aware datetime.

    Only the job's own value: the generated_at / created_at fallback is applied by
    the reader (`coalesce`) rather than stored, so a row re-upserted with new
    metadata still falls back correctly. Mirrors the resolution order the
    statistics service used, including the legacy epoch-float form.
    """
    job = metadata.get("job")
    if not isinstance(job, dict):
        return None
    value = job.get("completed_at")
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_optional_str(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = value if isinstance(value, str) else str(value)
    return text or None


def _parse_generated_at(png_meta: dict, full_path: str) -> datetime | None:
    """Best-effort true image creation time: PNG meta anchor, else file mtime."""
    for key in ("job_created_at", "job_timeline_anchor"):
        raw = png_meta.get(key)
        if not raw:
            continue
        try:
            s = str(raw)
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            continue
    job = png_meta.get("job")
    if isinstance(job, dict):
        completed = job.get("completed_at")
        if isinstance(completed, (int, float)) and completed > 0:
            try:
                return datetime.fromtimestamp(completed, tz=timezone.utc)
            except (ValueError, OSError, OverflowError) as exc:
                logger.debug("png_completed_at_parse_failed", error=str(exc))
    try:
        mtime = os.path.getmtime(full_path)
        if mtime > 0:
            return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except OSError as exc:
        logger.debug("mtime_read_failed", path=full_path, error=str(exc))
    return None


def _extract_meta(path: str) -> dict:
    """Read image metadata (embedded PNG or sidecar JSON fallback)."""
    try:
        return read_image_metadata(path) or {}
    except Exception:
        return {}


def _derived_workspace(job_metadata: dict | None, png_meta: dict) -> str:
    if job_metadata and job_metadata.get("workspace"):
        return job_metadata["workspace"]
    src = (job_metadata or {}).get("source") or ""
    if src in ("roleplay_scene", "scene_illustrate", "agentic_tool", "chat_image", "narrator"):
        return "chat"
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
    generated_at: datetime | None = None,
    metadata: dict | None = None,
) -> None:
    """Idempotent UPSERT of a single asset row (keyed by relative_path).

    The only supported way to write an `Asset`. The statistics rollup columns
    are derived here from `metadata` rather than accepted as arguments, so they
    cannot be set inconsistently by a caller.
    """
    dialect_name = session.get_bind().dialect.name
    dialect_insert = pg_insert if dialect_name == "postgresql" else sqlite_insert if dialect_name == "sqlite" else insert
    stat_columns = derive_stat_columns(metadata)
    stmt = dialect_insert(Asset).values(
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
        generated_at=generated_at,
        metadata_=metadata,
        created_at=datetime.now(timezone.utc),
        **stat_columns,
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
            "generated_at": stmt.excluded.generated_at,
            "metadata_": stmt.excluded.metadata_,
            "deleted_at": None,
            **{name: stmt.excluded[name] for name in stat_columns},
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

        generated_at = _parse_generated_at(png_meta, full_path)

        width = height = None
        try:
            from PIL import Image

            with Image.open(full_path) as im:
                width, height = im.size
        except Exception as exc:
            logger.debug("image_dimensions_read_failed", path=full_path, error=str(exc))

        thumbnail_relative_path = None
        try:
            # Reuse an existing thumbnail when one already sits at the expected
            # partitioned path (13k-file migrations re-run over the same tree).
            expected_thumb = None
            try:
                thumb_dir = get_output_path(output_dir, subdir="thumb", user_id=user_id, workspace=ws)
                expected_thumb = os.path.join(thumb_dir, f"{os.path.splitext(filename)[0]}.webp")
            except Exception as exc:
                logger.debug("thumb_path_build_failed", error=str(exc))
            if expected_thumb and os.path.exists(expected_thumb):
                thumbs = {"medium": expected_thumb}
            else:
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
        except Exception as exc:
            logger.debug("blurhash_failed", path=full_path, error=str(exc))

        relative_path = os.path.relpath(full_path, output_dir).replace("\\", "/") if output_dir else full_path

        # Full compacted metadata: embedded PNG metadata (job anchor, duration,
        # sampler/scheduler/steps/cfg/checkpoint/loras...) layered with
        # job-level overrides so statistics and gallery grouping keep working.
        meta = _compact_metadata(dict(png_meta))
        for key in ("prompt", "negativePrompt", "checkpoint", "seed", "source", "workspace"):
            v = (job_metadata or {}).get(key)
            if v is not None:
                meta[key] = v
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
            generated_at=generated_at,
            metadata=meta or None,
        )
        logger.debug("asset_reconciled", path=relative_path, workspace=ws)
    except Exception as e:
        logger.error("asset_reconcile_failed", path=full_path, error=str(e), tb=traceback.format_exc())


def move_existing_assets(output_dir: str, db_session_factory, *, user_id: str = DEFAULT_USER_ID) -> int:
    """Idempotent indexer: reconcile every PNG under OUTPUT_DIR into the assets
    table, relocating legacy flat files into the partitioned layout.

    Legacy:  data/output/YYYY/MM/DD/foo.png  or data/output/foo.png
    Target:  data/output/{user_id}/{workspace}/YYYY/MM/DD/foo.png  (+ thumb mirror)

    Files already under {user_id}/... are reconciled in place (no rename), so
    re-running after a partial migration re-indexes everything without touching
    the existing partition. Returns the number of assets reconciled.
    """
    reconciled = 0
    root = output_dir
    if not os.path.isdir(root):
        return 0

    # Fast-path: if the partitioned layout already exists and contains PNGs,
    # skip the expensive os.walk on every startup. Set
    # COMFY_ASSET_MIGRATION_FORCE=1 to force a full re-scan.
    if os.environ.get("COMFY_ASSET_MIGRATION_FORCE") != "1":
        user_partition = os.path.join(root, user_id)
        if os.path.isdir(user_partition):
            existing_pngs = 0
            for _dirpath, _dirnames, filenames in os.walk(user_partition):
                existing_pngs += sum(1 for fn in filenames if fn.lower().endswith(".png"))
                if existing_pngs > 0:
                    break
            if existing_pngs > 0:
                logger.info("asset_migration_skip_existing_partition", user_id=user_id)
                return 0

    # Collect PNGs without descending into the thumb tree.
    png_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        top = rel.split(os.sep)[0] if rel != "." else ""
        if top == "thumb":
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.lower().endswith(".png"):
                png_files.append(os.path.join(dirpath, fn))

    logger.info("asset_migration_scan", found=len(png_files))

    # One shared session for the whole walk (the old per-file sessions were
    # never closed and leaked one connection per file).
    session = db_session_factory()
    try:
        for full_path in png_files:
            try:
                filename = os.path.basename(full_path)
                rel_path = os.path.relpath(full_path, root).replace("\\", "/")

                # Already indexed? Skip — keeps re-runs (every startup) cheap.
                if session.execute(
                    select(Asset.id).where(
                        Asset.relative_path == rel_path,
                        Asset.deleted_at.is_(None),
                    )
                ).first():
                    continue

                png_meta = _extract_meta(full_path)
                job_id = png_meta.get("job_id")

                ws, character_id, story_id = _workspace_from_job(job_id, session)
                if job_id is None:
                    ws = "main"

                rel = os.path.relpath(full_path, root)
                parts = rel.split(os.sep)
                # rel is either {user_id}/{workspace}/{y}/{m}/{d}/{file}
                # (already partitioned) or a legacy YYYY/MM/DD/{file} / flat {file}.
                if len(parts) >= 6 and parts[0] == user_id:
                    # Already partitioned: the path is authoritative — keep it.
                    ws = parts[1] or ws
                    y, m, d = parts[2], parts[3], parts[4]
                else:
                    if len(parts) < 4:
                        # No date hierarchy (flat legacy config): file sits at root.
                        # UTC for the same reason as the partition writer in
                        # `infrastructure/image_processor.py`: `created_at` and
                        # the gallery's date buckets are UTC, so a local date here
                        # back-files a flat legacy image under a day it was never
                        # generated on.
                        today = datetime.now(timezone.utc)
                        y = today.year
                        m = today.month
                        d = today.day
                    else:
                        y, m, d = parts[0], parts[1], parts[2]
                    try:
                        if not (2000 <= int(y) <= 2100 and 1 <= int(m) <= 12 and 1 <= int(d) <= 31):
                            raise ValueError
                    except ValueError:
                        today = datetime.now(timezone.utc)
                        y = today.year
                        m = today.month
                        d = today.day
                    # Preserve the original YYYY/MM/DD from the source path
                    # (get_output_path always appends *today's* date, which
                    # would scramble the timeline).
                    target_dir = os.path.join(root, user_id, ws, str(y), str(m), str(d))
                    target_path = os.path.join(target_dir, filename)
                    if os.path.abspath(target_path) != os.path.abspath(full_path):
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        if os.path.exists(target_path):
                            os.remove(target_path)
                        os.rename(full_path, target_path)
                        full_path = target_path

                # Move thumbnail if it exists in the legacy flat thumb tree
                # (root/thumb/YYYY/MM/DD/<file>.webp) into the partition mirror.
                flat_thumb = os.path.join(root, "thumb", f"{y}", f"{m}", f"{d}", os.path.basename(filename).replace(".png", ".webp"))
                if os.path.exists(flat_thumb):
                    thumb_target_dir = os.path.join(root, user_id, ws, "thumb", str(y), str(m), str(d))
                    thumb_target = os.path.join(thumb_target_dir, os.path.basename(flat_thumb))
                    if os.path.abspath(thumb_target) != os.path.abspath(flat_thumb):
                        os.makedirs(os.path.dirname(thumb_target), exist_ok=True)
                        os.rename(flat_thumb, thumb_target)

                reconcile_asset(
                    session,
                    full_path,
                    user_id=user_id,
                    workspace=ws,
                    character_id=character_id,
                    story_id=story_id,
                    job_id=job_id,
                    job_metadata={"workspace": ws, "source": png_meta.get("source")},
                    output_dir=root,
                )
                reconciled += 1
            except Exception as e:
                logger.error("asset_migration_file_failed", path=full_path, error=str(e))
    finally:
        session.close()

    logger.info("asset_migration_done", reconciled=reconciled)
    return reconciled


def _asset_as_file_data(asset: Asset, output_dir: str) -> dict[str, Any]:
    """Shape a DB Asset row like the legacy GalleryIndexer file dict."""
    name = os.path.basename(asset.relative_path).replace("\\", "/")
    full_path = os.path.join(output_dir, asset.relative_path)
    size = 0
    mtime = 0.0
    try:
        size = os.path.getsize(full_path)
        mtime = os.path.getmtime(full_path)
    except OSError as exc:
        logger.debug("asset_stat_failed", path=full_path, error=str(exc))
    order_ts = asset.generated_at or asset.created_at
    ts = order_ts.timestamp() if order_ts else mtime
    rel = asset.relative_path.replace("\\", "/")
    metadata = dict(asset.metadata_ or {})
    metadata.setdefault("workspace", asset.workspace)
    if asset.character_id:
        metadata.setdefault("character_id", asset.character_id)
    if asset.story_id:
        metadata.setdefault("story_id", asset.story_id)
    file_data = {
        "name": name,
        "relative_path": rel,
        "full_path": rel,
        "size": size,
        "date": ts,
        "mtime": mtime,
        "modified_time": ts,
        "type": "image",
        "preview": f"/api/view/output/{rel}",
        "thumbnail": f"/api/thumbnail/medium/{rel}",
        "thumbnail_medium": f"/api/thumbnail/medium/{rel}",
        "metadata": metadata,
        "workspace": asset.workspace,
        "character_id": asset.character_id,
        "story_id": asset.story_id,
    }
    if asset.blurhash:
        file_data["blurhash"] = asset.blurhash
    return file_data
