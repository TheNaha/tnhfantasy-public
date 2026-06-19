# Prometheus metrics for application monitoring
# Exposes counters, histograms, and gauges for key operations
#
# Usage:
#   from infrastructure.metrics import metrics
#   metrics.track_request("GET", "/api/jobs", 200, 0.05)
#   metrics.track_job_created()

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    Info,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)

# Use the default registry so all metrics are auto-registered

# ============================================================================
# HTTP REQUEST METRICS
# ============================================================================

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status_code"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

# ============================================================================
# JOB METRICS
# ============================================================================

JOBS_CREATED_TOTAL = Counter(
    "jobs_created_total",
    "Total number of jobs created",
    registry=REGISTRY,
)

JOBS_COMPLETED_TOTAL = Counter(
    "jobs_completed_total",
    "Total number of jobs completed",
    ["status"],  # completed, failed
    registry=REGISTRY,
)

JOBS_PROCESSING_DURATION_SECONDS = Histogram(
    "jobs_processing_duration_seconds",
    "Job processing duration in seconds",
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
    registry=REGISTRY,
)

JOBS_QUEUE_SIZE = Gauge(
    "jobs_queue_size",
    "Current number of jobs in the queue",
    registry=REGISTRY,
)

JOBS_ACTIVE = Gauge(
    "jobs_active",
    "Number of currently active/processing jobs",
    registry=REGISTRY,
)

# ============================================================================
# PROVIDER METRICS
# ============================================================================

PROVIDER_REQUESTS_TOTAL = Counter(
    "provider_requests_total",
    "Total requests to providers",
    ["provider_id", "status"],  # status: success, failure
    registry=REGISTRY,
)

