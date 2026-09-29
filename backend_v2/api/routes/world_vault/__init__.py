from fastapi import APIRouter

from .characters import router as characters_router
from .chats import router as chats_router
from .branches import router as branches_router
from .worlds import router as worlds_router
from .llm_config import router as llm_config_router
from .lorebooks import router as lorebooks_router
from .memories import router as memories_router
from .scenarios import router as scenarios_router
from .sessions import router as sessions_router
from .personas import router as personas_router
from .stories import router as stories_router
from .tags import router as tags_router
from .voices import router as voices_router
from .world_hub import router as world_hub_router
from .locations import router as locations_router
from .timeline import router as timeline_router
from .graph_layout import router as graph_layout_router
from .util import router as util_router

router = APIRouter(prefix="/api/v2")

router.include_router(characters_router, prefix="/characters", tags=["Characters"])
router.include_router(chats_router, prefix="/chats", tags=["Chats"])
router.include_router(branches_router, prefix="/chats", tags=["Branching"])
router.include_router(lorebooks_router, prefix="/lorebooks", tags=["Lorebooks"])
router.include_router(memories_router, prefix="/memories", tags=["Memories"])
router.include_router(scenarios_router, prefix="/scenarios", tags=["Scenarios"])
router.include_router(personas_router, prefix="/personas", tags=["Personas"])
router.include_router(worlds_router, prefix="/worlds", tags=["Worlds"])
router.include_router(stories_router, prefix="/stories", tags=["Stories"])
router.include_router(sessions_router, prefix="/sessions", tags=["Sessions"])
# No sub-prefix: the tag paths are already absolute under /api/v2
# (/asset/{id}/tags, /tags, /assets/auto-tag, /assets/facet).
router.include_router(tags_router, tags=["Tags"])
router.include_router(voices_router, prefix="/voices", tags=["Voices"])
router.include_router(world_hub_router, prefix="/world-vault", tags=["World Vault"])
router.include_router(locations_router, prefix="/locations", tags=["Locations"])
router.include_router(timeline_router, tags=["Timeline"])
router.include_router(llm_config_router, prefix="/llm", tags=["LLM Configuration"])
router.include_router(graph_layout_router, prefix="/world-vault/graph-layout", tags=["Graph Layout"])
router.include_router(util_router, prefix="/world-vault", tags=["World Vault"])
