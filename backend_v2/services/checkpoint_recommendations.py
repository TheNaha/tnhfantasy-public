"""Checkpoint recommendation engine for tiered storage and remote worker pre-warming.

Computes:
1. Tier 1 (Ultra-Hot): The #1 most frequently used checkpoint over the last 7 days (or all-time fallback),
   including CivitAI metadata (civitai_version_id, download_url, base_model, is_flux) for direct CDN downloads.
2. Tier 2 (Warm Cache): Distinct non-Flux checkpoints used over the last 30 days for asynchronous NVMe caching.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlmodel import Session, select

from core.asset_sql import CHECKPOINT_KEY, RESOLVED_TS
from core.entities import Asset, AssetKind, ModelFile, ModelV2, ModelVersion, is_unet_only_model
from infrastructure.logging import get_logger

logger = get_logger("checkpoint_recommendations")


def _resolve_checkpoint_metadata(session: Session, filename: str) -> dict[str, Any]:
    """Look up CivitAI and model metadata for a given checkpoint filename."""
    basename = os.path.basename(filename.strip())

    # 1. Try relational database match in ModelFile / ModelVersion / ModelV2
    stmt = (
        select(ModelFile, ModelVersion, ModelV2)
        .join(ModelVersion, ModelFile.version_id == ModelVersion.id)
        .join(ModelV2, ModelVersion.model_id == ModelV2.id)
        .where(
            or_(
                ModelFile.storage_filename == basename,
                ModelFile.original_filename == basename,
            )
        )
    )
    row = session.exec(stmt).first()
    if row:
        file_ent, ver_ent, model_ent = row
        base_model_str = ver_ent.base_model or ""
        is_flux = (
            is_unet_only_model(base_model_str)
            or ("flux" in base_model_str.lower())
            or ("flux" in (file_ent.storage_filename or "").lower())
        )
        dl_url = file_ent.download_url
        if not dl_url and ver_ent.civitai_version_id:
            dl_url = f"https://civitai.com/api/download/models/{ver_ent.civitai_version_id}"

        return {
            "filename": basename,
            "civitai_version_id": ver_ent.civitai_version_id,
            "civitai_model_id": model_ent.civitai_model_id,
            "download_url": dl_url,
            "base_model": base_model_str,
            "is_flux": is_flux,
            "size_kb": file_ent.size_kb,
        }

    # 2. Fallback: Extract version ID from standardized storage filename pattern
    # Format: {model}_{version}_{version_id}.{ext} -> e.g. _janku_trained_chenkin_noobai__v777_2786084.safetensors
    civitai_ver = None
    m = re.search(r"_(\d+)\.(?:safetensors|ckpt)$", basename)
    if m:
        try:
            civitai_ver = int(m.group(1))
        except (ValueError, TypeError) as exc:
            logger.debug("checkpoint_civitai_ver_parse_failed", filename=basename, error=str(exc))

    is_flux = "flux" in basename.lower()
    dl_url = f"https://civitai.com/api/download/models/{civitai_ver}" if civitai_ver else None

    return {
        "filename": basename,
        "civitai_version_id": civitai_ver,
        "civitai_model_id": None,
        "download_url": dl_url,
        "base_model": "Flux" if is_flux else None,
        "is_flux": is_flux,
        "size_kb": 0,
    }


def get_checkpoint_recommendations(session: Session) -> dict[str, Any]:
    """Compute project checkpoint usage recommendations for tiered caching.

    Returns:
    - top_checkpoint_7d: #1 most used checkpoint in the last 7 days (or all-time fallback)
    - recent_checkpoints_30d: List of recent checkpoints used in the last 30 days
    """
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    # 1. Top checkpoint in 7 days
    stmt_7d = (
        select(CHECKPOINT_KEY.label("checkpoint"), func.count().label("cnt"))
        .where(Asset.kind == AssetKind.IMAGE)
        .where(CHECKPOINT_KEY.is_not(None))
        .where(CHECKPOINT_KEY != "")
        .where(RESOLVED_TS >= seven_days_ago)
        .group_by(CHECKPOINT_KEY)
        .order_by(func.count().desc())
    )
    rows_7d = session.exec(stmt_7d).all()

    # Fallback to all-time if no image generations in the last 7 days
    if not rows_7d:
        stmt_fallback = (
            select(CHECKPOINT_KEY.label("checkpoint"), func.count().label("cnt"))
            .where(Asset.kind == AssetKind.IMAGE)
            .where(CHECKPOINT_KEY.is_not(None))
            .where(CHECKPOINT_KEY != "")
            .group_by(CHECKPOINT_KEY)
            .order_by(func.count().desc())
        )
        rows_7d = session.exec(stmt_fallback).all()

    top_ckpt_meta: dict[str, Any] | None = None
    if rows_7d and rows_7d[0][0]:
        top_name = str(rows_7d[0][0])
        top_cnt = int(rows_7d[0][1])
        top_ckpt_meta = _resolve_checkpoint_metadata(session, top_name)
        top_ckpt_meta["count"] = top_cnt

    # 2. Recent checkpoints in 30 days
    stmt_30d = (
        select(CHECKPOINT_KEY.label("checkpoint"), func.count().label("cnt"))
        .where(Asset.kind == AssetKind.IMAGE)
        .where(CHECKPOINT_KEY.is_not(None))
        .where(CHECKPOINT_KEY != "")
        .where(RESOLVED_TS >= thirty_days_ago)
        .group_by(CHECKPOINT_KEY)
        .order_by(func.count().desc())
        .limit(25)
    )
    rows_30d = session.exec(stmt_30d).all()

    # Fallback to rows_7d if 30d query returned nothing
    if not rows_30d and rows_7d:
        rows_30d = rows_7d[:25]

    recent_ckpts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows_30d:
        if not row[0]:
            continue
        c_name = str(row[0])
        c_cnt = int(row[1])
        base = os.path.basename(c_name)
        if base in seen:
            continue
        seen.add(base)
        meta = _resolve_checkpoint_metadata(session, c_name)
        meta["count"] = c_cnt
        recent_ckpts.append(meta)

    return {
        "top_checkpoint_7d": top_ckpt_meta,
        "recent_checkpoints_30d": recent_ckpts,
    }
