"""
Provider Core - shared library for the TNHComfy remote agent.

This package used to live under ``provider_containers/`` alongside the
legacy containerized provider workers (image/llm/tts ``worker.py`` HTTP
apps, their container HTTP clients, and the worker router/background/
deploy machinery). Those workers were removed when the backend switched
to in-process engines: the only remaining consumer of this package is
``remote_agent/server.py``, which imports the submodules it needs
directly. The worker-only modules (router, base_client, background,
deploy, sse, comfy_lifecycle, worker_bootstrap, model_scan,
ranged_read) were deleted with the workers.
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
    MODEL_DIRECTORIES,
)
from .state import ReconciliationState, get_reconciliation_state
from .http_client import (
    configure_http_client,
    get_http_client,
    http_client_config_from_env,
    get_file_size_cap,
    HttpClientConfig,
)
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
from .auth import bearer_from_header, token_matches
from .utils import (
    get_safe_path,
    build_deploy_compatibility_response,
    is_model_candidate,
    is_transient_artifact,
)
from .downloads import (
    download_model_to_path,
    build_authenticated_download_request,
    pending_download_paths,
    pipeline_artifacts,
)
from .validation import (
    MIN_MODEL_SIZE,
    VALID_FILE_HEADERS,
    validate_downloaded_file,
)
from .responses import failed, from_upstream, ok
from .logging import get_logger

__all__ = [
    "get_logger",
    "get_safe_path",
    "is_model_candidate",
    "is_transient_artifact",
    "bearer_from_header",
    "token_matches",
    "failed",
    "from_upstream",
    "ok",
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
    "MODEL_DIRECTORIES",
    # State
    "ReconciliationState",
    "get_reconciliation_state",
    # HTTP Client
    "get_http_client",
    "configure_http_client",
    "http_client_config_from_env",
    "get_file_size_cap",
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
    "build_deploy_compatibility_response",
    "download_model_to_path",
    "build_authenticated_download_request",
    "pending_download_paths",
    "pipeline_artifacts",
    # Validation
    "MIN_MODEL_SIZE",
    "VALID_FILE_HEADERS",
    "validate_downloaded_file",
]
