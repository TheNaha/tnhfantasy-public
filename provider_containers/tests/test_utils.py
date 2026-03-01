import pytest
import os
from provider_core.utils import get_safe_path

def test_get_safe_path_valid():
    base_dir = "/mnt/data"
    path = "models/checkpoints/model.safetensors"
    result = get_safe_path(base_dir, path)
    assert result == "/mnt/data/models/checkpoints/model.safetensors"

def test_get_safe_path_traversal():
    base_dir = "/mnt/data"
    path = "../../../etc/passwd"
    with pytest.raises(ValueError, match="Access denied"):
        get_safe_path(base_dir, path)

def test_get_safe_path_absolute():
    base_dir = "/mnt/data"
    path = "/etc/passwd"
    # The lstrip prevents it from being absolute and puts it in base_dir
    result = get_safe_path(base_dir, path)
    assert result == "/mnt/data/etc/passwd"

def test_get_safe_path_empty():
    base_dir = "/mnt/data"

    with pytest.raises(ValueError, match="Invalid path: path cannot be empty"):
        get_safe_path(base_dir, "")

    with pytest.raises(ValueError, match="Invalid path: path cannot be empty"):
        get_safe_path(base_dir, "/")

    with pytest.raises(ValueError, match="Invalid path: path cannot be empty"):
        get_safe_path(base_dir, "\\")
