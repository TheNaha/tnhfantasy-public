import os
import time
import random
import asyncio
import httpx
from typing import Dict, Any, List, Optional, Tuple

from infrastructure.logging import get_logger
from infrastructure.http_client import get_http_client
from infrastructure.config_helpers import resolve_env_bool, resolve_env_int, resolve_env_float
from infrastructure.request_dedup import deduplicated, make_key
from infrastructure.database import get_session_sync

logger = get_logger("model_preview_service")

def _resolve_preview_cache_dir() -> str:
    configured_dir = os.getenv("COMFY_PREVIEW_CACHE_DIR")
    if configured_dir:
        return configured_dir

    output_dir = os.getenv("OUTPUT_DIR")
    if output_dir:
        return os.path.join(output_dir, "cache", "previews")

    return os.path.join(os.path.dirname(__file__), "../../cache/previews")


PREVIEW_CACHE_DIR = _resolve_preview_cache_dir()
PREVIEW_METADATA_TIMEOUT_SECONDS = resolve_env_float("COMFY_PREVIEW_METADATA_TIMEOUT_SECONDS", 10.0, 0.1)
PREVIEW_IMAGE_TIMEOUT_SECONDS = resolve_env_float("COMFY_PREVIEW_IMAGE_TIMEOUT_SECONDS", 30.0, 0.1)
PREVIEW_FAILURE_TTL_SECONDS = resolve_env_int("COMFY_PREVIEW_FAILURE_TTL_SECONDS", 600, 0)
PREVIEW_NOT_FOUND_TTL_SECONDS = resolve_env_int("COMFY_PREVIEW_NOT_FOUND_TTL_SECONDS", 21600, 0)
PREVIEW_PREFETCH_ENABLED = resolve_env_bool("COMFY_PREVIEW_PREFETCH_ENABLED", False)
PREVIEW_PREFETCH_INTERVAL_SECONDS = resolve_env_int("COMFY_PREVIEW_PREFETCH_INTERVAL_SECONDS", 300, 1)
PREVIEW_PREFETCH_BATCH_SIZE = resolve_env_int("COMFY_PREVIEW_PREFETCH_BATCH_SIZE", 10, 1)
PREVIEW_PREFETCH_MAX_CANDIDATES = resolve_env_int("COMFY_PREVIEW_PREFETCH_MAX_CANDIDATES", 50, 1)
PREVIEW_PREFETCH_STALE_AFTER_SECONDS = resolve_env_int("COMFY_PREVIEW_PREFETCH_STALE_AFTER_SECONDS", 86400, 0)
PREVIEW_PREFETCH_JITTER_SECONDS = resolve_env_float("COMFY_PREVIEW_PREFETCH_JITTER_SECONDS", 60.0, 0.0)
PREVIEW_PREFETCH_ITEM_DELAY_SECONDS = resolve_env_float("COMFY_PREVIEW_PREFETCH_ITEM_DELAY_SECONDS", 2.0, 0.0)


def get_cache_path(model_id: int, version_id: int = None, image_index: int = 0) -> str:
    """Get cache path for a model preview image."""
    os.makedirs(PREVIEW_CACHE_DIR, exist_ok=True)
    if version_id is not None:
        return os.path.join(PREVIEW_CACHE_DIR, f"{model_id}_{version_id}_{image_index}.img")
    return os.path.join(PREVIEW_CACHE_DIR, f"{model_id}_{image_index}.img")


def _get_cache_meta_path(cache_path: str) -> str:
    return f"{cache_path}.meta"


def _get_failure_marker_path(cache_path: str) -> str:
    return f"{cache_path}.fail"


def _get_not_found_marker_path(cache_path: str) -> str:
    return f"{cache_path}.404"


def _has_recent_failure(failure_marker_path: str, ttl_seconds: int) -> bool:
    if ttl_seconds <= 0 or not os.path.exists(failure_marker_path):
        return False
    try:
        with open(failure_marker_path, 'r', encoding='utf-8') as marker_file:
            failed_at = float(marker_file.read().strip())
    except Exception:
        return False
    return (time.time() - failed_at) < ttl_seconds


def _mark_failure(failure_marker_path: str) -> None:
    with open(failure_marker_path, 'w', encoding='utf-8') as marker_file:
        marker_file.write(str(time.time()))


def _clear_failure_marker(failure_marker_path: str) -> None:
    if os.path.exists(failure_marker_path):
        os.remove(failure_marker_path)


def _load_preview_from_cache(cache_path: str, cache_meta_path: str) -> tuple:
    if not os.path.exists(cache_path):
        return None, None

    with open(cache_path, 'rb') as image_file:
        cached_content = image_file.read()

    cached_content_type = "image/jpeg"
    if os.path.exists(cache_meta_path):
        try:
            with open(cache_meta_path, 'r', encoding='utf-8') as meta_file:
                cached_content_type = meta_file.read().strip() or cached_content_type
        except Exception:
            pass

    return cached_content, cached_content_type


