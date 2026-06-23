import os
import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, Response

import httpx

from api.deps import get_session
from core.exceptions import NotFoundError, ValidationError
from api.deps import get_http_client
from api.deps import deduplicated, make_key
from api.deps import model_logger
from services.model_preview_service import get_preview_deduplicated, prefetch_stale_model_previews

logger = model_logger()

router = APIRouter()


@router.get("/preview/{model_id}")
async def get_model_preview_image(model_id: int, version_id: int = None, image_index: int = 0, width: int = None):
    if image_index < 0:
        raise ValidationError("image_index must be >= 0")

    image_data, content_type, cache_hit = await get_preview_deduplicated(
        model_id, version_id, image_index, width
    )

    if not image_data:
        raise NotFoundError("Resource", "Preview image not found")

    return Response(
        content=image_data,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400",
            "X-Cache-Source": "civitai-proxy",
            "X-Cache-Status": "hit" if cache_hit else "miss",
        }
    )
