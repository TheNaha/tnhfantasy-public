# Custom exceptions for the application
from typing import Optional


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
    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message=message, code="VALIDATION_ERROR")
        self.field = field


class ProviderError(ComfyError):
    """Provider-related error."""
    def __init__(self, provider_id: str, message: str):
        super().__init__(
            message=f"Provider '{provider_id}': {message}",
            code="PROVIDER_ERROR"
        )
        self.provider_id = provider_id


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