def _save_preview_to_cache(cache_path: str, cache_meta_path: str, image_data: bytes, content_type: str) -> None:
    with open(cache_path, 'wb') as image_file:
        image_file.write(image_data)
    with open(cache_meta_path, 'w', encoding='utf-8') as meta_file:
        meta_file.write(content_type)


def _select_preview_url(model_data: Dict[str, Any], version_id: Optional[int], image_index: int) -> Optional[str]:
    model_versions = model_data.get('modelVersions', [])
    if not model_versions:
        return None

    target_version = None
    if version_id is not None:
        target_version = next((v for v in model_versions if v.get('id') == version_id), None)
    if not target_version:
        target_version = model_versions[0]

    raw_images = target_version.get('images', [])
    image_candidates = [
        img for img in raw_images
        if isinstance(img, dict)
        and img.get('url')
        and img.get('type', 'image').lower() != 'video'
    ]

    if not image_candidates:
        image_candidates = [
            img for img in raw_images
            if isinstance(img, dict) and img.get('url')
        ]

    if not image_candidates:
        return None

    safe_image_index = min(max(image_index, 0), len(image_candidates) - 1)
    return image_candidates[safe_image_index].get('url')


def _is_preview_cache_stale(
    model_id: int,
    version_id: Optional[int],
    image_index: int,
    stale_after_seconds: int,
) -> bool:
    cache_path = get_cache_path(model_id, version_id, image_index)
    if not os.path.exists(cache_path):
        return True

    if stale_after_seconds <= 0:
        return True

    try:
        return (time.time() - os.path.getmtime(cache_path)) >= stale_after_seconds
    except OSError:
        return True


def _list_civitai_model_ids_for_prefetch() -> List[int]:
    from sqlmodel import select
    from core.entities_v2 import ModelV2

    session = get_session_sync()
    try:
        rows = session.exec(
            select(ModelV2.civitai_model_id).where(
                ModelV2.civitai_model_id.is_not(None),
                ModelV2.source == "civitai",
            )
        ).all()
        unique_ids = {
            model_id
            for model_id in rows
            if isinstance(model_id, int) and model_id > 0
        }
        return list(unique_ids)
    finally:
        session.close()


def _select_stale_prefetch_candidates(
    model_ids: List[int],
    max_candidates: int,
    batch_size: int,
    stale_after_seconds: int,
) -> List[int]:
    if not model_ids or batch_size <= 0:
        return []

    shuffled_ids = model_ids[:]
    random.shuffle(shuffled_ids)

    if max_candidates > 0 and len(shuffled_ids) > max_candidates:
        shuffled_ids = shuffled_ids[:max_candidates]

    stale_candidates: List[int] = []
    for model_id in shuffled_ids:
        if _is_preview_cache_stale(
            model_id,
            version_id=None,
            image_index=0,
            stale_after_seconds=stale_after_seconds,
        ):
            stale_candidates.append(model_id)
        if len(stale_candidates) >= batch_size:
            break

    return stale_candidates


