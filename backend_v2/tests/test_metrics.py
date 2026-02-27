"""Tests for infrastructure/metrics.py - Prometheus metrics"""
import pytest
from infrastructure.metrics import (
    metrics,
    MetricsManager,
    REGISTRY,
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    JOBS_CREATED_TOTAL,
    JOBS_COMPLETED_TOTAL,
    JOBS_QUEUE_SIZE,
    JOBS_ACTIVE,
    PROVIDER_REQUESTS_TOTAL,
    CACHE_HITS_TOTAL,
    CACHE_MISSES_TOTAL,
    CACHE_SIZE,
    DB_OPERATIONS_TOTAL,
    DOWNLOADS_TOTAL,
    DOWNLOADS_ACTIVE,
    MODELS_TOTAL,
    WEBSOCKET_CONNECTIONS,
    SCHEDULER_TASKS_TOTAL,
    APP_INFO,
)


class TestMetricsManager:
    def test_singleton_exists(self):
        assert metrics is not None
        assert isinstance(metrics, MetricsManager)

    def test_track_request(self):
        # Should not raise
        metrics.track_request("GET", "/api/jobs", 200, 0.05)

    def test_track_request_different_methods(self):
        metrics.track_request("POST", "/api/jobs", 201, 0.1)
        metrics.track_request("DELETE", "/api/jobs/1", 204, 0.02)

    def test_track_job_created(self):
        metrics.track_job_created()

    def test_track_job_completed(self):
        metrics.track_job_completed("completed", duration=30.5)

    def test_track_job_completed_failed(self):
        metrics.track_job_completed("failed")

    def test_set_queue_size(self):
        metrics.set_queue_size(5)

    def test_set_active_jobs(self):
        metrics.set_active_jobs(2)

    def test_track_provider_request(self):
        metrics.track_provider_request("modal-1", "success", duration=1.5)

    def test_track_provider_failure(self):
        metrics.track_provider_failure("modal-1", "timeout")

    def test_track_cache_hit(self):
        metrics.track_cache_hit("stats")

    def test_track_cache_miss(self):
        metrics.track_cache_miss("model")

    def test_set_cache_size(self):
        metrics.set_cache_size("stats", 10)

    def test_track_db_operation(self):
        metrics.track_db_operation("query", duration=0.005)

    def test_track_db_error(self):
        metrics.track_db_error("insert")

    def test_track_download(self):
        metrics.track_download("started")
        metrics.track_download("completed")
        metrics.track_download("failed")

    def test_set_active_downloads(self):
        metrics.set_active_downloads(3)

    def test_set_models_total(self):
        metrics.set_models_total(42)

    def test_track_model_sync(self):
        metrics.track_model_sync("success")
        metrics.track_model_sync("failure")

    def test_set_websocket_connections(self):
        metrics.set_websocket_connections(5)

    def test_track_scheduler_task(self):
        metrics.track_scheduler_task("cleanup", "success")
        metrics.track_scheduler_task("vacuum", "failure")


class TestMetricsOutput:
    def test_generate_metrics_returns_bytes(self):
        output = metrics.generate_metrics()
        assert isinstance(output, bytes)
        assert len(output) > 0

    def test_generate_metrics_contains_app_info(self):
        output = metrics.generate_metrics().decode("utf-8")
        assert "app_info" in output
        assert "tnhcomfy" in output

    def test_generate_metrics_contains_http_metrics(self):
        metrics.track_request("GET", "/test", 200, 0.01)
        output = metrics.generate_metrics().decode("utf-8")
        assert "http_requests_total" in output

    def test_generate_metrics_contains_job_metrics(self):
        metrics.track_job_created()
        output = metrics.generate_metrics().decode("utf-8")
        assert "jobs_created_total" in output

    def test_generate_metrics_contains_cache_metrics(self):
        metrics.track_cache_hit("test_cache")
        output = metrics.generate_metrics().decode("utf-8")
        assert "cache_hits_total" in output

    def test_get_content_type(self):
        ct = metrics.get_content_type()
        assert "text/plain" in ct or "openmetrics" in ct


class TestPrometheusCounters:
    def test_http_requests_counter_exists(self):
        assert HTTP_REQUESTS_TOTAL is not None

    def test_jobs_created_counter_exists(self):
        assert JOBS_CREATED_TOTAL is not None

    def test_provider_requests_counter_exists(self):
        assert PROVIDER_REQUESTS_TOTAL is not None

    def test_cache_counters_exist(self):
        assert CACHE_HITS_TOTAL is not None
        assert CACHE_MISSES_TOTAL is not None

    def test_db_operations_counter_exists(self):
        assert DB_OPERATIONS_TOTAL is not None

    def test_downloads_counter_exists(self):
        assert DOWNLOADS_TOTAL is not None

    def test_scheduler_tasks_counter_exists(self):
        assert SCHEDULER_TASKS_TOTAL is not None


class TestPrometheusGauges:
    def test_queue_size_gauge_exists(self):
        assert JOBS_QUEUE_SIZE is not None

    def test_active_jobs_gauge_exists(self):
        assert JOBS_ACTIVE is not None

    def test_cache_size_gauge_exists(self):
        assert CACHE_SIZE is not None

    def test_downloads_active_gauge_exists(self):
        assert DOWNLOADS_ACTIVE is not None

    def test_models_total_gauge_exists(self):
        assert MODELS_TOTAL is not None

    def test_websocket_connections_gauge_exists(self):
        assert WEBSOCKET_CONNECTIONS is not None


class TestPrometheusHistograms:
    def test_http_duration_histogram_exists(self):
        assert HTTP_REQUEST_DURATION_SECONDS is not None

    def test_provider_duration_histogram_exists(self):
        from infrastructure.metrics import PROVIDER_REQUEST_DURATION_SECONDS
        assert PROVIDER_REQUEST_DURATION_SECONDS is not None

    def test_db_duration_histogram_exists(self):
        from infrastructure.metrics import DB_OPERATION_DURATION_SECONDS
        assert DB_OPERATION_DURATION_SECONDS is not None

    def test_job_duration_histogram_exists(self):
        from infrastructure.metrics import JOBS_PROCESSING_DURATION_SECONDS
        assert JOBS_PROCESSING_DURATION_SECONDS is not None
