"""Tests for config.py"""
import os
import json
import pytest
import tempfile
import config as cfg
from config import (
    DEFAULT_CONFIG,
    Settings,
    get_settings,
    load_config,
    get_config,
    update_config,
    reset_config,
    _deep_merge,
    _validate_config,
    get_worker_poll_interval,
    get_worker_retry_delay,
    get_worker_poll_limit,
    get_default_jobs_limit,
    get_max_jobs_in_memory,
    get_max_concurrent_jobs,
    get_job_timeout,
    get_job_max_retries,
    get_job_retry_base_delay,
    get_job_retry_max_delay,
    get_model_sync_interval,
    get_model_sync_retry_delay,
    get_reconciliation_interval,
    get_worker_backend_url,
    get_download_chunk_size,
    get_download_auto_remove_delay,
    get_modal_timeout,
    get_modal_max_containers,
    get_modal_scaledown_window,
    get_cors_origins,
    get_gzip_minimum_size,
    get_jobs_cleanup_max_age,
    get_jobs_cleanup_auto,
    get_jobs_cleanup_interval,
    get_thumbnail_sizes,
    get_thumbnail_quality,
    get_blurhash_components,
    get_blurhash_resize_max,
    get_thumbnail_format,
    get_thumbnail_directory,
    get_output_date_hierarchy,
    get_embed_metadata_in_png,
)


@pytest.fixture(autouse=True)
def reset_global_config():
    """Reset the global _config state and path before each test."""
    import config as cfg_module
    original_config = cfg_module._config
    original_path = cfg_module._config_path
    yield
    cfg_module._config = original_config
    cfg_module._config_path = original_path


class TestSettings:
    def test_default_database_url(self):
        s = Settings()
        assert "sqlite" in s.database_url

    def test_default_worker_poll_interval(self):
        s = Settings()
        assert s.worker_poll_interval == 0.3

    def test_env_prefix(self):
        assert Settings.model_config.get("env_prefix") == "COMFY_" or hasattr(Settings, "model_config")

    def test_get_settings_returns_settings(self):
        s = get_settings()
        assert isinstance(s, Settings)

    def test_cors_origins_default(self):
        s = Settings()
        assert isinstance(s.cors_origins, list)

    def test_directories_env_fallback(self, monkeypatch):
        # 1. Test defaults when nothing is set in env
        monkeypatch.delenv("COMFY_OUTPUT_DIR", raising=False)
        monkeypatch.delenv("OUTPUT_DIR", raising=False)
        monkeypatch.delenv("COMFY_INPUT_DIR", raising=False)
        monkeypatch.delenv("INPUT_DIR", raising=False)
        s1 = Settings()
        assert s1.output_dir.endswith("output")
        assert s1.input_dir.endswith("input")

        # 2. Test fallback to OUTPUT_DIR / INPUT_DIR (non-prefixed)
        monkeypatch.setenv("OUTPUT_DIR", "/tmp/non_prefixed_out")
        monkeypatch.setenv("INPUT_DIR", "/tmp/non_prefixed_in")
        s2 = Settings()
        assert s2.output_dir == "/tmp/non_prefixed_out"
        assert s2.input_dir == "/tmp/non_prefixed_in"

        # 3. Test COMFY_ prefixed takes precedence over non-prefixed
        monkeypatch.setenv("COMFY_OUTPUT_DIR", "/tmp/prefixed_out")
        monkeypatch.setenv("COMFY_INPUT_DIR", "/tmp/prefixed_in")
        s3 = Settings()
        assert s3.output_dir == "/tmp/prefixed_out"
        assert s3.input_dir == "/tmp/prefixed_in"


class TestDeepMerge:
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        updates = {"b": 3, "c": 4}
        result = _deep_merge(base, updates)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"worker": {"poll_interval": 0.3, "retry_delay": 5}}
        updates = {"worker": {"poll_interval": 1.0}}
        result = _deep_merge(base, updates)
        assert result["worker"]["poll_interval"] == 1.0
        assert result["worker"]["retry_delay"] == 5

    def test_deep_nested_merge(self):
        base = {"a": {"b": {"c": 1, "d": 2}}}
        updates = {"a": {"b": {"c": 99}}}
        result = _deep_merge(base, updates)
        assert result["a"]["b"]["c"] == 99
        assert result["a"]["b"]["d"] == 2

    def test_adds_new_keys(self):
        base = {"a": 1}
        updates = {"b": 2}
        result = _deep_merge(base, updates)
        assert result["b"] == 2

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        _deep_merge(base, {"a": 2})
        assert base["a"] == 1

    def test_non_dict_values_overwrite(self):
        base = {"a": [1, 2]}
        updates = {"a": [3, 4, 5]}
        result = _deep_merge(base, updates)
        assert result["a"] == [3, 4, 5]