async def fetch_civitai_preview(
    model_id: int,
    version_id: int = None,
    image_index: int = 0,
    force_refresh: bool = False,
) -> Tuple[Optional[bytes], Optional[str], bool]:
    """Fetch preview image from CivitAI API and cache it using non-blocking I/O.
    Returns (image_data, content_type, is_cache_hit).
    """
    cache_path = get_cache_path(model_id, version_id, image_index)
    cache_meta_path = _get_cache_meta_path(cache_path)
    failure_marker_path = _get_failure_marker_path(cache_path)
    not_found_marker_path = _get_not_found_marker_path(cache_path)

    has_recent_not_found = await asyncio.to_thread(
        _has_recent_failure,
        not_found_marker_path,
        PREVIEW_NOT_FOUND_TTL_SECONDS,
    )
    if has_recent_not_found:
        logger.debug(
            "civitai_preview_recent_not_found_skip",
            model_id=model_id,
            version_id=version_id,
            image_index=image_index,
            ttl_seconds=PREVIEW_NOT_FOUND_TTL_SECONDS,
        )
        return None, None, False

    has_recent_failure = await asyncio.to_thread(
        _has_recent_failure,
        failure_marker_path,
        PREVIEW_FAILURE_TTL_SECONDS,
    )
    if has_recent_failure:
        logger.debug(
            "civitai_preview_recent_failure_skip",
            model_id=model_id,
            version_id=version_id,
            image_index=image_index,
            ttl_seconds=PREVIEW_FAILURE_TTL_SECONDS,
        )
        return None, None, False

    if not force_refresh:
        cached_content, cached_content_type = await asyncio.to_thread(
            _load_preview_from_cache,
            cache_path,
            cache_meta_path,
        )
        if cached_content is not None:
            return cached_content, cached_content_type, True

    try:
        from services.external_model_service import ExternalModelService, ExternalModelServiceError
        external_service = ExternalModelService()
        model_data = await external_service.get_civitai_model(model_id)

        image_url = _select_preview_url(model_data, version_id, image_index)
        if not image_url:
            return None, None, False

        client = get_http_client()
        img_response = await client.get(image_url, timeout=PREVIEW_IMAGE_TIMEOUT_SECONDS)
        img_response.raise_for_status()
        image_data = img_response.content
        content_type = img_response.headers.get('Content-Type', 'image/jpeg')

        await asyncio.to_thread(
            _save_preview_to_cache,
            cache_path,
            cache_meta_path,
            image_data,
            content_type,
        )
        await asyncio.to_thread(_clear_failure_marker, failure_marker_path)
        await asyncio.to_thread(_clear_failure_marker, not_found_marker_path)
        return image_data, content_type, False

    except ExternalModelServiceError as e:
        if e.status_code == 404:
            await asyncio.to_thread(_mark_failure, not_found_marker_path)
            await asyncio.to_thread(_clear_failure_marker, failure_marker_path)
            logger.info(
                "civitai_preview_model_not_found",
                model_id=model_id,
                version_id=version_id,
                image_index=image_index,
                error=str(e),
            )
            return None, None, False

        await asyncio.to_thread(_mark_failure, failure_marker_path)
        logger.warning(
            "civitai_preview_fetch_failed",
            model_id=model_id,
            version_id=version_id,
            image_index=image_index,
            error=str(e),
        )
        return None, None, False
    except httpx.HTTPStatusError as e:
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        if status_code == 404:
            await asyncio.to_thread(_mark_failure, not_found_marker_path)
            await asyncio.to_thread(_clear_failure_marker, failure_marker_path)
            logger.info(
                "civitai_preview_model_not_found",
                model_id=model_id,
                version_id=version_id,
                image_index=image_index,
                error=str(e),
            )
            return None, None, False

        await asyncio.to_thread(_mark_failure, failure_marker_path)
        logger.warning(
            "civitai_preview_fetch_failed",
            model_id=model_id,
            version_id=version_id,
            image_index=image_index,
            error=str(e),
        )
        return None, None, False
    except Exception as e:
        await asyncio.to_thread(_mark_failure, failure_marker_path)
        logger.warning(
            "civitai_preview_fetch_failed",
            model_id=model_id,
            version_id=version_id,
            image_index=image_index,
            error=str(e),
        )
        return None, None, False


async def get_preview_deduplicated(model_id: int, version_id: int = None, image_index: int = 0) -> Tuple[Optional[bytes], Optional[str], bool]:
    """Fetch preview using deduplication."""
    dedup_key = make_key(
        "civitai_preview",
        model_id,
        version_id if version_id is not None else "default",
        image_index,
    )
    return await deduplicated(
        dedup_key,
        lambda: fetch_civitai_preview(model_id, version_id, image_index),
    )


async def prefetch_stale_model_previews() -> Dict[str, Any]:
    """Warm stale model preview cache entries with jittered, sampled background fetches."""
    if not PREVIEW_PREFETCH_ENABLED:
        logger.debug("preview_prefetch_disabled")
        return {"status": "disabled"}

    jitter_seconds = 0.0
    if PREVIEW_PREFETCH_JITTER_SECONDS > 0:
        jitter_seconds = random.uniform(0.0, PREVIEW_PREFETCH_JITTER_SECONDS)
        if jitter_seconds > 0:
            await asyncio.sleep(jitter_seconds)

    model_ids = await asyncio.to_thread(_list_civitai_model_ids_for_prefetch)
    total_models = len(model_ids)
    if total_models == 0:
        logger.debug("preview_prefetch_no_models")
        return {"status": "no_models"}

    stale_candidates = await asyncio.to_thread(
        _select_stale_prefetch_candidates,
        model_ids,
        PREVIEW_PREFETCH_MAX_CANDIDATES,
        PREVIEW_PREFETCH_BATCH_SIZE,
        PREVIEW_PREFETCH_STALE_AFTER_SECONDS,
    )

    if not stale_candidates:
        logger.debug("preview_prefetch_no_stale", total_models=total_models)
        return {
            "status": "no_stale",
            "total_models": total_models,
        }

    warmed = 0
    misses = 0
    for index, model_id in enumerate(stale_candidates):
        image_data, _content_type, _cache_hit = await fetch_civitai_preview(
            model_id,
            version_id=None,
            image_index=0,
            force_refresh=True,
        )
        if image_data:
            warmed += 1
        else:
            misses += 1

        if PREVIEW_PREFETCH_ITEM_DELAY_SECONDS > 0 and index < len(stale_candidates) - 1:
            await asyncio.sleep(random.uniform(0.0, PREVIEW_PREFETCH_ITEM_DELAY_SECONDS))

    logger.info(
        "preview_prefetch_cycle_complete",
        total_models=total_models,
        selected=len(stale_candidates),
        warmed=warmed,
        misses=misses,
        jitter_seconds=round(jitter_seconds, 3),
    )
    return {
        "status": "ok",
        "total_models": total_models,
        "selected": len(stale_candidates),
        "warmed": warmed,
        "misses": misses,
    }
