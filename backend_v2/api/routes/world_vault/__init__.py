from fastapi import APIRouter

from .characters import router as characters_router
from .chats import router as chats_router
from .lorebooks import router as lorebooks_router
from .scenarios import router as scenarios_router
from .stories import router as stories_router

router = APIRouter(prefix="/api/v2")

router.include_router(characters_router, prefix="/characters", tags=["Characters"])
router.include_router(chats_router, prefix="/chats", tags=["Chats"])
router.include_router(lorebooks_router, prefix="/lorebooks", tags=["Lorebooks"])
router.include_router(scenarios_router, prefix="/scenarios", tags=["Scenarios"])
router.include_router(stories_router, prefix="/stories", tags=["Stories"])