PROVIDER_REQUEST_DURATION_SECONDS = Histogram(
    "provider_request_duration_seconds",
    "Provider request duration in seconds",
    ["provider_id"],
    buckets=(0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
    registry=REGISTRY,
)

PROVIDER_FAILURES_TOTAL = Counter(
    "provider_failures_total",
    "Total provider failures",
    ["provider_id", "error_type"],
    registry=REGISTRY,
)

# ============================================================================
# CACHE METRICS
# ============================================================================

CACHE_HITS_TOTAL = Counter(
    "cache_hits_total",
    "Total cache hits",
    ["cache_name"],
    registry=REGISTRY,
)

CACHE_MISSES_TOTAL = Counter(
    "cache_misses_total",
    "Total cache misses",
    ["cache_name"],
    registry=REGISTRY,
)

CACHE_SIZE = Gauge(
    "cache_current_size",
    "Current number of entries in cache",
    ["cache_name"],
    registry=REGISTRY,
)

# ============================================================================
# DATABASE METRICS
# ============================================================================

DB_OPERATIONS_TOTAL = Counter(
    "db_operations_total",
    "Total database operations",
    ["operation"],  # query, insert, update, delete
    registry=REGISTRY,
)

DB_OPERATION_DURATION_SECONDS = Histogram(
    "db_operation_duration_seconds",
    "Database operation duration in seconds",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    registry=REGISTRY,
)

DB_ERRORS_TOTAL = Counter(
    "db_errors_total",
    "Total database errors",
    ["operation"],
    registry=REGISTRY,
)

# ============================================================================
# DOWNLOAD METRICS
# ============================================================================

DOWNLOADS_TOTAL = Counter(
    "downloads_total",
    "Total model downloads",
    ["status"],  # started, completed, failed
    registry=REGISTRY,
)

DOWNLOADS_ACTIVE = Gauge(
    "downloads_active",
    "Number of currently active downloads",
    registry=REGISTRY,
)

# ============================================================================
# MODEL METRICS
# ============================================================================

MODELS_TOTAL = Gauge(
    "models_total",
    "Total number of models tracked",
    registry=REGISTRY,
)

MODEL_SYNC_TOTAL = Counter(
    "model_sync_total",
    "Total model sync operations",
    ["status"],  # success, failure
    registry=REGISTRY,
)

# ============================================================================
# WEBSOCKET METRICS
# ============================================================================

WEBSOCKET_CONNECTIONS = Gauge(
    "websocket_connections_active",
    "Number of active WebSocket connections",
    registry=REGISTRY,
)

# ============================================================================
# SCHEDULER METRICS
# ============================================================================

SCHEDULER_TASKS_TOTAL = Counter(
    "scheduler_tasks_total",
    "Total scheduled task executions",
    ["task_id", "status"],  # status: success, failure
    registry=REGISTRY,
)

# ============================================================================
# APP INFO
# ============================================================================

APP_INFO = Info(
    "app",
    "Application information",
    registry=REGISTRY,
)
APP_INFO.info({"name": "tnhcomfy", "version": "2.0.0"})


# ============================================================================
# HELPER CLASS
# ============================================================================

class MetricsManager:
    """Convenience wrapper for recording metrics."""

    def track_request(self, method: str, endpoint: str, status_code: int, duration: float):
        """Track an HTTP request."""
        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status_code=str(status_code)).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(duration)

    def track_job_created(self):
        JOBS_CREATED_TOTAL.inc()

    def track_job_completed(self, status: str, duration: float = None):
        JOBS_COMPLETED_TOTAL.labels(status=status).inc()
        if duration is not None:
            JOBS_PROCESSING_DURATION_SECONDS.observe(duration)

    def set_queue_size(self, size: int):
        JOBS_QUEUE_SIZE.set(size)

    def set_active_jobs(self, count: int):
        JOBS_ACTIVE.set(count)

    def track_provider_request(self, provider_id: str, status: str, duration: float = None):
        PROVIDER_REQUESTS_TOTAL.labels(provider_id=provider_id, status=status).inc()
        if duration is not None:
            PROVIDER_REQUEST_DURATION_SECONDS.labels(provider_id=provider_id).observe(duration)

    def track_provider_failure(self, provider_id: str, error_type: str):
        PROVIDER_FAILURES_TOTAL.labels(provider_id=provider_id, error_type=error_type).inc()

    def track_cache_hit(self, cache_name: str):
        CACHE_HITS_TOTAL.labels(cache_name=cache_name).inc()

    def track_cache_miss(self, cache_name: str):
        CACHE_MISSES_TOTAL.labels(cache_name=cache_name).inc()

    def set_cache_size(self, cache_name: str, size: int):
        CACHE_SIZE.labels(cache_name=cache_name).set(size)

    def track_db_operation(self, operation: str, duration: float = None):
        DB_OPERATIONS_TOTAL.labels(operation=operation).inc()
        if duration is not None:
            DB_OPERATION_DURATION_SECONDS.labels(operation=operation).observe(duration)

    def track_db_error(self, operation: str):
        DB_ERRORS_TOTAL.labels(operation=operation).inc()

    def track_download(self, status: str):
        DOWNLOADS_TOTAL.labels(status=status).inc()

    def set_active_downloads(self, count: int):
        DOWNLOADS_ACTIVE.set(count)

    def set_models_total(self, count: int):
        MODELS_TOTAL.set(count)

    def track_model_sync(self, status: str):
        MODEL_SYNC_TOTAL.labels(status=status).inc()

    def set_websocket_connections(self, count: int):
        WEBSOCKET_CONNECTIONS.set(count)

    def track_scheduler_task(self, task_id: str, status: str):
        SCHEDULER_TASKS_TOTAL.labels(task_id=task_id, status=status).inc()

    def generate_metrics(self) -> bytes:
        """Generate Prometheus metrics output."""
        return generate_latest(REGISTRY)

    def get_content_type(self) -> str:
        """Get the Prometheus content type header."""
        return CONTENT_TYPE_LATEST


# Global metrics instance
metrics = MetricsManager()
