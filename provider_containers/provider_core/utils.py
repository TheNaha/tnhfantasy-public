import os
from typing import Any, Dict

def get_safe_path(base_dir: str, requested_path: str) -> str:
    """
    Resolve and validate a path to prevent directory traversal.

    Args:
        base_dir: The trusted base directory.
        requested_path: The user-provided path component.

    Returns:
        The absolute resolved path if valid.

    Raises:
        ValueError if path traversal is detected.
    """
    # Remove leading slashes to prevent absolute path interpretation
    clean_path = requested_path.lstrip("/\\")

    if not clean_path:
        raise ValueError("Invalid path: path cannot be empty")

    # Resolve full path
    full_path = os.path.abspath(os.path.join(base_dir, clean_path))
    base_path = os.path.abspath(base_dir)

    # Check if the resolved path starts with the base path
    if os.path.commonpath([base_path, full_path]) != base_path:
         raise ValueError("Access denied: Path outside allowed directory")

    return full_path


def build_deploy_compatibility_response(
    *,
    backend_url: str,
    provider_id: str,
    provider_type: str,
) -> Dict[str, Any]:
    """Return a compatibility payload for deprecated worker-local deploy endpoints."""
    base_url = (backend_url or "").rstrip("/")
    if base_url:
        deploy_endpoint = f"{base_url}/api/providers/{provider_id}/deploy"
        status_endpoint = f"{base_url}/api/providers/{provider_id}/deploy-status"
    else:
        deploy_endpoint = f"/api/providers/{provider_id}/deploy"
        status_endpoint = f"/api/providers/{provider_id}/deploy-status"

    return {
        "status": "deprecated",
        "accepted": False,
        "compatibility_mode": True,
        "source_of_truth": "backend_orchestrator",
        "message": "Worker-local deploy endpoint is deprecated; use backend provider deploy endpoint.",
        "provider_id": provider_id,
        "provider_type": provider_type,
        "backend_deploy_endpoint": deploy_endpoint,
        "backend_deploy_status_endpoint": status_endpoint,
    }