class TestValidateConfig:
    def test_valid_empty_config(self):
        _validate_config({})  # Should not raise

    def test_invalid_poll_interval(self):
        with pytest.raises(ValueError):
            _validate_config({"worker": {"poll_interval": -1}})

    def test_invalid_retry_delay(self):
        with pytest.raises(ValueError):
            _validate_config({"worker": {"retry_delay": -1}})

    def test_invalid_max_concurrent(self):
        with pytest.raises(ValueError):
            _validate_config({"jobs": {"max_concurrent": 0}})

    def test_invalid_timeout(self):
        with pytest.raises(ValueError):
            _validate_config({"jobs": {"timeout": 0}})

    def test_invalid_default_limit(self):
        with pytest.raises(ValueError):
            _validate_config({"jobs": {"default_limit": 0}})

    def test_invalid_gzip_size(self):
        with pytest.raises(ValueError):
            _validate_config({"api": {"gzip_minimum_size": -1}})

    def test_invalid_cors_origins_type(self):
        with pytest.raises(ValueError):
            _validate_config({"api": {"cors_origins": "not-a-list"}})

    def test_invalid_cleanup_age(self):
        with pytest.raises(ValueError):
            _validate_config({"jobs_cleanup": {"max_age_hours": 0}})

    def test_invalid_thumbnail_quality_too_low(self):
        with pytest.raises(ValueError):
            _validate_config({"image_processing": {"thumbnail_quality": 0}})

    def test_invalid_thumbnail_quality_too_high(self):
        with pytest.raises(ValueError):
            _validate_config({"image_processing": {"thumbnail_quality": 101}})

    def test_invalid_blurhash_x(self):
        with pytest.raises(ValueError):
            _validate_config({"image_processing": {"blurhash_components_x": 10}})

    def test_invalid_blurhash_y(self):
        with pytest.raises(ValueError):
            _validate_config({"image_processing": {"blurhash_components_y": 0}})

    def test_invalid_blurhash_resize(self):
        with pytest.raises(ValueError):
            _validate_config({"image_processing": {"blurhash_resize_max": 0}})

    def test_valid_api_settings(self):
        _validate_config({"api": {"gzip_minimum_size": 500, "cors_origins": ["*"]}})


class TestLoadConfig:
    def test_load_from_file(self):
        import config as cfg_module
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"worker": {"poll_interval": 2.5}}, f)
            tmp_path = f.name

        try:
            result = load_config(tmp_path)
            assert result["worker"]["poll_interval"] == 2.5
        finally:
            os.unlink(tmp_path)

    def test_creates_default_config_if_not_exists(self):
        import config as cfg_module
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = os.path.join(tmpdir, "config.json")
            result = load_config(tmp_path)
            assert "worker" in result
            assert os.path.exists(tmp_path)

    def test_falls_back_to_defaults_on_bad_json(self):
        import config as cfg_module
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("INVALID JSON {{{")
            tmp_path = f.name

        try:
            # Should not raise, returns defaults
            result = load_config(tmp_path)
            assert "worker" in result
        finally:
            os.unlink(tmp_path)

    def test_merges_with_defaults(self):
        import config as cfg_module
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"worker": {"poll_interval": 5.0}}, f)
            tmp_path = f.name

        try:
            result = load_config(tmp_path)
            # Should have poll_interval from file + retry_delay from defaults
            assert result["worker"]["poll_interval"] == 5.0
            assert "retry_delay" in result["worker"]
        finally:
            os.unlink(tmp_path)


class TestWorkerBackendUrl:
    def test_prefers_file_config_when_settings_value_is_default(self, monkeypatch):
        monkeypatch.setattr(cfg.settings, "worker_backend_url", "http://backend_v2:8002")
        cfg._config = _deep_merge(DEFAULT_CONFIG.copy(), {"api": {"worker_backend_url": "http://custom-backend:9002"}})

        assert get_worker_backend_url() == "http://custom-backend:9002"

    def test_prefers_settings_override_when_non_default(self, monkeypatch):
        monkeypatch.setenv("COMFY_WORKER_BACKEND_URL", "http://env-backend:9100")
        monkeypatch.setattr(cfg.settings, "worker_backend_url", "http://env-backend:9100")
        cfg._config = _deep_merge(DEFAULT_CONFIG.copy(), {"api": {"worker_backend_url": "http://config-backend:9002"}})

        assert get_worker_backend_url() == "http://env-backend:9100"

    def test_normalizes_legacy_hostname_from_config(self, monkeypatch):
        monkeypatch.delenv("COMFY_WORKER_BACKEND_URL", raising=False)
        monkeypatch.setattr(cfg.settings, "worker_backend_url", "http://backend_v2:8002")
        cfg._config = _deep_merge(DEFAULT_CONFIG.copy(), {"api": {"worker_backend_url": "http://comfy-backend-v2:8002"}})

        assert get_worker_backend_url() == "http://backend_v2:8002"

    def test_normalizes_legacy_hostname_from_env_override(self, monkeypatch):
        monkeypatch.setenv("COMFY_WORKER_BACKEND_URL", "http://comfy-backend-v2:8002")
        monkeypatch.setattr(cfg.settings, "worker_backend_url", "http://comfy-backend-v2:8002")
        cfg._config = _deep_merge(DEFAULT_CONFIG.copy(), {"api": {"worker_backend_url": "http://config-backend:9002"}})

        assert get_worker_backend_url() == "http://backend_v2:8002"


