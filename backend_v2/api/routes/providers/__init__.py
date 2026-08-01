from fastapi import APIRouter

from .crud import router as crud_router
from .lifecycle import router as lifecycle_router
from .reconciliation import router as reconciliation_router

router = APIRouter(prefix="/api/providers", tags=["providers"])
router.include_router(lifecycle_router)
router.include_router(reconciliation_router)
router.include_router(crud_router)
