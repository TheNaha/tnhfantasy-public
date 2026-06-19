from .schemas import *
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends

from sqlmodel import Session
from pydantic import BaseModel

from api.deps import get_session, get_session_sync
from services.model_service import ModelServiceV2
from core.exceptions import NotFoundError, ValidationError, ComfyError
from infrastructure.logging import model_logger

logger = model_logger()

router = APIRouter()

def get_model_service(session: Session) -> ModelServiceV2:
    return ModelServiceV2(session)

from services.model_preview_service import get_preview_deduplicated, prefetch_stale_model_previews


# ============================================================================
# PREVIEW IMAGES - Fetch from CivitAI and cache
# ============================================================================

import os
import asyncio
import httpx
from fastapi import Response
from infrastructure.http_client import get_http_client
from infrastructure.request_dedup import deduplicated, make_key

@router.get("/preview/{model_id}")
async def get_model_preview_image(model_id: int, version_id: int = None, image_index: int = 0):
    """
    Fetch and cache model preview image from CivitAI.
    Automatically filters out videos and returns the first image.
    """
    if image_index < 0:
        raise ValidationError("image_index must be >= 0")

    image_data, content_type, cache_hit = await get_preview_deduplicated(
        model_id, version_id, image_index
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


