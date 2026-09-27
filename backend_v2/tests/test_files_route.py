from unittest.mock import AsyncMock, mock_open, patch

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from api.deps import get_session
from api.error_handlers import register_exception_handlers
from api.routes.files import get_safe_path, router


def _png_bytes(width: int = 2, height: int = 2, fmt: str = "PNG") -> bytes:
    """Real image bytes - the upload routes verify content, not just extension."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (255, 0, 0)).save(buf, format=fmt)
    return buf.getvalue()


PNG_BYTES = _png_bytes()
JPEG_BYTES = _png_bytes(fmt="JPEG")


# Setup database fixtures
@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine

@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session

@pytest.fixture(name="client")
def client_fixture(session):
    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)

    app.dependency_overrides[get_session] = lambda: session

    return TestClient(app)

class TestFilesRoute:

    def test_get_safe_path_valid(self):
        base = "/tmp/base"
        path = "sub/file.txt"
        with patch("os.path.abspath", side_effect=lambda x: x):
            with patch("os.path.join", side_effect=lambda x, y: f"{x}/{y}"):
                with patch("os.path.commonpath", return_value=base):
                    result = get_safe_path(base, path)
                    assert result == f"{base}/{path}"

    def test_get_safe_path_invalid(self):
        base = "/tmp/base"
        path = "../file.txt"
        with patch("os.path.abspath", side_effect=lambda x: x):
            with patch("os.path.join", side_effect=lambda x, y: "/tmp/file.txt"):
                from core.exceptions import ValidationError
                with pytest.raises(ValidationError):
                    get_safe_path(base, path)

    @patch("api.routes.files._query_gallery_files")
    def test_list_files_output(self, mock_query_gallery_files, client):
        mock_query_gallery_files.return_value = {
            "files": [{"name": "test.png"}],
            "total": 1
        }

        response = client.get("/api/files?directory=output")
        assert response.status_code == 200
        data = response.json()
        assert data["files"][0]["name"] == "test.png"
        assert data["total"] == 1

    @patch("services.model_service.ModelServiceV2.list_models_by_directory")
    def test_list_files_models(self, mock_list_models_by_directory, client):
        mock_list_models_by_directory.return_value = [
            {
                "name": "model1",
                "versions": [{"is_default": True, "file": {"filename": "model1.safetensors"}}],
                "stats": {},
                "tags": []
            }
        ]

        response = client.get("/api/files?directory=models/checkpoints")
        assert response.status_code == 200
        data = response.json()
        assert len(data["files"]) == 1
        assert data["files"][0]["name"] == "model1.safetensors"


# A LoRA whose name and filenames say nothing useful — the exact shape that
# made "find a LORA for a specific character" impossible from the picker.
CHARACTER_LORA = {
    "id": "m-1",
    "name": "unnamed_lora_v2.safetensors",
    "civitai_model_id": 1009342,
    "type": "LORA",
    "description": "Style helper for the tent scene.",
    "creator": {"username": "someuser"},
    "base_model": "Illustrious",
    "tags": ["boob tent", "breasts", "clothing"],
    "stats": {},
    "versions": [
        {
            "is_default": True,
            "name": "v2",
            "base_model": "Illustrious",
            "trained_words": ["boob tent"],
            "file": {"filename": "unnamed_lora_v2.safetensors"},
        }
    ],
}

UNRELATED_LORA = {
    "id": "m-2",
    "name": "sunset_colors.safetensors",
    "civitai_model_id": 555,
    "type": "LORA",
    "description": "Warmer sunsets.",
    "creator": {"username": "someone"},
    "tags": ["landscape", "sunset"],
    "stats": {},
    "versions": [
        {
            "is_default": True,
            "name": "v1",
            "file": {"filename": "sunset_colors.safetensors"},
        }
    ],
}


@patch("services.model_service.ModelServiceV2.list_models_by_directory")
def test_list_files_models_search_covers_tags(mock_list, client):
    """The picker placeholder promised "name, tags, description" but only name
    and version filenames were searched, so a tag was not searchable at all."""
    mock_list.return_value = [CHARACTER_LORA, UNRELATED_LORA]

    response = client.get("/api/files?directory=models/loras&search=boob+tent")
    assert response.status_code == 200
    names = [f["name"] for f in response.json()["files"]]
    assert names == ["unnamed_lora_v2.safetensors"]


@patch("services.model_service.ModelServiceV2.list_models_by_directory")
def test_list_files_models_search_covers_description(mock_list, client):
    mock_list.return_value = [CHARACTER_LORA, UNRELATED_LORA]

    response = client.get("/api/files?directory=models/loras&search=warmer+sunsets")
    assert [f["name"] for f in response.json()["files"]] == ["sunset_colors.safetensors"]


@patch("services.model_service.ModelServiceV2.list_models_by_directory")
def test_list_files_models_search_covers_trained_words(mock_list, client):
    """Trained words are the trigger vocabulary and the only tag an
    HF-sourced LoRA has, so they have to be searchable too."""
    mock_list.return_value = [{**CHARACTER_LORA, "tags": []}, UNRELATED_LORA]

    response = client.get("/api/files?directory=models/loras&search=boob+tent")
    assert [f["name"] for f in response.json()["files"]] == ["unnamed_lora_v2.safetensors"]


@patch("services.model_service.ModelServiceV2.list_models_by_directory")
def test_list_files_models_search_is_case_insensitive_over_tags(mock_list, client):
    mock_list.return_value = [CHARACTER_LORA, UNRELATED_LORA]

    response = client.get("/api/files?directory=models/loras&search=Breasts")
    assert [f["name"] for f in response.json()["files"]] == ["unnamed_lora_v2.safetensors"]


@patch("services.model_service.ModelServiceV2.list_models_by_directory")
def test_list_files_models_search_survives_null_description_and_creator(mock_list, client):
    """description/creator are nullable on a real ModelV2; a naive join raises."""
    mock_list.return_value = [
        {**CHARACTER_LORA, "description": None, "creator": None, "tags": None, "stats": {}}
    ]

    response = client.get("/api/files?directory=models/loras&search=boob")
    assert response.status_code == 200
    assert [f["name"] for f in response.json()["files"]] == ["unnamed_lora_v2.safetensors"]


@patch("services.model_service.ModelServiceV2.list_models_by_directory")
def test_list_files_models_tag_filter_still_ands(mock_list, client):
    """The pre-existing tag filter the picker was failing to send."""
    mock_list.return_value = [CHARACTER_LORA, UNRELATED_LORA]

    response = client.get("/api/files?directory=models/loras&tags=boob+tent,clothing")
    assert [f["name"] for f in response.json()["files"]] == ["unnamed_lora_v2.safetensors"]

    response = client.get("/api/files?directory=models/loras&tags=boob+tent,landscape")
    assert response.json()["files"] == []



    @patch("os.path.exists")
    @patch("os.path.isfile")
    @patch("api.routes.files.FileResponse")
    def test_view_file_local(self, mock_file_response, mock_isfile, mock_exists, client):
        mock_exists.return_value = True
        mock_isfile.return_value = True

        # Mock FileResponse to prevent actual file access
        mock_file_response.return_value = Response(content=b"content")

        with patch("api.routes.files.get_safe_path", return_value="/tmp/output/test.png"):
            response = client.get("/api/view/output/test.png")
            assert response.status_code == 200
            assert response.content == b"content"

    @patch("glob.glob")
    @patch("os.path.exists")
    @patch("api.routes.files.FileResponse")
    def test_view_file_nested(self, mock_file_response, mock_exists, mock_glob, client):
        # local exists=False; resolver DB miss + exists=False; falls to glob (mocked)
        mock_exists.return_value = False
        mock_glob.return_value = ["/tmp/output/date/test.png"]

        mock_file_response.return_value = Response(content=b"content")

        with patch("api.routes.files.get_safe_path", return_value="/tmp/output/date/test.png"):
            response = client.get("/api/view/output/date/test.png")
            assert response.status_code == 200

    def test_view_file_not_found(self, client):
        with patch("os.path.exists", return_value=False):
            with patch("glob.glob", return_value=[]):
                response = client.get("/api/view/output/missing.png")
                assert response.status_code == 404

    @patch("os.path.exists")
    @patch("os.stat")
    @patch("hashlib.md5")
    @patch("api.routes.files.FileResponse")
    def test_serve_thumbnail_legacy(self, mock_file_response, mock_md5, mock_stat, mock_exists, client):
        mock_exists.return_value = True
        mock_stat.return_value.st_mtime = 123456
        mock_md5.return_value.hexdigest.return_value = "etag"
        mock_file_response.return_value = Response(content=b"thumb", headers={"ETag": '"etag"'})

        with patch("api.routes.files.get_safe_path", return_value="/tmp/output/test.png"):
            with patch("glob.glob", return_value=[]): # No new webp found
                response = client.get("/api/thumbnail/medium/test.png")
                assert response.status_code == 200
                assert response.headers["etag"] == '"etag"'

    @patch("os.path.getsize", return_value=7)
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    def test_upload_file(self, mock_file, mock_makedirs, mock_getsize, client):
        files = {"file": ("test.png", PNG_BYTES, "image/png")}
        with patch("api.routes.files.get_safe_path", return_value="/tmp/output/input"):
            response = client.post("/api/upload", files=files)
            assert response.status_code == 200
            assert response.json()["status"] == "success"

    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("api.routes.files.get_provider_service")
    def test_upload_input_image(self, mock_get_provider_service, mock_file, mock_makedirs, client):
        # Mock provider service
        mock_service = AsyncMock()
        mock_service.list_providers.return_value = []
        mock_get_provider_service.return_value = mock_service

        files = {"file": ("test.png", PNG_BYTES, "image/png")}
        response = client.post("/api/upload/input", files=files)
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert response.json()["width"] == 2

    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("api.routes.files.get_provider_service")
    def test_upload_mask(self, mock_get_provider_service, mock_file, mock_makedirs, client):
        mock_service = AsyncMock()
        mock_service.list_providers.return_value = []
        mock_get_provider_service.return_value = mock_service

        import base64

        payload = {
            "mask_data": "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode(),
            "source_filename": "source.png"
        }
        response = client.post("/api/upload/mask", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("os.remove")
    @patch("os.path.exists")
    def test_batch_delete(self, mock_exists, mock_remove, client):
        mock_exists.return_value = True
        payload = {
            "directory": "output",
            "files": ["test.png"]
        }
        with patch("api.routes.files.get_safe_path", return_value="/tmp/output/test.png"):
            response = client.post("/api/batch/delete", json=payload)
            assert response.status_code == 200
            assert response.json()["deleted"] == 1

    @patch("infrastructure.image_processor.read_image_metadata")
    @patch("os.path.exists")
    def test_batch_get_metadata(self, mock_exists, mock_read_meta, client):
        mock_exists.return_value = True
        mock_read_meta.return_value = {"width": 512}

        payload = {"paths": ["output/test.png"]}
        with patch("api.routes.files.get_safe_path", return_value="/tmp/output/test.png"):
            response = client.post("/api/files/metadata/batch", json=payload)
            assert response.status_code == 200
            assert response.json()["results"]["output/test.png"]["success"] is True

    def test_provider_file_proxy_removed(self, client):
        """The provider file proxy was an unvalidated path traversal.

        `path` went straight from the URL into HttpFileProxy.get_file, which only
        `quote(path, safe="/")`s it — `.` is a unreserved URI character, so `../`
        survived verbatim. Every other file endpoint in this module routes
        through get_safe_path(). It also had no frontend consumer, so it was both
        dead and unsafe; the endpoint is gone rather than patched.
        """
        response = client.get("/api/files/proxy/123/path/to/image.png")
        assert response.status_code == 404

