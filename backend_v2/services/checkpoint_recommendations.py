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
from core.entities import (
    Asset,
    AssetKind,
    AssetLora,
    ModelFile,
    ModelV2,
    ModelVersion,
    is_unet_only_model,
)
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
    """Compute project checkpoint and LoRA usage recommendations for tiered caching.

    Returns:
    - top_checkpoint_7d: #1 most used checkpoint in the last 7 days (or all-time fallback)
    - recent_checkpoints_30d: List of recent checkpoints used in the last 30 days
    - all_non_flux_checkpoints: All enabled non-Flux library checkpoints with download metadata
    - top_loras_30d: Most frequently used LoRAs in the last 30 days (or all-time fallback)
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
    seen_recent: set[str] = set()
    for row in rows_30d:
        if not row[0]:
            continue
        c_name = str(row[0])
        c_cnt = int(row[1])
        base = os.path.basename(c_name)
        if base in seen_recent:
            continue
        seen_recent.add(base)
        meta = _resolve_checkpoint_metadata(session, c_name)
        meta["count"] = c_cnt
        recent_ckpts.append(meta)

    # 3. All enabled non-Flux library checkpoints for direct worker NVMe pre-warming
    all_non_flux: list[dict[str, Any]] = []
    seen_non_flux: set[str] = set()

    # 3a. Prioritize recent_ckpts that are non-Flux first
    for r in recent_ckpts:
        fn = r.get("filename") or ""
        if not fn or r.get("is_flux"):
            continue
        if fn not in seen_non_flux:
            seen_non_flux.add(fn)
            all_non_flux.append(r)

    # 3b. Query all enabled ModelV2 checkpoints / unets
    stmt_all_ckpts = (
        select(ModelFile, ModelVersion, ModelV2)
        .join(ModelVersion, ModelFile.version_id == ModelVersion.id)
        .join(ModelV2, ModelVersion.model_id == ModelV2.id)
        .where(ModelV2.directory.in_(("checkpoints", "unet")))
        .where(ModelVersion.is_enabled == True)  # noqa: E712
        .where(ModelFile.is_primary == True)  # noqa: E712
        .order_by(ModelV2.name.asc())
    )
    for file_ent, ver_ent, model_ent in session.exec(stmt_all_ckpts).all():
        base_model_str = ver_ent.base_model or ""
        storage_fn = os.path.basename(
            (file_ent.storage_filename or file_ent.original_filename or "").strip()
        )
        if not storage_fn:
            continue
        is_flux = (
            is_unet_only_model(base_model_str)
            or ("flux" in base_model_str.lower())
            or ("flux" in storage_fn.lower())
        )
        if is_flux:
            continue
        if storage_fn in seen_non_flux:
            continue
        seen_non_flux.add(storage_fn)

        dl_url = file_ent.download_url
        if not dl_url and ver_ent.civitai_version_id:
            dl_url = f"https://civitai.com/api/download/models/{ver_ent.civitai_version_id}"

        all_non_flux.append({
            "filename": storage_fn,
            "model_name": model_ent.name,
            "version_name": ver_ent.name,
            "civitai_version_id": ver_ent.civitai_version_id,
            "civitai_model_id": model_ent.civitai_model_id,
            "download_url": dl_url,
            "base_model": base_model_str,
            "is_flux": False,
            "size_kb": float(file_ent.size_kb or 0.0),
            "count": 0,
        })

    # 4. Top LoRAs over the last 30 days (or all-time fallback)
    stmt_loras_30d = (
        select(
            AssetLora.model_id,
            AssetLora.civitai_model_id,
            func.count().label("cnt"),
        )
        .join(Asset, AssetLora.asset_id == Asset.id)
        .where(Asset.kind == AssetKind.IMAGE)
        .where(RESOLVED_TS >= thirty_days_ago)
        .group_by(AssetLora.model_id, AssetLora.civitai_model_id)
        .order_by(func.count().desc())
        .limit(16)
    )
    rows_loras = session.exec(stmt_loras_30d).all()
    if not rows_loras:
        stmt_loras_fallback = (
            select(
                AssetLora.model_id,
                AssetLora.civitai_model_id,
                func.count().label("cnt"),
            )
            .join(Asset, AssetLora.asset_id == Asset.id)
            .where(Asset.kind == AssetKind.IMAGE)
            .group_by(AssetLora.model_id, AssetLora.civitai_model_id)
            .order_by(func.count().desc())
            .limit(16)
        )
        rows_loras = session.exec(stmt_loras_fallback).all()

    top_loras: list[dict[str, Any]] = []
    seen_lora_files: set[str] = set()
    for m_id, civ_id, cnt in rows_loras:
        # Try resolving to ModelV2 / ModelVersion / ModelFile
        conds = []
        if m_id:
            conds.append(ModelV2.id == m_id)
        if civ_id:
            conds.append(ModelV2.civitai_model_id == civ_id)
        if not conds:
            continue
        stmt_lora_model = (
            select(ModelFile, ModelVersion, ModelV2)
            .join(ModelVersion, ModelFile.version_id == ModelVersion.id)
            .join(ModelV2, ModelVersion.model_id == ModelV2.id)
            .where(ModelV2.directory == "loras")
            .where(ModelVersion.is_enabled == True)  # noqa: E712
            .where(or_(*conds))
            .order_by(ModelFile.is_primary.desc(), ModelVersion.is_default.desc())
        )
        lora_row = session.exec(stmt_lora_model).first()
        if lora_row:
            l_file, l_ver, l_model = lora_row
            l_fn = os.path.basename(
                (l_file.storage_filename or l_file.original_filename or "").strip()
            )
            if l_fn and l_fn not in seen_lora_files:
                seen_lora_files.add(l_fn)
                dl_url = l_file.download_url
                if not dl_url and l_ver.civitai_version_id:
                    dl_url = f"https://civitai.com/api/download/models/{l_ver.civitai_version_id}"
                top_loras.append({
                    "filename": l_fn,
                    "model_name": l_model.name,
                    "version_name": l_ver.name,
                    "civitai_version_id": l_ver.civitai_version_id,
                    "civitai_model_id": l_model.civitai_model_id,
                    "download_url": dl_url,
                    "size_kb": float(l_file.size_kb or 0.0),
                    "count": int(cnt),
                })

    return {
        "top_checkpoint_7d": top_ckpt_meta,
        "recent_checkpoints_30d": recent_ckpts,
        "all_non_flux_checkpoints": all_non_flux,
        "top_loras_30d": top_loras,
    }
