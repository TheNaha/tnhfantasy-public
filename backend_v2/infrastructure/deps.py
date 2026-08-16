# Infrastructure-level dependency injection
#
# Services and background tasks should import from here, NOT from api.deps.
# api.deps is the FastAPI-specific layer; this module is the infrastructure layer.
from collections.abc import AsyncIterator

from infrastructure.database import get_session_context, get_session_sync

_global_container_manager = None

def set_global_container_manager(cm):
    """Set the global fallback container manager instance for background tasks."""
    global _global_container_manager
    _global_container_manager = cm

def get_container_manager(request=None):
    """Get container manager from app state if in request context, else fallback to global."""
    if request is not None and hasattr(request, "app"):
        return getattr(request.app.state, "container_manager", None)
    return _global_container_manager
