from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.deps import get_external_model_service
from core.exceptions import ProviderError
from services.external_model_service import (
    ExternalModelService,
    ExternalModelServiceError,
)

router = APIRouter(prefix="/api/v2/models/external", tags=["models-v2"])


class ParseUrlRequest(BaseModel):
    url: str


@router.post("/parse")
async def parse_model_url(
    request: ParseUrlRequest,
    service: ExternalModelService = Depends(get_external_model_service),
) -> dict[str, Any]:
    """Parse a model URL from CivitAI or HuggingFace and return normalized metadata."""
    try:
        return await service.parse_model_url(request.url)
    except ExternalModelServiceError as exc:
        raise ProviderError("ExternalModelService", exc.detail) from exc


@router.get("/civitai/enums")
async def get_civitai_enums(
    service: ExternalModelService = Depends(get_external_model_service),
) -> dict[str, Any]:
    """Get valid enum values for CivitAI filters."""
    try:
        return await service.get_civitai_enums()
    except ExternalModelServiceError as exc:
        raise ProviderError("ExternalModelService", exc.detail) from exc

@router.get("/civitai/tags")
async def get_civitai_tags(
    limit: int = Query(20, ge=1, le=100),
    service: ExternalModelService = Depends(get_external_model_service),
) -> dict[str, Any]:
    """Get valid tags for CivitAI filters."""
    try:
        return await service.get_civitai_tags(limit=limit)
    except ExternalModelServiceError as exc:
        raise ProviderError("ExternalModelService", exc.detail) from exc

@router.get("/civitai")
async def search_civitai(
    # Ceiling on the upstream CivitAI search term. Unbounded before: the
    # value is forwarded to CivitAI and also used to filter locally, and a
    # megabyte of text costs nothing to send and everything to check.
    query: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100),
    types: str = None,
    sort: str = None,
    baseModels: str = None,
    nsfw: bool = None,
    period: str = None,
    page: int = None,
    cursor: str = None,
    username: str = None,
    tag: str = None,
    service: ExternalModelService = Depends(get_external_model_service),
) -> dict[str, Any]:
    """Search models on CivitAI."""
    try:
        return await service.search_civitai(
            query=query, 
            limit=limit,
            types=types,
            sort=sort,
            baseModels=baseModels,
            nsfw=nsfw,
            period=period,
            page=page,
            cursor=cursor,
            username=username,
            tag=tag
        )
    except ExternalModelServiceError as exc:
        raise ProviderError("ExternalModelService", exc.detail) from exc


@router.get("/huggingface")
async def search_huggingface(
    query: str = Query(..., max_length=200),
    limit: int = Query(20, ge=1, le=100),
    service: ExternalModelService = Depends(get_external_model_service),
) -> dict[str, Any]:
    """Search models on HuggingFace."""
    try:
        return await service.search_huggingface(query=query, limit=limit)
    except ExternalModelServiceError as exc:
        raise ProviderError("ExternalModelService", exc.detail) from exc



