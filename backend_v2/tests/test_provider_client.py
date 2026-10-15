import pytest

from services.provider_client import validate_image_outputs


def test_validate_image_outputs_accepts_valid_images():
    payload = {
        "event": "completed",
        "outputs": [
            {"filename": "image-1.png", "data": "YWJj", "_base64_encoded": True},
        ],
    }
    validate_image_outputs(payload)


def test_validate_image_outputs_accepts_reference_images():
    payload = {
        "event": "completed",
        "outputs": [{"filename": "image-1.png", "subfolder": "", "image_type": "output"}],
    }
    validate_image_outputs(payload)


def test_validate_image_outputs_accepts_success_without_outputs():
    validate_image_outputs({"event": "completed"})
    validate_image_outputs({"event": "completed", "outputs": None})


def test_validate_image_outputs_rejects_non_list_outputs():
    payload = {"event": "completed", "outputs": {"filename": "image-1.png"}}
    with pytest.raises(ValueError, match="outputs must be a list"):
        validate_image_outputs(payload)


def test_validate_image_outputs_rejects_missing_data_or_filename():
    payload = {"event": "completed", "outputs": [{"_base64_encoded": True}]}
    with pytest.raises(ValueError, match="missing data or filename"):
        validate_image_outputs(payload)


@pytest.mark.asyncio
async def test_call_in_process_image_provider_failed_event_raises_provider_call_error():
    from unittest.mock import AsyncMock
    from services.provider_client import call_in_process_image_provider, ProviderCallError

    class MockEngine:
        async def run_inference(self, **kwargs):
            yield {"event": "failed", "message": "CUDA out of memory"}

    mock_job_service = AsyncMock()
    with pytest.raises(ProviderCallError, match="CUDA out of memory"):
        await call_in_process_image_provider(
            engine=MockEngine(),
            workflow={},
            job_id="test-job",
            job_service=mock_job_service,
            total_nodes=5,
            timeout=10.0,
            provider_id="modal-test",
        )


@pytest.mark.asyncio
async def test_call_in_process_image_provider_auth_error_raises_non_retryable_call_error():
    from unittest.mock import AsyncMock
    from services.engines.base import EngineAuthError
    from services.provider_client import call_in_process_image_provider, ProviderCallError

    class MockEngine:
        async def run_inference(self, **kwargs):
            raise EngineAuthError("Modal token rejected")
            yield  # pragma: no cover

    mock_job_service = AsyncMock()
    with pytest.raises(ProviderCallError, match="Modal token rejected") as exc_info:
        await call_in_process_image_provider(
            engine=MockEngine(),
            workflow={},
            job_id="test-job",
            job_service=mock_job_service,
            total_nodes=5,
            timeout=10.0,
            provider_id="modal-test",
        )
    assert exc_info.value.is_retryable is False


@pytest.mark.asyncio
async def test_call_in_process_llm_provider_auth_error_raises_non_retryable_call_error():
    from unittest.mock import AsyncMock
    from services.engines.base import EngineAuthError
    from services.provider_client import call_in_process_llm_provider, ProviderCallError

    class MockLLMEngine:
        async def run_inference(self, **kwargs):
            raise EngineAuthError("OpenAI key rejected")
            yield  # pragma: no cover

    mock_job_service = AsyncMock()
    with pytest.raises(ProviderCallError, match="OpenAI key rejected") as exc_info:
        await call_in_process_llm_provider(
            engine=MockLLMEngine(),
            workflow={},
            job_id="test-job",
            job_service=mock_job_service,
            timeout=10.0,
            provider_id="llm-test",
        )
    assert exc_info.value.is_retryable is False

