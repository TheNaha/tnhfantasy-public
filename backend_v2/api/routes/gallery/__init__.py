"""Gallery-domain routes: asset tagging and image sessions.

These two modules used to live in `api/routes/world_vault/`, which was the
wrong namespace for them by a wide margin — `tags.py` was 973 lines and
`sessions.py` 696, together 24% of that directory, and neither had anything to
do with the World Vault. A "session" here is a grouping of generated IMAGES,
and a tag here labels an ASSET. Both are gallery concepts.

They are here rather than in `world_vault/` because the World Vault namespace
now means one thing: the roleplay data layer. A reader browsing
`api/routes/world_vault/` was finding gallery code and had to work out why.

The URL prefixes are unchanged — `/api/v2/sessions`, `/api/v2/asset/{id}/tags`,
`/api/v2/tags`, `/api/v2/assets/auto-tag`, `/api/v2/assets/facet` — so the
frontend and every OpenAPI consumer see exactly what they saw before. This is
a move, not a change.
"""

from __future__ import annotations

from fastapi import APIRouter

from .sessions import router as sessions_router
from .tags import router as tags_router

router = APIRouter(prefix="/api/v2")

router.include_router(sessions_router, prefix="/sessions", tags=["Sessions"])
# No sub-prefix: the tag paths are already absolute under /api/v2
# (/asset/{id}/tags, /tags, /assets/auto-tag, /assets/facet).
router.include_router(tags_router, tags=["Tags"])

__all__ = ["router", "sessions_router", "tags_router"]
