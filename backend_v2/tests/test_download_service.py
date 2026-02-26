import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlmodel import Session

from services.download_service import DownloadService
from core.entities import Download, Model, ModelStatus
from core.events import EventType

class TestDownloadService:
    """Tests for DownloadService."""

    @pytest.fixture
    def mock_session(self):
        """Mock SQLModel Session."""
        return MagicMock(spec=Session)

    @pytest.fixture
    def mock_model_repo(self):
        """Mock ModelRepository."""
        with patch("services.download_service.ModelRepository") as MockRepo:
            repo_instance = MockRepo.return_value
            yield repo_instance

    @pytest.fixture
    def service(self, mock_session, mock_model_repo):
        """Create DownloadService instance with mocks."""
        return DownloadService(mock_session)

    @pytest.fixture
    def mock_emit(self):
        """Mock emit_download_event."""
        with patch("services.download_service.emit_download_event", new_callable=AsyncMock) as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_start_download_creates_active_download(self, service, mock_emit):
        """Test start_download creates download and emits event."""
        download = await service.start_download(
            name="test-model",
            url="http://example.com/model.safetensors",
            path="/models/checkpoints",
            provider_id="provider-1"
        )

        assert isinstance(download, Download)
        assert download.name == "test-model"
        assert download.url == "http://example.com/model.safetensors"
        assert download.status == "pending"

        # Check active downloads
        assert download.id in service._active_downloads
        assert service._active_downloads[download.id] == download

        # Check event emitted
        mock_emit.assert_called_once()
        args = mock_emit.call_args
        assert args[0][0] == EventType.DOWNLOAD_STARTED
        assert args[0][1]["id"] == download.id

    @pytest.mark.asyncio
    async def test_update_progress_updates_download(self, service, mock_emit):
        """Test update_progress updates download state and emits event."""
        # Setup initial download
        download = await service.start_download(
            name="test-model",
            url="http://example.com/model.safetensors",
            path="/models/checkpoints",
            provider_id="provider-1"
        )
        mock_emit.reset_mock()

        # Update progress
        updated = await service.update_progress(
            download_id=download.id,
            progress=50.0,
            speed="10MB/s",
            downloaded_size="500MB",
            total_size="1GB",
            message="Downloading..."
        )

        assert updated is not None
        assert updated.progress == 50.0
        assert updated.status == "downloading"
        assert updated.speed == "10MB/s"
        assert updated.downloaded_size == "500MB"
        assert updated.total_size == "1GB"
        assert updated.message == "Downloading..."

        # Check event emitted
        mock_emit.assert_called_once()
        args = mock_emit.call_args
        assert args[0][0] == EventType.DOWNLOAD_PROGRESS
        assert args[0][1]["progress"] == 50.0

    @pytest.mark.asyncio
    async def test_update_progress_not_found(self, service, mock_emit):
        """Test update_progress returns None for non-existent download."""
        result = await service.update_progress("non-existent", 50.0)
        assert result is None
        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_download_success(self, service, mock_emit, mock_model_repo):
        """Test complete_download finalizes download and updates repo."""
        # Setup
        download = await service.start_download(
            name="test-model",
            url="http://example.com/model.safetensors",
            path="/models/checkpoints",
            provider_id="provider-1"
        )
        mock_emit.reset_mock()

        # Mock repo response
        mock_model = MagicMock(spec=Model)
        mock_model.id = 123
        mock_model_repo.upsert.return_value = mock_model

        # Complete download
        completed = await service.complete_download(
            download_id=download.id,
            directory="checkpoints",
            source="civitai"
        )

        assert completed is not None
        assert completed.status == "completed"
        assert completed.progress == 100.0

        # Check repo calls
        mock_model_repo.upsert.assert_called_once_with(
            name="test-model",
            directory="checkpoints",
            url="http://example.com/model.safetensors",
            source="civitai"
        )
        mock_model_repo.update_provider_status.assert_called_once_with(
            model_id=123,
            provider_id="provider-1",
            status=ModelStatus.INSTALLED
        )

        # Check event emitted
        mock_emit.assert_called_once()
        args = mock_emit.call_args
        assert args[0][0] == EventType.DOWNLOAD_COMPLETED

        # Verify removed from active downloads
        assert download.id not in service._active_downloads

    @pytest.mark.asyncio
    async def test_complete_download_not_found(self, service, mock_emit, mock_model_repo):
        """Test complete_download returns None for non-existent download."""
        result = await service.complete_download("non-existent", "checkpoints")
        assert result is None
        mock_emit.assert_not_called()
        mock_model_repo.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_fail_download_success(self, service, mock_emit):
        """Test fail_download marks as failed and emits event."""
        # Setup
        download = await service.start_download(
            name="test-model",
            url="http://example.com/model.safetensors",
            path="/models/checkpoints",
            provider_id="provider-1"
        )
        mock_emit.reset_mock()

        # Fail download
        failed = await service.fail_download(
            download_id=download.id,
            error="Connection timeout"
        )

        assert failed is not None
        assert failed.status == "failed"
        assert failed.message == "Connection timeout"

        # Check event emitted
        mock_emit.assert_called_once()
        args = mock_emit.call_args
        assert args[0][0] == EventType.DOWNLOAD_FAILED
        assert args[0][1]["message"] == "Connection timeout"

        # Verify removed from active downloads
        assert download.id not in service._active_downloads

    @pytest.mark.asyncio
    async def test_fail_download_not_found(self, service, mock_emit):
        """Test fail_download returns None for non-existent download."""
        result = await service.fail_download("non-existent", "error")
        assert result is None
        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_active_downloads(self, service):
        """Test get_active_downloads returns list."""
        await service.start_download("d1", "url1", "path1", "p1")
        await service.start_download("d2", "url2", "path2", "p2")

        active = service.get_active_downloads()
        assert len(active) == 2
        assert isinstance(active[0], dict)
        names = {d["name"] for d in active}
        assert "d1" in names
        assert "d2" in names

    @pytest.mark.asyncio
    async def test_get_download(self, service):
        """Test get_download returns specific download."""
        download = await service.start_download("d1", "url1", "path1", "p1")

        fetched = service.get_download(download.id)
        assert fetched is not None
        assert fetched["id"] == download.id
        assert fetched["name"] == "d1"

        assert service.get_download("non-existent") is None