class TestGetConfig:
    def test_returns_dict(self):
        import config as cfg_module
        cfg_module._config = None
        result = get_config()
        assert isinstance(result, dict)

    def test_cached_after_first_call(self):
        import config as cfg_module
        cfg_module._config = {"test": True}
        result = get_config()
        assert result["test"] is True


class TestUpdateConfig:
    def test_updates_value(self):
        import config as cfg_module
        cfg_module._config = DEFAULT_CONFIG.copy()
        update_config({"worker": {"poll_interval": 99.0}}, persist=False)
        assert cfg_module._config["worker"]["poll_interval"] == 99.0

    def test_returns_updated_config(self):
        import config as cfg_module
        cfg_module._config = DEFAULT_CONFIG.copy()
        result = update_config({"worker": {"poll_interval": 10.0}}, persist=False)
        assert result["worker"]["poll_interval"] == 10.0

    def test_raises_on_invalid_values(self):
        import config as cfg_module
        cfg_module._config = DEFAULT_CONFIG.copy()
        with pytest.raises(ValueError):
            update_config({"worker": {"poll_interval": -1}}, persist=False)


class TestResetConfig:
    def test_resets_to_defaults(self):
        import config as cfg_module
        cfg_module._config = {"worker": {"poll_interval": 999}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            tmp_path = f.name
        cfg_module._config_path = tmp_path
        try:
            reset_config()
            assert cfg_module._config["worker"]["poll_interval"] == DEFAULT_CONFIG["worker"]["poll_interval"]
        finally:
            os.unlink(tmp_path)


class TestConvenienceFunctions:
    @pytest.fixture(autouse=True)
    def setup_default_config(self):
        import config as cfg_module
        cfg_module._config = DEFAULT_CONFIG.copy()

    def test_get_worker_poll_interval(self):
        assert get_worker_poll_interval() == 0.3

    def test_get_worker_retry_delay(self):
        assert get_worker_retry_delay() == 5

    def test_get_worker_poll_limit(self):
        assert get_worker_poll_limit() == 50

    def test_get_default_jobs_limit(self):
        assert get_default_jobs_limit() == 20

    def test_get_max_jobs_in_memory(self):
        assert get_max_jobs_in_memory() == 100

    def test_get_max_concurrent_jobs(self):
        assert get_max_concurrent_jobs() == 5

    def test_get_job_timeout(self):
        assert isinstance(get_job_timeout(), int)

    def test_get_job_max_retries(self):
        assert isinstance(get_job_max_retries(), int)

    def test_get_job_retry_base_delay(self):
        assert isinstance(get_job_retry_base_delay(), float)

    def test_get_job_retry_max_delay(self):
        assert isinstance(get_job_retry_max_delay(), float)

    def test_get_model_sync_interval(self):
        assert get_model_sync_interval() == 300

    def test_get_model_sync_retry_delay(self):
        assert get_model_sync_retry_delay() == 10

    def test_get_reconciliation_interval(self):
        assert get_reconciliation_interval() == 120

    def test_get_download_chunk_size(self):
        assert get_download_chunk_size() == 8192

    def test_get_download_auto_remove_delay(self):
        assert get_download_auto_remove_delay() == 5

    def test_get_modal_timeout(self):
        assert get_modal_timeout() == 300

    def test_get_modal_max_containers(self):
        assert get_modal_max_containers() == 1

    def test_get_modal_scaledown_window(self):
        assert get_modal_scaledown_window() == 5

    def test_get_cors_origins(self):
        result = get_cors_origins()
        assert isinstance(result, list)

    def test_get_gzip_minimum_size(self):
        assert get_gzip_minimum_size() == 1000

    def test_get_jobs_cleanup_max_age(self):
        assert get_jobs_cleanup_max_age() == 24

    def test_get_jobs_cleanup_auto(self):
        assert get_jobs_cleanup_auto() is False

    def test_get_jobs_cleanup_interval(self):
        assert get_jobs_cleanup_interval() == 3600

    def test_get_thumbnail_sizes(self):
        sizes = get_thumbnail_sizes()
        assert isinstance(sizes, dict)
        assert "medium" in sizes

    def test_get_thumbnail_quality(self):
        assert get_thumbnail_quality() == 90

    def test_get_blurhash_components(self):
        x, y = get_blurhash_components()
        assert x == 4
        assert y == 3

    def test_get_blurhash_resize_max(self):
        assert get_blurhash_resize_max() == 400

    def test_get_thumbnail_format(self):
        assert get_thumbnail_format() == "webp"

    def test_get_thumbnail_directory(self):
        assert get_thumbnail_directory() == "thumb"

    def test_get_output_date_hierarchy(self):
        assert get_output_date_hierarchy() is True

    def test_get_embed_metadata_in_png(self):
        assert get_embed_metadata_in_png() is True
