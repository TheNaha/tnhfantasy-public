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


class TestRequestValidationErrorHandler:
    """A 422 for a malformed body.

    Two leaks are closed here. `exc.body` used to be logged at error severity —
    so every malformed `POST /api/jobs` wrote the whole ComfyUI workflow,
    including the user's prompt, into the log — and echoed back to the client,
    where any proxy or error tracker in between now had a copy of it.
    """

    def _malformed(self, client, path="/api/jobs", payload=None):
        return client.post(path, json=payload if payload is not None else {
            "task_type": "image",
            # `workflow` must be a dict; a string here is the canonical malformed
            # body, and it is the one that carries prompt text.
            "workflow": "a prompt the user typed, sent as a string",
        })

    def test_the_request_body_is_not_echoed_back(self, client):
        response = self._malformed(client)
        assert response.status_code == 422
        body = response.json()
        assert "body" not in body
        assert "a prompt the user typed" not in response.text

    def test_the_error_uses_the_api_envelope(self, client):
        body = self._malformed(client).json()
        # Same shape as every other handler, so a client sees one error format.
        assert body["code"] == "REQUEST_VALIDATION_ERROR"
        assert isinstance(body["error"], str)
        assert isinstance(body["detail"], list) and body["detail"]

    def test_the_detail_names_the_offending_field(self, client):
        detail = self._malformed(client).json()["detail"]
        assert any("workflow" in item["field"] for item in detail)
        assert all({"field", "message"} <= set(item) for item in detail)

    def test_the_body_is_not_logged_at_error_severity(self, client, caplog):
        import logging

        with caplog.at_level(logging.DEBUG, logger="error_handlers"):
            self._malformed(client)

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert not errors, f"a validation error logged at ERROR: {[r.getMessage() for r in errors]}"
        assert not any("a prompt the user typed" in r.getMessage() for r in caplog.records)
