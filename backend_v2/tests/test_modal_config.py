import pytest
from infrastructure.providers.modal_config import build_modal_env_vars

def test_build_modal_env_vars_empty():
    """Test with empty credentials and config."""
    result = build_modal_env_vars({}, {})
    assert result == {}

def test_build_modal_env_vars_full_credentials():
    """Test with all credentials and config present."""
    credentials = {
        "token_id": "test_token_id",
        "token_secret": "test_token_secret",
        "username": "test_user"
    }
    config = {
        "app_name": "test_app"
    }

    result = build_modal_env_vars(credentials, config)

    assert result == {
        "MODAL_TOKEN_ID": "test_token_id",
        "MODAL_TOKEN_SECRET": "test_token_secret",
        "MODAL_USERNAME": "test_user",
        "MODAL_APP_NAME": "test_app"
    }

def test_build_modal_env_vars_partial_credentials():
    """Test with partial credentials."""
    credentials = {
        "token_id": "test_token_id"
    }
    config = {}

    result = build_modal_env_vars(credentials, config)

    assert result == {
        "MODAL_TOKEN_ID": "test_token_id"
    }

def test_build_modal_env_vars_memory_snapshot_true():
    """Test with enable_memory_snapshot set to True."""
    credentials = {}
    config = {
        "enable_memory_snapshot": True
    }

    result = build_modal_env_vars(credentials, config)

    assert result == {
        "ENABLE_MEMORY_SNAPSHOT": "true"
    }

def test_build_modal_env_vars_memory_snapshot_false():
    """Test with enable_memory_snapshot set to False."""
    credentials = {}
    config = {
        "enable_memory_snapshot": False
    }

    result = build_modal_env_vars(credentials, config)

    assert result == {
        "ENABLE_MEMORY_SNAPSHOT": "false"
    }

def test_build_modal_env_vars_ignores_unknown_keys():
    """Test that unknown keys in credentials and config are ignored."""
    credentials = {
        "token_id": "test_token_id",
        "unknown_cred": "should_be_ignored"
    }
    config = {
        "app_name": "test_app",
        "unknown_config": "should_be_ignored"
    }

    result = build_modal_env_vars(credentials, config)

    assert result == {
        "MODAL_TOKEN_ID": "test_token_id",
        "MODAL_APP_NAME": "test_app"
    }

def test_modal_provider_config_structure():
    """Test that MODAL_PROVIDER_CONFIG is structured correctly."""
    from infrastructure.providers.modal_config import MODAL_PROVIDER_CONFIG, build_modal_env_vars
    from infrastructure.providers.provider_registry import ProviderTypeConfig

    assert isinstance(MODAL_PROVIDER_CONFIG, ProviderTypeConfig)
    assert MODAL_PROVIDER_CONFIG.type_name == "modal"

    # Check credentials
    assert "token_id" in MODAL_PROVIDER_CONFIG.required_credentials
    assert "token_secret" in MODAL_PROVIDER_CONFIG.required_credentials
    assert "username" in MODAL_PROVIDER_CONFIG.required_credentials

    # Check config
    assert "app_name" in MODAL_PROVIDER_CONFIG.required_config
    assert "enable_memory_snapshot" in MODAL_PROVIDER_CONFIG.optional_config

    # Check builder func mapping
    assert MODAL_PROVIDER_CONFIG.env_builder is build_modal_env_vars

    # Check other properties
    assert MODAL_PROVIDER_CONFIG.worker_image == "comfy-provider-modal"
    assert MODAL_PROVIDER_CONFIG.default_port == 8000
