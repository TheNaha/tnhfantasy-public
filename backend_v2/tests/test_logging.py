"""Tests for infrastructure/logging.py"""
from infrastructure.logging import (
    Colors,
    api_logger,
    cache_logger,
    compact_renderer,
    config_logger,
    configure_logging,
    db_logger,
    download_logger,
    get_logger,
    http_logger,
    job_logger,
    model_logger,
    provider_logger,
    scheduler_logger,
    ws_logger,
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

    def test_cache_logger(self):
        logger = cache_logger()
        assert logger is not None

    def test_db_logger(self):
        logger = db_logger()
        assert logger is not None

    def test_scheduler_logger(self):
        logger = scheduler_logger()
        assert logger is not None

    def test_http_logger(self):
        logger = http_logger()
        assert logger is not None

    def test_config_logger(self):
        logger = config_logger()
        assert logger is not None

    def test_ws_logger(self):
        logger = ws_logger()
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
        assert Colors.MAGENTA is not None
        assert Colors.BOLD is not None


def _render(extra: dict) -> str:
    """Render one log line through the app's renderer.

    Called from inside an `except` block so `exc_info=True` resolves to the
    active exception, exactly as it does at a real call site.
    """
    event = {
        "timestamp": "2024-01-15 00:00:00",
        "level": "error",
        "event": "unhandled",
    }
    event.update(extra)
    return compact_renderer(None, "error", event)


VOLUMINOUS_REPR_CALLS = []


class TestExceptionRenderingIsBounded:
    """The 22-second-500 bug, pinned.

    `configure_logging()` used to be called only from the FastAPI lifespan, but a
    structlog proxy binds its processor chain on FIRST USE and never rebinds. So
    every module-level `logger = get_logger(...)` — which is most of the
    codebase — captured structlog's DEFAULT chain, ending in `ConsoleRenderer`
    instead of this module's `compact_renderer`. `ConsoleRenderer` hands
    `exc_info` to `RichTracebackFormatter`, which pretty-prints the LOCALS of
    every frame. `rich` is importable here because `modal` depends on it.

    The symptom: an unhandled exception in a request handler took ~22s to
    become a 500, on the event loop, printing nothing readable. A frame holding
    a SQLAlchemy Session/Connection is an unbounded object graph to walk.
    """

    def test_a_fresh_logger_uses_this_modules_renderer(self):
        configure_logging()
        logger = get_logger("test_bounded")
        last = logger._processors[-1]
        assert last is compact_renderer, (
            "a logger created now must bind compact_renderer; getting "
            f"{last!r} means configure_logging() is not running at import time, "
            "and every exc_info=True log will go through rich's locals renderer"
        )

    def test_a_module_level_logger_is_not_bound_to_the_structlog_default(self):
        # `api.error_handlers` creates its logger at import, exactly like most
        # service modules. This is the logger whose 500 took 22 seconds.
        from api import error_handlers

        assert error_handlers.logger._processors[-1] is compact_renderer

    def test_rendering_an_exception_produces_a_traceback(self):
        configure_logging()
        try:
            raise ValueError("boom")
        except ValueError:
            line = _render({"exc_info": True})
        assert "Traceback (most recent call last):" in line
        assert "ValueError: boom" in line
        # The frame is identified, but its LOCALS are not rendered — that is
        # the whole difference between this and `ConsoleRenderer`.
        assert "test_rendering_an_exception_produces_a_traceback" in line

    def test_rendering_is_bounded_when_a_frame_local_is_huge(self):
        """A frame local that expands into a large object graph must not be
        rendered, and must not be walked to find out how large it is."""

        class Voluminous:
            def __init__(self, depth=0):
                # A WIDE, shallow, self-referential graph — the shape of a live
                # DB session's internals, which is what a real handler frame
                # holds. `rich`'s pretty printer would walk all of it.
                self.parent = self
                self.children = (
                    [Voluminous(depth + 1) for _ in range(200)] if depth < 2 else []
                )

            def __repr__(self):
                VOLUMINOUS_REPR_CALLS.append(1)
                return f"<Voluminous {len(self.children)} children>"

        def _raiser(thing):
            raise RuntimeError("carrying a heavy frame local")

        configure_logging()
        del VOLUMINOUS_REPR_CALLS[:]
        try:
            _raiser(Voluminous())
        except RuntimeError:
            line = _render({"exc_info": True})

        assert "RuntimeError: carrying a heavy frame local" in line
        # The SOURCE line of the call site legitimately mentions the class; what
        # must not appear is the object's expanded repr, which is what
        # `RichTracebackFormatter` would walk the object graph to produce.
        assert "<Voluminous 200 children>" not in line, (
            "frame locals must not be rendered"
        )
        # How many times the object's `__repr__` fired — the direct, load-
        # independent measure of whether the formatter walked the object graph.
        #
        # This used to be a wall-clock ceiling of 2.0s, on the reasoning that the
        # buggy path cost ~22s and a correct render is sub-millisecond. It failed
        # at 5.23s under a loaded event loop while passing in isolation in 18s
        # for the whole file, which is exactly what a time-based assertion about
        # CPU-bound work on a shared machine does. The repr count says the same
        # thing without reference to how busy the machine is.
        assert len(VOLUMINOUS_REPR_CALLS) == 0, (
            f"the formatter repr'd a frame-local object "
            f"{len(VOLUMINOUS_REPR_CALLS)} times; it must not walk locals"
        )

    def test_a_very_deep_traceback_is_truncated(self):
        from infrastructure.logging import MAX_TRACEBACK_FRAMES

        def _recurse(n):
            if n:
                return _recurse(n - 1)
            raise IndexError("bottom")

        configure_logging()
        try:
            _recurse(MAX_TRACEBACK_FRAMES * 3)
        except IndexError:
            line = _render({"exc_info": True})
        assert "earlier frame(s) omitted" in line
        assert line.count("_recurse") <= MAX_TRACEBACK_FRAMES + 2

    def test_a_bare_exception_is_accepted(self):
        exc = ValueError("bare")
        line = _render({"exc_info": exc})
        assert "ValueError: bare" in line

    def test_a_sys_exc_info_tuple_is_accepted(self):
        try:
            raise KeyError("tupled")
        except KeyError:
            payload = __import__("sys").exc_info()
        assert "KeyError: 'tupled'" in _render({"exc_info": payload})

