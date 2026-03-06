"""
Provider Core - Shared utilities for provider workers.

This package extracts common functionality used by both Modal and Beam workers
to reduce code duplication and improve maintainability.
"""

from .models import (
    InferenceRequest,
    DownloadRequest,
    ListModelsRequest,
    DeleteModelRequest,
    UploadFileRequest,
    ValidateModelsRequest,
    CancelJobRequest,
    ErrorResponse,
    StatusResponse,
    build_error_response,
    build_status_response,
)
from .state import ReconciliationState, get_reconciliation_state
from .sync_progress import SyncProgressReporter
from .http_client import get_http_client, HttpClientConfig
from .reconciliation import (
    report_file_status_v2,
    batch_update_file_status_v2,
    push_reconciliation_event,
    get_pending_downloads,
    get_all_expected_paths,
    determine_download_token,
    calculate_safe_deletion_limit,
)
from .background import (
    reconciliation_loop,
    log_startup_info,
    JobCancellationTracker,
    get_job_tracker,
)

from .utils import get_safe_path

__all__ = [
    "get_safe_path",
    # Models
    "InferenceRequest",
    "DownloadRequest", 
    "ListModelsRequest",
    "DeleteModelRequest",
    "UploadFileRequest",
    "ValidateModelsRequest",
    "CancelJobRequest",
    "ErrorResponse",
    "StatusResponse",
    "build_error_response",
    "build_status_response",
    # State
    "ReconciliationState",
    "get_reconciliation_state",
    # Sync Progress
    "SyncProgressReporter",
    # HTTP Client
    "get_http_client",
    "HttpClientConfig",
    # Reconciliation
    "report_file_status_v2",
    "batch_update_file_status_v2",
    "push_reconciliation_event",
    "get_pending_downloads",
    "get_all_expected_paths",
    "determine_download_token",
    "calculate_safe_deletion_limit",
    # Background
    "reconciliation_loop",
    "log_startup_info",
    "JobCancellationTracker",
    "get_job_tracker",
]
