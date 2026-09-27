# Custom exceptions for the application
#
# EXCEPTION HIERARCHY:
#   ComfyError (base)
#   ├── NotFoundError       - Resource not found (404)
#   ├── ValidationError     - Invalid input or state (422)
#   ├── ProviderError       - Serverless provider failure (e.g., Modal timeout)
#   ├── ContainerError      - Local Docker/Podman container issue
#   ├── JobError            - Job processing failure
#   ├── DownloadError       - File download failure
#   └── ConfigurationError  - Bad application configuration
#
# All exceptions carry a machine-readable `code` field so API error handlers
# can produce consistent JSON responses without string matching.


class ComfyError(Exception):
    """Base exception for all application errors."""
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class NotFoundError(ComfyError):
    """Resource not found."""
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            message=f"{resource} '{identifier}' not found",
            code="NOT_FOUND"
        )
        self.resource = resource
        self.identifier = identifier


class ValidationError(ComfyError):
    """Validation failed."""
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message=message, code="VALIDATION_ERROR")
        self.field = field

class UploadValidationError(ValidationError):
    """Bounded upload/export validation failure.

    Subclasses ValidationError so the existing 400 handler applies, but carries a
    specific machine-readable `code` plus limit metadata so every upload/export
    failure reads the same way for API clients and the UI.

    Codes:
      UPLOAD_TOO_LARGE        – body exceeded the route's byte budget
      UNSUPPORTED_FILE_TYPE   – extension not in the route's allowlist
      INVALID_IMAGE           – bytes are not a readable image
      IMAGE_DIMENSIONS_TOO_LARGE – image wider/taller than allowed
      IMAGE_PIXEL_LIMIT       – image pixel count above the bomb guard
      UPLOAD_CANCELLED        – client went away mid-upload
      UPLOAD_TIMEOUT          – upload stalled
      EXPORT_TOO_LARGE        – archive would exceed the export budget
      EXPORT_TOO_MANY_FILES   – more files requested than the export allows
      EXPORT_NO_MATCHING_FILES – nothing in the request resolved on disk
    """

    def __init__(
        self,
        message: str,
        code: str = "UPLOAD_INVALID",
        field: str | None = None,
        max_bytes: int | None = None,
        received_bytes: int | None = None,
        details: dict | None = None,
    ):
        super().__init__(message=message, field=field)
        self.code = code
        self.max_bytes = max_bytes
        self.received_bytes = received_bytes
        self.details = details or {}

    def to_payload(self) -> dict:
        """Render the API error body (superset of the ValidationError shape)."""
        payload: dict = {"error": self.message, "code": self.code, "field": self.field}
        if self.max_bytes is not None:
            payload["max_bytes"] = self.max_bytes
        if self.received_bytes is not None:
            payload["received_bytes"] = self.received_bytes
        if self.details:
            payload["details"] = self.details
        return payload


class MissingModelsError(ComfyError):
    """Workflow requires models that are not available."""
    def __init__(self, required_models: dict, global_missing: dict, missing_by_provider: dict, can_trigger_download: bool):
        super().__init__(message="No provider has all required models installed", code="MISSING_MODELS")
        self.required_models = required_models
        self.global_missing = global_missing
        self.missing_by_provider = missing_by_provider
        self.can_trigger_download = can_trigger_download



class ProviderError(ComfyError):
    """Provider-related error."""
    def __init__(self, provider_id: str, message: str):
        super().__init__(
            message=f"Provider '{provider_id}': {message}",
            code="PROVIDER_ERROR"
        )
        self.provider_id = provider_id


class ProviderConnectionError(ProviderError):
    """Failed to connect to the provider."""
    def __init__(self, provider_id: str, message: str):
        super().__init__(provider_id, message)
        self.code = "PROVIDER_CONNECTION_ERROR"


class ProviderTimeoutError(ProviderError):
    """Provider operation timed out."""
    def __init__(self, provider_id: str, message: str):
        super().__init__(provider_id, message)
        self.code = "PROVIDER_TIMEOUT_ERROR"


class ContainerError(ComfyError):
    """Container management error."""
    def __init__(self, provider_id: str, message: str):
        super().__init__(
            message=f"Container for '{provider_id}': {message}",
            code="CONTAINER_ERROR"
        )
        self.provider_id = provider_id


class JobError(ComfyError):
    """Job processing error."""
    def __init__(self, job_id: str, message: str):
        super().__init__(
            message=f"Job '{job_id}': {message}",
            code="JOB_ERROR"
        )
        self.job_id = job_id


class DownloadError(ComfyError):
    """Download failed."""
    def __init__(self, url: str, message: str):
        super().__init__(
            message=f"Download from '{url}': {message}",
            code="DOWNLOAD_ERROR"
        )
        self.url = url


class ConfigurationError(ComfyError):
    """Configuration error."""
    def __init__(self, message: str):
        super().__init__(message=message, code="CONFIGURATION_ERROR")


class ServiceUnavailableError(ComfyError):
    """A dependency this request needs is temporarily down.

    Distinct from `ConfigurationError` (which is a setting nobody set right and
    will still be wrong after a retry) because the two want opposite operator
    responses, and distinct from an opaque 500 because a client can tell
    "try again" apart from "you are holding it wrong".

    Used where the alternative was returning a 200 with an empty body: a
    dependency that failed cannot be represented as a successful empty result,
    because the caller cannot tell that apart from a real empty result.
    """

    def __init__(self, message: str, service: str = "unknown", status_code: int = 503):
        super().__init__(message=message, code="SERVICE_UNAVAILABLE")
        self.service = service
        self.status_code = status_code
