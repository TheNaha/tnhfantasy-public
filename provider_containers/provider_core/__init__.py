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
from .http_client import get_http_client, HttpClientConfig
from .reconciliation import (
    report_file_status_v2,
    batch_update_file_status_v2,
    push_reconciliation_event,
    get_pending_downloads,
    get_all_expected_paths,
    determine_download_token,
    calculate_safe_deletion_limit,
    run_reconciliation_v2,
)
from .background import (
    reconciliation_loop,
    log_startup_info,
    JobCancellationTracker,
    get_job_tracker,
    auto_discovery_loop,
)

from .utils import get_safe_path, build_deploy_compatibility_response
from .downloads import download_model_to_path, build_authenticated_download_request
from .validation import (
    MIN_MODEL_SIZE,
    VALID_FILE_HEADERS,
    validate_downloaded_file,
)
from .models_utils import list_models_with_metadata_internal
from .router import attach_provider_routes, ProviderClient
from .logging import get_logger

__all__ = [
    "get_logger",
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
    "run_reconciliation_v2",
    # Background
    "reconciliation_loop",
    "log_startup_info",
    "JobCancellationTracker",
    "get_job_tracker",
    "auto_discovery_loop",
    "build_deploy_compatibility_response",
    "download_model_to_path",
    "build_authenticated_download_request",
    # Validation
    "MIN_MODEL_SIZE",
    "VALID_FILE_HEADERS",
    "validate_downloaded_file",
    "list_models_with_metadata_internal",
    # Router
    "attach_provider_routes",
    "ProviderClient",
]
