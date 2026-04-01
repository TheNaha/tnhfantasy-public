"""Tests for infrastructure/providers/base.py, beam_provider.py, and modal_provider.py"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from infrastructure.providers.base import ServerlessProvider, FileProxyProvider
from infrastructure.providers.beam_provider import BeamProvider, BeamFileProxy
from infrastructure.providers.modal_provider import ModalProvider, ModalFileProxy


# ===== BASE PROVIDER TESTS =====

class ConcreteProvider(ServerlessProvider):
    """Concrete implementation of ServerlessProvider for testing."""
    async def run_inference(self, workflow):
        pass

    async def download_model(self, url, path, token=None, preview_url=None, metadata=None):
        return {}

    async def list_models(self, directory):
        return []

    async def delete_model(self, path):
        return True

    def get_file_proxy(self):
        return None


class ConcreteFileProxy(FileProxyProvider):
    """Concrete implementation of FileProxyProvider for testing."""
    async def get_file(self, path):
        return b""

    async def delete_file(self, path):
        return True

    def get_proxy_url(self):
        return "http://test"


class TestServerlessProviderBase:
    def test_init_sets_provider_id(self):
        provider = ConcreteProvider("test-id", {"type": "test"})
        assert provider.provider_id == "test-id"

    def test_init_sets_config(self):
        config = {"type": "modal", "extra": "value"}
        provider = ConcreteProvider("test-id", config)
        assert provider.config == config

    def test_init_sets_provider_type(self):
        provider = ConcreteProvider("test-id", {"type": "beam"})
        assert provider.provider_type == "beam"

    def test_provider_type_defaults_to_unknown(self):
        provider = ConcreteProvider("test-id", {})
        assert provider.provider_type == "unknown"

    def test_get_provider_info(self):
        provider = ConcreteProvider("p1", {"type": "modal"})
        info = provider.get_provider_info()
        assert info["id"] == "p1"
        assert info["type"] == "modal"
        assert "config" in info

    def test_get_provider_info_has_config(self):
        config = {"type": "test", "key": "val"}
        provider = ConcreteProvider("p1", config)
        info = provider.get_provider_info()
        assert info["config"] == config


class TestFileProxyProviderBase:
    def test_init_sets_provider_id(self):
        proxy = ConcreteFileProxy("p1", {})
        assert proxy.provider_id == "p1"

    def test_init_sets_config(self):
        config = {"key": "value"}
        proxy = ConcreteFileProxy("p1", config)
        assert proxy.config == config

    def test_get_proxy_url(self):
        proxy = ConcreteFileProxy("p1", {})
        assert proxy.get_proxy_url() == "http://test"


# ===== BEAM PROVIDER TESTS =====

class TestBeamFileProxy:
    def get_proxy(self):
        return BeamFileProxy("beam-1", {}, "http://comfy-provider-beam-1:8000")

    def test_init_strips_trailing_slash(self):
        proxy = BeamFileProxy("p1", {}, "http://comfy-provider-p1:8000/")
        assert proxy.base_url == "http://comfy-provider-p1:8000"

    def test_get_proxy_url(self):
        proxy = self.get_proxy()
        assert proxy.get_proxy_url() == "http://comfy-provider-beam-1:8000"

    async def test_get_file_success(self):
        proxy = self.get_proxy()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"file_content"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        with patch("infrastructure.providers.beam_provider.get_http_client", return_value=mock_client):
            result = await proxy.get_file("path/to/file.safetensors")
        assert result == b"file_content"

    async def test_get_file_failure_raises(self):
        proxy = self.get_proxy()
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        with patch("infrastructure.providers.beam_provider.get_http_client", return_value=mock_client):
            with pytest.raises(Exception, match="Failed to get file"):
                await proxy.get_file("path/to/file.safetensors")

    async def test_delete_file_success(self):
        proxy = self.get_proxy()
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)
        with patch("infrastructure.providers.beam_provider.get_http_client", return_value=mock_client):
            result = await proxy.delete_file("path/to/file.safetensors")
        assert result is True

    async def test_delete_file_failure(self):
        proxy = self.get_proxy()
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)
        with patch("infrastructure.providers.beam_provider.get_http_client", return_value=mock_client):
            result = await proxy.delete_file("path/to/file.safetensors")
        assert result is False


class TestBeamProvider:
    def get_provider(self, extra_config=None):
        config = {
            "type": "beam",
            "credentials": {"api_key": "test-key"},
            "config": {"gpu_type": "A100"},
            "container_config": {"port": 8004},
        }
        if extra_config:
            config.update(extra_config)
        return BeamProvider("beam-primary", config)

    def test_init_sets_worker_url(self):
        provider = self.get_provider()
        assert provider.worker_url == "http://comfy-provider-beam-primary:8000"

    def test_init_credentials(self):
        provider = self.get_provider()
        assert provider.api_key == "test-key"

    def test_init_gpu_type(self):
        provider = self.get_provider()
        assert provider.gpu_type == "A100"

    def test_init_default_port(self):
        provider = BeamProvider("beam-primary", {"type": "beam"})
        assert provider.worker_url == "http://comfy-provider-beam-primary:8000"

    def test_get_file_proxy(self):
        provider = self.get_provider()
        proxy = provider.get_file_proxy()
        assert isinstance(proxy, BeamFileProxy)

    def test_provider_type(self):
        provider = self.get_provider()
        assert provider.provider_type == "beam"


# ===== MODAL PROVIDER TESTS =====

class TestModalFileProxy:
    def get_proxy(self):
        return ModalFileProxy("modal-1", {}, "http://comfy-provider-modal-1:8000")

    def test_init_strips_trailing_slash(self):
        proxy = ModalFileProxy("p1", {}, "http://comfy-provider-p1:8000/")
        assert proxy.base_url == "http://comfy-provider-p1:8000"

    def test_get_proxy_url(self):
        proxy = self.get_proxy()
        assert proxy.get_proxy_url() == "http://comfy-provider-modal-1:8000"

    async def test_get_file_success(self):
        proxy = self.get_proxy()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"modal_content"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        with patch("infrastructure.providers.modal_provider.get_http_client", return_value=mock_client):
            result = await proxy.get_file("models/test.safetensors")
        assert result == b"modal_content"

    async def test_get_file_failure_raises(self):
        proxy = self.get_proxy()
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        with patch("infrastructure.providers.modal_provider.get_http_client", return_value=mock_client):
            with pytest.raises(Exception, match="Failed to get file"):
                await proxy.get_file("models/test.safetensors")

    async def test_delete_file_success(self):
        proxy = self.get_proxy()
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)
        with patch("infrastructure.providers.modal_provider.get_http_client", return_value=mock_client):
            result = await proxy.delete_file("models/test.safetensors")
        assert result is True

    async def test_delete_file_failure(self):
        proxy = self.get_proxy()
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)
        with patch("infrastructure.providers.modal_provider.get_http_client", return_value=mock_client):
            result = await proxy.delete_file("models/test.safetensors")
        assert result is False


class TestModalProvider:
    def get_provider(self, extra_config=None):
        config = {
            "type": "modal",
            "credentials": {"username": "testuser"},
            "container_config": {"port": 8001},
        }
        if extra_config:
            config.update(extra_config)
        return ModalProvider("modal-primary", config)

    def test_init_sets_worker_url(self):
        provider = self.get_provider()
        assert provider.worker_url == "http://comfy-provider-modal-primary:8000"

    def test_init_credentials(self):
        provider = self.get_provider()
        assert provider.username == "testuser"

    def test_init_default_port(self):
        provider = ModalProvider("modal-1", {"type": "modal"})
        assert provider.worker_url == "http://comfy-provider-modal-1:8000"

    def test_get_file_proxy(self):
        provider = self.get_provider()
        proxy = provider.get_file_proxy()
        assert isinstance(proxy, ModalFileProxy)

    def test_provider_type(self):
        provider = self.get_provider()
        assert provider.provider_type == "modal"

    def test_get_provider_info(self):
        provider = self.get_provider()
        info = provider.get_provider_info()
        assert info["id"] == "modal-primary"
