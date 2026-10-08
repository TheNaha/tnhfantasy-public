# Infrastructure-level dependency injection
#
# Services and background tasks should import from here, NOT from api.deps.
# api.deps is the FastAPI-specific layer; this module is the infrastructure layer.
# Re-exports below are consumed by api.deps; do not remove.

from collections.abc import AsyncIterator

from infrastructure.database import get_session_context, get_session_sync  # noqa: F401
