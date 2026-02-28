import os

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
    if not requested_path:
        raise ValueError("Invalid path: path cannot be empty")

    # Remove leading slashes to prevent absolute path interpretation
    clean_path = requested_path.lstrip("/\\")

    # Resolve full path
    full_path = os.path.abspath(os.path.join(base_dir, clean_path))
    base_path = os.path.abspath(base_dir)

    # Check if the resolved path starts with the base path
    if os.path.commonpath([base_path, full_path]) != base_path:
         raise ValueError("Access denied: Path outside allowed directory")

    return full_path
