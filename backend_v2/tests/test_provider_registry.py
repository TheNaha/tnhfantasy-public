# Provider Registry Unit Tests

import asyncio

import pytest

from infrastructure.providers.provider_registry import (
    ProviderRegistry,
    ProviderTypeConfig,
)


class TestProviderTypeConfig:
    """Test ProviderTypeConfig dataclass."""
    
    def test_create_config(self):
        """Test creating a provider type config."""
        config = ProviderTypeConfig(
            type_name="test",
            required_credentials=["api_key"],
            optional_credentials=["region"],
            required_config=["app_name"],
            optional_config=["timeout"],
        )
        
        assert config.type_name == "test"
        assert "api_key" in config.required_credentials
        assert config.default_port == 8000
    
    def test_validate_credentials_missing(self):
        """Test credential validation finds missing fields."""
        config = ProviderTypeConfig(
            type_name="test",
            required_credentials=["token_id", "token_secret"],
        )
        
        # Missing token_secret
        missing = config.validate_credentials({"token_id": "abc"})
        
        assert "token_secret" in missing
        assert "token_id" not in missing
    
    def test_validate_credentials_complete(self):
        """Test credential validation passes when complete."""
        config = ProviderTypeConfig(
            type_name="test",
            required_credentials=["token_id", "token_secret"],
        )
        
        missing = config.validate_credentials({
            "token_id": "abc",
            "token_secret": "xyz"
        })
        
        assert len(missing) == 0
    
    def test_validate_config_missing(self):
        """Test config validation finds missing fields."""
        config = ProviderTypeConfig(
            type_name="test",
            required_config=["app_name", "region"],
        )
        
        missing = config.validate_config({"app_name": "test-app"})
        
        assert "region" in missing
    
    def test_build_env_vars_with_builder(self):
        """Test env var building with custom builder function."""
        def my_builder(credentials, config):
            return {
                "MY_TOKEN": credentials.get("token", ""),
                "MY_APP": config.get("app_name", ""),
            }
        
        config = ProviderTypeConfig(
            type_name="test",
            env_builder=my_builder,
        )
        
        env_vars = config.build_env_vars(
            {"token": "secret123"},
            {"app_name": "my-app"}
        )
        
        assert env_vars["MY_TOKEN"] == "secret123"
        assert env_vars["MY_APP"] == "my-app"
    
    def test_build_env_vars_no_builder(self):
        """Test env var building returns empty without builder."""
        config = ProviderTypeConfig(type_name="test")
        
        env_vars = config.build_env_vars({"token": "abc"}, {"app": "test"})
        
        assert env_vars == {}


