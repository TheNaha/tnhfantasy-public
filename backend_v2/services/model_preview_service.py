import asyncio
import os
import random
import time
from typing import Any

import httpx

from api.deps import get_session_sync
from infrastructure.config_helpers import (
    resolve_env_bool,
    resolve_env_float,
    resolve_env_int,
)
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from infrastructure.request_dedup import deduplicated, make_key

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


def get_cache_path(model_id: int, version_id: int = None, image_index: int = 0, width: int = None) -> str:
    """Get cache path for a model preview image."""
    os.makedirs(PREVIEW_CACHE_DIR, exist_ok=True)
    
    width_suffix = f"_{width}" if width else ""
    
    if version_id is not None:
        return os.path.join(PREVIEW_CACHE_DIR, f"{model_id}_{version_id}_{image_index}{width_suffix}.img")
    return os.path.join(PREVIEW_CACHE_DIR, f"{model_id}_{image_index}{width_suffix}.img")


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
    except Exception as exc:
        logger.debug("failure_marker_read_failed", path=failure_marker_path, error=str(exc))
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
        except Exception as exc:
            logger.debug("cache_meta_read_failed", path=cache_meta_path, error=str(exc))
            pass

    return cached_content, cached_content_type


def _save_preview_to_cache(cache_path: str, cache_meta_path: str, image_data: bytes, content_type: str) -> None:
    import uuid
    tmp_cache_path = f"{cache_path}.{uuid.uuid4().hex}.tmp"
    tmp_meta_path = f"{cache_meta_path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp_cache_path, 'wb') as image_file:
            image_file.write(image_data)
        with open(tmp_meta_path, 'w', encoding='utf-8') as meta_file:
            meta_file.write(content_type)
        os.replace(tmp_cache_path, cache_path)
        os.replace(tmp_meta_path, cache_meta_path)
    finally:
        if os.path.exists(tmp_cache_path):
            os.remove(tmp_cache_path)
        if os.path.exists(tmp_meta_path):
            os.remove(tmp_meta_path)


def _select_preview_url(model_data: dict[str, Any], version_id: int | None, image_index: int) -> str | None:
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
    version_id: int | None,
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


def _list_civitai_model_ids_for_prefetch() -> list[int]:
    from sqlmodel import select

    from core.entities import ModelV2

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
    model_ids: list[int],
    max_candidates: int,
    batch_size: int,
    stale_after_seconds: int,
) -> list[int]:
    if not model_ids or batch_size <= 0:
        return []

    shuffled_ids = model_ids[:]
    random.shuffle(shuffled_ids)

    if max_candidates > 0 and len(shuffled_ids) > max_candidates:
        shuffled_ids = shuffled_ids[:max_candidates]

    stale_candidates: list[int] = []
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
    width: int = None,
) -> tuple[bytes | None, str | None, bool]:
    """Fetch preview image from CivitAI API and cache it using non-blocking I/O.
    Returns (image_data, content_type, is_cache_hit).
    """
    cache_path = get_cache_path(model_id, version_id, image_index, width)
    cache_meta_path = _get_cache_meta_path(cache_path)
    
    # Use base path for markers so we don't duplicate failures
    base_cache_path = get_cache_path(model_id, version_id, image_index)
    failure_marker_path = _get_failure_marker_path(base_cache_path)
    not_found_marker_path = _get_not_found_marker_path(base_cache_path)

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

    base_image_data = None
    base_content_type = None

    if width is not None and not force_refresh:
        base_meta_path = _get_cache_meta_path(base_cache_path)
        base_image_data, base_content_type = await asyncio.to_thread(
            _load_preview_from_cache,
            base_cache_path,
            base_meta_path,
        )

    if base_image_data is None:
        from services.external_model_service import ExternalModelServiceError
        try:
            async def _fetch_base():
                from services.external_model_service import ExternalModelService
                external_service = ExternalModelService()
                model_data = await external_service.get_civitai_model(model_id)
        
                image_url = _select_preview_url(model_data, version_id, image_index)
                if not image_url:
                    return None, None
        
                client = get_http_client()
                img_response = await client.get(image_url, timeout=PREVIEW_IMAGE_TIMEOUT_SECONDS)
                img_response.raise_for_status()
                b_image_data = img_response.content
                b_content_type = img_response.headers.get('Content-Type', 'image/jpeg')
        
                base_meta_path = _get_cache_meta_path(base_cache_path)
                await asyncio.to_thread(
                    _save_preview_to_cache,
                    base_cache_path,
                    base_meta_path,
                    b_image_data,
                    b_content_type,
                )
                await asyncio.to_thread(_clear_failure_marker, failure_marker_path)
                await asyncio.to_thread(_clear_failure_marker, not_found_marker_path)
                return b_image_data, b_content_type

            base_dedup_key = make_key("civitai_preview_base", model_id, version_id if version_id is not None else "default", image_index)
            base_image_data, base_content_type = await deduplicated(base_dedup_key, _fetch_base)
            
            if base_image_data is None:
                return None, None, False
            
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
                    "civitai_preview_http_404",
                    model_id=model_id,
                    version_id=version_id,
                    image_index=image_index,
                )
                return None, None, False
    
            await asyncio.to_thread(_mark_failure, failure_marker_path)
            logger.warning(
                "civitai_preview_http_error",
                model_id=model_id,
                version_id=version_id,
                image_index=image_index,
                error=str(e),
            )
            return None, None, False
        except Exception as e:
            await asyncio.to_thread(_mark_failure, failure_marker_path)
            logger.error(
                "civitai_preview_unexpected_error",
                model_id=model_id,
                version_id=version_id,
                image_index=image_index,
                error=str(e),
            )
            return None, None, False

    if width is None:
        return base_image_data, base_content_type, False
        
    def _resize(data: bytes, w: int, content_type: str) -> tuple[bytes, str]:
        try:
            import io

            from PIL import Image
            img = Image.open(io.BytesIO(data))
            if img.mode == 'RGBA':
                bg = Image.new('RGB', img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            img.thumbnail((w, w), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            fmt = "JPEG"
            if "png" in content_type.lower():
                fmt = "PNG"
            elif "webp" in content_type.lower():
                fmt = "WEBP"
            img.save(out, format=fmt, quality=85)
            return out.getvalue(), f"image/{fmt.lower()}"
        except Exception as e:
            logger.error("preview_resize_failed", error=str(e))
            return data, content_type

    resized_data, resized_content_type = await asyncio.to_thread(_resize, base_image_data, width, base_content_type)
    
    await asyncio.to_thread(
        _save_preview_to_cache,
        cache_path,
        cache_meta_path,
        resized_data,
        resized_content_type,
    )
    
    return resized_data, resized_content_type, False



async def get_preview_deduplicated(model_id: int, version_id: int = None, image_index: int = 0, width: int = None) -> tuple[bytes | None, str | None, bool]:
    """Fetch preview using deduplication."""
    dedup_key = make_key(
        "civitai_preview",
        model_id,
        version_id if version_id is not None else "default",
        image_index,
        width if width is not None else "full",
    )
    return await deduplicated(
        dedup_key,
        lambda: fetch_civitai_preview(model_id, version_id, image_index, width=width),
    )


async def prefetch_stale_model_previews() -> dict[str, Any]:
    """Warm stale model preview cache entries with jittered, sampled background fetches."""
    if not PREVIEW_PREFETCH_ENABLED:
        logger.debug("preview_prefetch_disabled")
        return {"status": "disabled"}

    try:
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
    except asyncio.CancelledError:
        logger.debug("preview_prefetch_cancelled_due_to_shutdown")
        return {"status": "cancelled"}
