# Custom Exception Tests
import pytest

from core.exceptions import (
    ComfyError,
    ConfigurationError,
    ContainerError,
    DownloadError,
    JobError,
    NotFoundError,
    ProviderError,
    ValidationError,
)


class TestComfyError:
    """Tests for the base ComfyError exception."""

    def test_basic_message(self):
        """Test creating ComfyError with message."""
        err = ComfyError("something went wrong")
        assert str(err) == "something went wrong"
        assert err.message == "something went wrong"
        assert err.code == "UNKNOWN_ERROR"

    def test_custom_code(self):
        """Test creating ComfyError with custom code."""
        err = ComfyError("boom", code="MY_CODE")
        assert err.code == "MY_CODE"

    def test_is_exception(self):
        """ComfyError is an Exception subclass."""
        with pytest.raises(ComfyError):
            raise ComfyError("test")


class TestNotFoundError:
    """Tests for NotFoundError."""

    def test_message_format(self):
        """Message includes resource type and identifier."""
        err = NotFoundError("Job", "abc-123")
        assert "Job" in err.message
        assert "abc-123" in err.message

    def test_code(self):
        """Error code is NOT_FOUND."""
        err = NotFoundError("Provider", "p1")
        assert err.code == "NOT_FOUND"

    def test_attributes(self):
        """resource and identifier attributes are set."""
        err = NotFoundError("Model", "my-model")
        assert err.resource == "Model"
        assert err.identifier == "my-model"

    def test_is_comfy_error(self):
        """NotFoundError is a ComfyError subclass."""
        err = NotFoundError("X", "y")
        assert isinstance(err, ComfyError)


class TestValidationError:
    """Tests for ValidationError."""

    def test_basic(self):
        err = ValidationError("field is required")
        assert err.message == "field is required"
        assert err.code == "VALIDATION_ERROR"
        assert err.field is None

    def test_with_field(self):
        err = ValidationError("must be positive", field="steps")
        assert err.field == "steps"

    def test_is_comfy_error(self):
        assert isinstance(ValidationError("x"), ComfyError)


class TestProviderError:
    """Tests for ProviderError."""

    def test_message_format(self):
        err = ProviderError("modal-primary", "connection timed out")
        assert "modal-primary" in err.message
        assert "connection timed out" in err.message

    def test_code(self):
        err = ProviderError("p", "err")
        assert err.code == "PROVIDER_ERROR"

    def test_provider_id_attribute(self):
        err = ProviderError("modal-primary", "bad")
        assert err.provider_id == "modal-primary"


class TestContainerError:
    """Tests for ContainerError."""

    def test_message_format(self):
        err = ContainerError("beam-1", "failed to start")
        assert "beam-1" in err.message
        assert "failed to start" in err.message

    def test_code(self):
        err = ContainerError("p", "err")
        assert err.code == "CONTAINER_ERROR"

    def test_provider_id_attribute(self):
        err = ContainerError("my-provider", "crash")
        assert err.provider_id == "my-provider"


class TestJobError:
    """Tests for JobError."""

    def test_message_format(self):
        err = JobError("job-xyz", "failed to process")
        assert "job-xyz" in err.message
        assert "failed to process" in err.message

    def test_code(self):
        err = JobError("j", "err")
        assert err.code == "JOB_ERROR"

    def test_job_id_attribute(self):
        err = JobError("job-abc", "timeout")
        assert err.job_id == "job-abc"


class TestDownloadError:
    """Tests for DownloadError."""

    def test_message_format(self):
        err = DownloadError("https://example.com/model.safetensors", "404 Not Found")
        assert "https://example.com/model.safetensors" in err.message
        assert "404 Not Found" in err.message

    def test_code(self):
        err = DownloadError("http://x.com", "err")
        assert err.code == "DOWNLOAD_ERROR"

    def test_url_attribute(self):
        url = "https://civitai.com/model.pt"
        err = DownloadError(url, "timeout")
        assert err.url == url


class TestConfigurationError:
    """Tests for ConfigurationError."""

    def test_basic(self):
        err = ConfigurationError("invalid config value")
        assert err.message == "invalid config value"
        assert err.code == "CONFIGURATION_ERROR"

    def test_is_comfy_error(self):
        assert isinstance(ConfigurationError("x"), ComfyError)