class TestProviderRegistry:
    """Test ProviderRegistry class methods."""
    
    def test_register_provider_type(self):
        """Test registering a new provider type."""
        config = ProviderTypeConfig(
            type_name="custom_provider",
            required_credentials=["api_key"],
        )
        
        ProviderRegistry.register(config)
        
        assert ProviderRegistry.is_registered("custom_provider")
        assert ProviderRegistry.get("custom_provider") == config
    
    def test_get_unregistered(self):
        """Test getting unregistered provider returns None."""
        result = ProviderRegistry.get("nonexistent_provider")
        
        assert result is None
    
    def test_is_registered(self):
        """Test checking if provider type is registered."""
        # Modal should be registered on import
        assert ProviderRegistry.is_registered("modal") is True
        assert ProviderRegistry.is_registered("fake_provider") is False
    
    def test_get_all(self):
        """Test getting all registered provider types."""
        all_types = ProviderRegistry.get_all()
        
        assert isinstance(all_types, dict)
        assert "modal" in all_types  # Modal is auto-registered
    
    def test_build_container_env_modal(self):
        """Test building container env for Modal provider."""
        # Create a mock provider object
        class MockProvider:
            type = "modal"
            credentials = {
                "token_id": "ak-test123",
                "token_secret": "as-secretxyz",
                "username": "testuser"
            }
            config = {
                "app_name": "test-app"
            }
        
        env_vars = ProviderRegistry.build_container_env(MockProvider())
        
        assert env_vars.get("MODAL_TOKEN_ID") == "ak-test123"
        assert env_vars.get("MODAL_TOKEN_SECRET") == "as-secretxyz"
        assert env_vars.get("MODAL_USERNAME") == "testuser"
        assert env_vars.get("MODAL_APP_NAME") == "test-app"
    
    def test_build_container_env_unknown_type(self):
        """Test building container env for unknown provider returns empty."""
        class MockProvider:
            type = "unknown_provider_type"
            credentials = {}
            config = {}
        
        env_vars = ProviderRegistry.build_container_env(MockProvider())
        
        assert env_vars == {}
    
    def test_validate_provider(self):
        """Test validating provider credentials and config."""
        result = ProviderRegistry.validate_provider(
            "modal",
            {"token_id": "abc"},  # Missing token_secret and username
            {"app_name": "test"}   # Complete
        )
        
        assert "token_secret" in result["credentials"]
        assert "username" in result["credentials"]
        assert len(result["config"]) == 0  # Config is complete
    
    def test_get_worker_image(self):
        """Test getting worker image name."""
        assert ProviderRegistry.get_worker_image("modal") == "comfy-provider-image-worker:latest"
        assert ProviderRegistry.get_worker_image("beam") == "comfy-provider-image-worker:latest"
        assert ProviderRegistry.get_worker_image("unknown-provider") == "comfy-provider-unknown-provider:latest"
    
    def test_get_default_port(self):
        """Test getting default port."""
        port = ProviderRegistry.get_default_port("modal")
        
        assert port == 8000
    
    # ============================================
    # Beam Provider Tests
    # ============================================
    
    def test_beam_is_registered(self):
        """Test Beam provider auto-registers on import."""
        assert ProviderRegistry.is_registered("beam") is True
    
    def test_beam_in_get_all(self):
        """Test Beam appears in all registered providers."""
        all_types = ProviderRegistry.get_all()
        assert "beam" in all_types
    
    def test_build_container_env_beam(self):
        """Test building container env for Beam provider."""
        class MockProvider:
            type = "beam"
            credentials = {
                "api_key": "bm-test123",
                "workspace_id": "ws-456",
                "hf_token": "hf_abc",
                "civitai_token": "cv_xyz"
            }
            config = {
                "gpu_url": "https://comfy-gpu.app.beam.cloud",
                "storage_url": "https://comfy-storage.app.beam.cloud",
                "gpu_type": "RTX4090"
            }
        
        env_vars = ProviderRegistry.build_container_env(MockProvider())
        
        assert env_vars.get("BEAM_API_KEY") == "bm-test123"
        assert env_vars.get("BEAM_WORKSPACE_ID") == "ws-456"
        assert env_vars.get("BEAM_GPU_URL") == "https://comfy-gpu.app.beam.cloud"
        assert env_vars.get("BEAM_STORAGE_URL") == "https://comfy-storage.app.beam.cloud"
        assert env_vars.get("BEAM_GPU_TYPE") == "RTX4090"
        assert env_vars.get("HF_TOKEN") == "hf_abc"
        assert env_vars.get("CIVITAI_TOKEN") == "cv_xyz"
    
    def test_build_container_env_beam_minimal(self):
        """Test building container env for Beam with only required credentials."""
        class MockProvider:
            type = "beam"
            credentials = {"api_key": "bm-minimal"}
            config = {
                "gpu_url": "https://gpu.beam.cloud",
                "storage_url": "https://storage.beam.cloud"
            }
        
        env_vars = ProviderRegistry.build_container_env(MockProvider())
        
        assert env_vars.get("BEAM_API_KEY") == "bm-minimal"
        assert env_vars.get("BEAM_GPU_URL") == "https://gpu.beam.cloud"
        assert env_vars.get("BEAM_STORAGE_URL") == "https://storage.beam.cloud"
        assert "BEAM_WORKSPACE_ID" not in env_vars  # Optional, not provided
    
    def test_validate_beam_provider_credentials(self):
        """Test validating Beam provider credentials."""
        result = ProviderRegistry.validate_provider(
            "beam",
            {},  # Missing api_key
            {"gpu_url": "https://gpu.beam.cloud", "storage_url": "https://storage.beam.cloud"}
        )
        
        assert "api_key" in result["credentials"]
        assert len(result["config"]) == 0  # Config is complete
    
    def test_validate_beam_provider_config(self):
        """Test validating Beam provider config."""
        result = ProviderRegistry.validate_provider(
            "beam",
            {"api_key": "test-key"},
            {}  # Missing gpu_url and storage_url
        )
        
        assert len(result["credentials"]) == 0  # Credentials complete
        assert "gpu_url" in result["config"]
        assert "storage_url" in result["config"]
    
    def test_get_beam_image_worker(self):
        """Test getting worker image name for Beam."""
        image = ProviderRegistry.get_worker_image("beam")
        
        assert "image-worker" in image
    
    def test_get_beam_default_port(self):
        """Test getting default port for Beam."""
        port = ProviderRegistry.get_default_port("beam")
        
        assert port == 8000


