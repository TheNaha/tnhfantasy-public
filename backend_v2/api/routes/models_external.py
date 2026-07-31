from typing import Any, Dict

from fastapi import APIRouter, Depends
from core.exceptions import NotFoundError, ValidationError, ComfyError, ProviderError
from pydantic import BaseModel

from api.deps import get_external_model_service
from services.external_model_service import ExternalModelService, ExternalModelServiceError

router = APIRouter(prefix="/api/v2/models/external", tags=["models-v2"])


class ParseUrlRequest(BaseModel):
    url: str


@router.post("/parse")
async def parse_model_url(
    request: ParseUrlRequest,
    service: ExternalModelService = Depends(get_external_model_service),
) -> Dict[str, Any]:
    """Parse a model URL from CivitAI or HuggingFace and return normalized metadata."""
    try:
        return await service.parse_model_url(request.url)
    except ExternalModelServiceError as exc:
        raise ProviderError("ExternalModelService", exc.detail) from exc


@router.get("/civitai/enums")
async def get_civitai_enums(
    service: ExternalModelService = Depends(get_external_model_service),
) -> Dict[str, Any]:
    """Get valid enum values for CivitAI filters."""
    try:
        return await service.get_civitai_enums()
    except ExternalModelServiceError as exc:
        raise ProviderError("ExternalModelService", exc.detail) from exc

@router.get("/civitai/tags")
async def get_civitai_tags(
    limit: int = 20,
    service: ExternalModelService = Depends(get_external_model_service),
) -> Dict[str, Any]:
    """Get valid tags for CivitAI filters."""
    try:
        return await service.get_civitai_tags(limit=limit)
    except ExternalModelServiceError as exc:
        raise ProviderError("ExternalModelService", exc.detail) from exc

@router.get("/civitai")
async def search_civitai(
    query: str = "",
    limit: int = 20,
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
) -> Dict[str, Any]:
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
    query: str,
    limit: int = 20,
    service: ExternalModelService = Depends(get_external_model_service),
) -> Dict[str, Any]:
    """Search models on HuggingFace."""
    try:
        return await service.search_huggingface(query=query, limit=limit)
    except ExternalModelServiceError as exc:
        raise ProviderError("ExternalModelService", exc.detail) from exc



