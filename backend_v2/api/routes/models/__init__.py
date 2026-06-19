from fastapi import APIRouter

from .crud import router as crud_router
from .provider_sync import router as provider_sync_router
from .maintenance import router as maintenance_router
from .preview import router as preview_router

router = APIRouter(prefix="/api/v2/models", tags=["models-v2"])

router.include_router(crud_router)
router.include_router(provider_sync_router)
router.include_router(maintenance_router)
router.include_router(preview_router)
