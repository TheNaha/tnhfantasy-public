import pytest
import os
from provider_core.utils import get_safe_path, build_deploy_compatibility_response

def test_get_safe_path_valid():
    base_dir = "/mnt/data"
    path = "models/checkpoints/model.safetensors"
    result = get_safe_path(base_dir, path)
    expected = os.path.abspath(os.path.join(base_dir, path))
    assert result == expected

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
    expected = os.path.abspath(os.path.join(base_dir, path.lstrip("/\\")))
    assert result == expected

def test_get_safe_path_empty():
    base_dir = "/mnt/data"

    with pytest.raises(ValueError, match="Invalid path: path cannot be empty"):
        get_safe_path(base_dir, "")

    with pytest.raises(ValueError, match="Invalid path: path cannot be empty"):
        get_safe_path(base_dir, "/")

    with pytest.raises(ValueError, match="Invalid path: path cannot be empty"):
        get_safe_path(base_dir, "\\")


def test_build_deploy_compatibility_response_with_absolute_backend_url():
    payload = build_deploy_compatibility_response(
        backend_url="http://backend_v2:8002/",
        provider_id="modal-primary",
        provider_type="modal",
    )

    assert payload["status"] == "deprecated"
    assert payload["source_of_truth"] == "backend_orchestrator"
    assert payload["backend_deploy_endpoint"] == "http://backend_v2:8002/api/v2/providers/modal-primary/deploy"
    assert payload["backend_deploy_status_endpoint"] == "http://backend_v2:8002/api/v2/providers/modal-primary/deploy-status"


def test_build_deploy_compatibility_response_with_relative_fallback():
    payload = build_deploy_compatibility_response(
        backend_url="",
        provider_id="beam-primary",
        provider_type="beam",
    )

    assert payload["accepted"] is False
    assert payload["compatibility_mode"] is True
    assert payload["backend_deploy_endpoint"] == "/api/v2/providers/beam-primary/deploy"
    assert payload["backend_deploy_status_endpoint"] == "/api/v2/providers/beam-primary/deploy-status"
