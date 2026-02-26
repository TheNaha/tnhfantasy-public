"""Tests for infrastructure/logging.py"""
import logging
import pytest
import structlog
from infrastructure.logging import (
    configure_logging,
    get_logger,
    job_logger,
    provider_logger,
    model_logger,
    download_logger,
    api_logger,
    compact_renderer,
    Colors,
)


class TestGetLogger:
    def test_get_logger_returns_bound_logger(self):
        logger = get_logger("test")
        assert logger is not None

    def test_get_logger_without_name(self):
        logger = get_logger()
        assert logger is not None

    def test_get_logger_with_name(self):
        logger = get_logger("my_module")
        assert logger is not None

    def test_logger_can_log_info(self):
        logger = get_logger("test_info")
        # Should not raise
        logger.info("test_message", extra_key="value")

    def test_logger_can_log_error(self):
        logger = get_logger("test_error")
        logger.error("test_error_message", error="some error")

    def test_logger_can_log_warning(self):
        logger = get_logger("test_warning")
        logger.warning("test_warning_message")

    def test_logger_can_log_debug(self):
        logger = get_logger("test_debug")
        logger.debug("test_debug_message")


class TestConvenienceLoggers:
    def test_job_logger(self):
        logger = job_logger()
        assert logger is not None

    def test_provider_logger(self):
        logger = provider_logger()
        assert logger is not None

    def test_model_logger(self):
        logger = model_logger()
        assert logger is not None

    def test_download_logger(self):
        logger = download_logger()
        assert logger is not None

    def test_api_logger(self):
        logger = api_logger()
        assert logger is not None


class TestConfigureLogging:
    def test_configure_default(self):
        # Should not raise
        configure_logging()

    def test_configure_with_debug(self):
        configure_logging(log_level="DEBUG")

    def test_configure_with_json_format(self):
        configure_logging(json_format=True)
        # Reset to default format
        configure_logging()

    def test_configure_with_custom_timestamp(self):
        configure_logging(timestamp_fmt="%H:%M:%S")

    def test_configure_with_warning_level(self):
        configure_logging(log_level="WARNING")
        # Reset
        configure_logging()


class TestCompactRenderer:
    def test_basic_message(self):
        event_dict = {
            "timestamp": "2024-01-15 10:30:00",
            "level": "info",
            "event": "test_event",
            "logger_name": "test"
        }
        result = compact_renderer(None, "info", event_dict)
        assert "test_event" in result

    def test_with_key_values(self):
        event_dict = {
            "timestamp": "2024-01-15",
            "level": "info",
            "event": "http_request",
            "status_code": 200,
            "method": "GET",
            "path": "/api/test"
        }
        result = compact_renderer(None, "info", event_dict)
        assert "http_request" in result
        assert "/api/test" in result

    def test_with_duration_ms(self):
        event_dict = {
            "timestamp": "2024-01-15",
            "level": "info",
            "event": "slow_request",
            "duration_ms": 123
        }
        result = compact_renderer(None, "info", event_dict)
        assert "123ms" in result

    def test_error_level(self):
        event_dict = {
            "timestamp": "2024-01-15",
            "level": "error",
            "event": "error_event"
        }
        result = compact_renderer(None, "error", event_dict)
        assert "error_event" in result

    def test_warning_level(self):
        event_dict = {
            "timestamp": "2024-01-15",
            "level": "warning",
            "event": "warning_event"
        }
        result = compact_renderer(None, "warning", event_dict)
        assert "warning_event" in result

    def test_skips_private_keys(self):
        event_dict = {
            "timestamp": "2024-01-15",
            "level": "info",
            "event": "my_event",
            "_internal_key": "should_not_appear"
        }
        result = compact_renderer(None, "info", event_dict)
        assert "_internal_key" not in result

    def test_no_timestamp(self):
        event_dict = {
            "level": "info",
            "event": "no_ts_event"
        }
        result = compact_renderer(None, "info", event_dict)
        assert "no_ts_event" in result

    def test_empty_event_dict(self):
        event_dict = {
            "level": "info",
            "event": "empty"
        }
        result = compact_renderer(None, "info", event_dict)
        assert "empty" in result

    def test_status_code_500_renders(self):
        event_dict = {
            "timestamp": "2024-01-15",
            "level": "error",
            "event": "server_error",
            "status_code": 500
        }
        result = compact_renderer(None, "error", event_dict)
        assert "500" in result

    def test_request_id_renders(self):
        event_dict = {
            "timestamp": "2024-01-15",
            "level": "info",
            "event": "request",
            "request_id": "abc123"
        }
        result = compact_renderer(None, "info", event_dict)
        assert "abc123" in result

    def test_generic_key_value(self):
        event_dict = {
            "timestamp": "2024-01-15",
            "level": "info",
            "event": "custom_event",
            "my_key": "my_value"
        }
        result = compact_renderer(None, "info", event_dict)
        assert "my_key=my_value" in result


class TestColors:
    def test_colors_exist(self):
        assert Colors.RESET is not None
        assert Colors.GREEN is not None
        assert Colors.RED is not None
        assert Colors.YELLOW is not None
        assert Colors.GRAY is not None
        assert Colors.CYAN is not None
        assert Colors.MAGENTA is not None
        assert Colors.BOLD is not None
