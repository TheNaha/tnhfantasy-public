import pytest
import os
import shutil
import json
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
from fastapi.testclient import TestClient
from fastapi import FastAPI, Response
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from api.routes.files import router, get_safe_path
from api.deps import get_session, get_provider_service
from api.error_handlers import register_exception_handlers
from services.gallery_indexer import GalleryIndexer

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

    @patch("services.gallery_indexer.gallery_indexer")
    def test_list_files_output(self, mock_indexer, client):
        mock_indexer.get_files.return_value = {
            "files": [{"name": "test.png"}],
            "total": 1
        }

        response = client.get("/api/files?directory=output")
        assert response.status_code == 200
        data = response.json()
        assert data["files"][0]["name"] == "test.png"
        assert data["total"] == 1

    @patch("api.routes.files.get_model_service_v2")
    def test_list_files_models(self, mock_get_service, client):
        # Setup mock service
        mock_service = AsyncMock()
        mock_service.list_models_by_directory.return_value = [
            {
                "name": "model1",
                "versions": [{"is_default": True, "file": {"filename": "model1.safetensors"}}],
                "stats": {},
                "tags": []
            }
        ]
        mock_get_service.return_value = mock_service

        mock_session = MagicMock()
        
        @asynccontextmanager
        async def fake_session_context():
            yield mock_session

        with patch("api.routes.files.get_session_context", fake_session_context):
            response = client.get("/api/files?directory=models/checkpoints")
            assert response.status_code == 200
            data = response.json()
            assert len(data["files"]) == 1
            assert data["files"][0]["name"] == "model1.safetensors"

    @patch("api.routes.files.get_model_service_v2")
    def test_list_files_models_closes_session_generator(self, mock_get_service, client):
        class DummySessionContext:
            def __init__(self, session):
                self._session = session
                self.closed = False

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                self.closed = True

        mock_service = AsyncMock()
        mock_service.list_models_by_directory.return_value = []
        mock_get_service.return_value = mock_service

        session_context = DummySessionContext(MagicMock())

        with patch("api.routes.files.get_session_context", return_value=session_context):
            response = client.get("/api/files?directory=models/checkpoints")
            assert response.status_code == 200
            assert session_context.closed is True

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
        # First check fails (direct path), second passes (glob)
        mock_exists.side_effect = [False, True]
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

    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    def test_upload_file(self, mock_file, mock_makedirs, client):
        files = {"file": ("test.png", b"content", "image/png")}
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

        files = {"file": ("test.png", b"content", "image/png")}
        response = client.post("/api/upload/input", files=files)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("api.routes.files.get_provider_service")
    def test_upload_mask(self, mock_get_provider_service, mock_file, mock_makedirs, client):
        mock_service = AsyncMock()
        mock_service.list_providers.return_value = []
        mock_get_provider_service.return_value = mock_service

        payload = {
            "mask_data": "base64,data",
            "source_filename": "source.png"
        }
        with patch("base64.b64decode", return_value=b"content"):
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

    @patch("api.routes.files.get_provider_service")
    def test_proxy_file(self, mock_get_provider_service, client):
        mock_service = AsyncMock()
        mock_provider = MagicMock()
        mock_provider.type = "modal"
        mock_provider.credentials = {}
        mock_provider.config = {}
        mock_provider.container_config = {}
        mock_service.get_provider.return_value = mock_provider
        mock_get_provider_service.return_value = mock_service

        with patch("infrastructure.providers.create_provider_client") as mock_create_provider:
            mock_instance = MagicMock()
            mock_proxy = MagicMock()
            mock_proxy.get_file = AsyncMock(return_value=b"content")
            mock_instance.get_file_proxy.return_value = mock_proxy
            mock_create_provider.return_value = mock_instance

            response = client.get("/api/files/proxy/123/path/to/image.png")
            assert response.status_code == 200
            assert response.content == b"content"
