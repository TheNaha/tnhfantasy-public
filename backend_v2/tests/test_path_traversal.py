import os
import shutil

import pytest
from fastapi.testclient import TestClient

import api.routes.files as files_module

# Setup directories for testing
# We use paths relative to the execution context (repo root or backend_v2)
TEST_OUTPUT_DIR = os.path.abspath("test_output_secure")
TEST_INPUT_DIR = os.path.abspath("test_input_secure")
SECRET_FILE_PATH = os.path.abspath("secret_secure.txt")
TO_DELETE_PATH = os.path.abspath("to_delete_secure.txt")

@pytest.fixture(scope="module", autouse=True)
def setup_directories():
    os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEST_INPUT_DIR, exist_ok=True)

    # Create a secret file outside the allowed directories
    with open(SECRET_FILE_PATH, "w") as f:
        f.write("sensitive data")

    # Monkeypatch the OUTPUT_DIR and INPUT_DIR in the files module
    original_output = files_module.OUTPUT_DIR
    original_input = files_module.INPUT_DIR
    files_module.OUTPUT_DIR = TEST_OUTPUT_DIR
    files_module.INPUT_DIR = TEST_INPUT_DIR

    yield

    # Cleanup
    files_module.OUTPUT_DIR = original_output
    files_module.INPUT_DIR = original_input
    if os.path.exists(SECRET_FILE_PATH):
        os.remove(SECRET_FILE_PATH)
    if os.path.exists(TO_DELETE_PATH):
        os.remove(TO_DELETE_PATH)

    shutil.rmtree(TEST_OUTPUT_DIR, ignore_errors=True)
    shutil.rmtree(TEST_INPUT_DIR, ignore_errors=True)

    # Also clean up any hacked file
    hacked_path = os.path.abspath("hacked.txt")
    if os.path.exists(hacked_path):
        os.remove(hacked_path)

    hacked_filename_path = os.path.abspath("hacked_filename.txt")
    if os.path.exists(hacked_filename_path):
        os.remove(hacked_filename_path)

def test_view_file_traversal(client: TestClient):
    """
    Test that path traversal in /api/view/{path} is blocked.
    """
    # Try to access the secret file via path traversal
    response = client.get("/api/view/output/../secret_secure.txt")

    # Expect 403 Forbidden (or 404 if we handle it that way)
    # 403 is better for security violation
    assert response.status_code in [403, 404]

    # Double check content is not leaked
    if response.status_code == 200:
        assert response.content != b"sensitive data"

def test_upload_file_traversal(client: TestClient):
    """
    Test that path traversal in /api/upload is blocked.
    """
    # Try to upload to ../
    response = client.post(
        "/api/upload",
        files={"file": ("hacked.txt", b"hacked content")},
        params={"path": "../"}
    )

    target_file = os.path.abspath("hacked.txt")

    # File should NOT be created
    assert not os.path.exists(target_file)

    # Expect error response
    assert response.status_code in [403, 400, 500]

def test_batch_delete_traversal(client: TestClient):
    """
    Test that path traversal in /api/batch/delete is blocked.
    """
    # Create a file to delete outside allowed dir
    with open(TO_DELETE_PATH, "w") as f:
        f.write("delete me")

    payload = {
        "directory": "output",
        "files": ["../to_delete_secure.txt"]
    }

    client.post("/api/batch/delete", json=payload)

    # File should STILL exist
    assert os.path.exists(TO_DELETE_PATH)

    # Check response indicates failure or partial success (depending on impl)
    # But critical check is file existence

def test_upload_filename_traversal(client: TestClient):
    """
    Test that path traversal via filename in /api/upload is blocked.
    """
    # Try to upload a file where filename contains traversal characters
    # e.g. filename="../../hacked_filename.txt"
    client.post(
        "/api/upload",
        files={"file": ("../../hacked_filename.txt", b"hacked content")},
        data={"path": "input"}
    )

    hacked_path = os.path.abspath("hacked_filename.txt")

    # Check if vulnerability exists (file created in root)
    if os.path.exists(hacked_path):
        os.remove(hacked_path) # Cleanup
        pytest.fail(f"VULNERABILITY DETECTED: File created at {hacked_path}")

    # The file should be sanitized and saved in TEST_OUTPUT_DIR/input/hacked_filename.txt
    # Or rejected.

    assert not os.path.exists(hacked_path), "Path traversal succeeded via filename"

def test_upload_mask_traversal(client: TestClient):
    """
    Test that path traversal via source_filename in /api/upload/mask is blocked.
    """
    payload = {
        "mask_data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNiAAAABgADNjd8qAAAAABJRU5ErkJggg==",
        "source_filename": "../../hacked_mask.png"
    }

    response = client.post("/api/upload/mask", json=payload)

    if response.status_code == 200:
        data = response.json()
        path = data.get("path", "")
        # If vulnerable, path might contain traversal
        assert "../" not in path, "Path traversal characters returned in path"