class TestLLMProviderAliasesAndStubs:
    """LLM provider types are API-backed: aliases resolve to real client
    classes and file-oriented abstract methods degrade gracefully."""

    @pytest.mark.parametrize("type_name,expected_client", [
        ("openai", "OpenAICompatProvider"),
        ("ollama", "OpenAICompatProvider"),
        ("gemini", "GoogleProvider"),
        ("google", "GoogleProvider"),
        ("anthropic", "AnthropicProvider"),
        ("openai_compat", "OpenAICompatProvider"),
    ])
    def test_llm_types_are_registered_and_instantiable(self, type_name, expected_client):
        from infrastructure.providers import create_provider_client
        client = create_provider_client("p-test", {"type": type_name, "api_base": "http://x/v1"})
        assert type(client).__name__ == expected_client

    @pytest.mark.parametrize("type_name", ["openai", "ollama", "gemini", "google", "anthropic", "openai_compat"])
    def test_llm_file_ops_raise_informative_error(self, type_name):
        from core.exceptions import ProviderError
        from infrastructure.providers import create_provider_client
        client = create_provider_client("p-test", {"type": type_name, "api_base": "http://x/v1"})
        with pytest.raises(ProviderError, match="LLM API provider"):
            client.get_file_proxy()
        with pytest.raises(ProviderError, match="LLM API provider"):
            asyncio.run(client.list_models("models"))
        with pytest.raises(ProviderError, match="LLM API provider"):
            asyncio.run(client.delete_model("models/x.safetensors"))
        with pytest.raises(ProviderError, match="LLM API provider"):
            asyncio.run(client.download_model("http://x", "models/x.safetensors"))

    def test_openai_alias_env_builder(self):
        from infrastructure.providers.provider_registry import ProviderRegistry
        config = ProviderRegistry.get("openai")
        env = config.build_env_vars({"api_key": "sk-test"}, {"id": "p1", "api_base": "https://api.openai.com/v1"})
        assert env["ENGINE"] == "openai_compat"
        assert env["OPENAI_API_BASE"] == "https://api.openai.com/v1"
        assert env["OPENAI_API_KEY"] == "sk-test"

    def test_gemini_alias_env_builder(self):
        from infrastructure.providers.provider_registry import ProviderRegistry
        config = ProviderRegistry.get("gemini")
        env = config.build_env_vars({"api_key": "g-123"}, {"id": "p1"})
        assert env["ENGINE"] == "google"
        assert env["GOOGLE_API_KEY"] == "g-123"
