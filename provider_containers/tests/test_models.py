import pytest
from pydantic import ValidationError
from provider_core.models import (
    InferenceRequest,
    CancelJobRequest,
    DownloadRequest,
    ListModelsRequest,
    DeleteModelRequest,
    UploadFileRequest,
    ValidateModelsRequest
)

class TestProviderModels:
    def test_inference_request_valid(self):
        req = InferenceRequest(workflow={"key": "val"}, use_snapshot=True, job_id="123")
        assert req.workflow == {"key": "val"}
        assert req.use_snapshot is True
        assert req.job_id == "123"

    def test_inference_request_missing_workflow(self):
        with pytest.raises(ValidationError):
            InferenceRequest(job_id="123")

    def test_cancel_job_request(self):
        req = CancelJobRequest(job_id="123")
        assert req.job_id == "123"

    def test_download_request_valid(self):
        req = DownloadRequest(
            url="http://example.com/file",
            path="models/test.safetensors",
            token="token",
            preview_url="preview",
            metadata={"key": "val"}
        )
        assert req.url == "http://example.com/file"
        assert req.path == "models/test.safetensors"

    def test_list_models_request(self):
        req = ListModelsRequest(directory="checkpoints")
        assert req.directory == "checkpoints"

    def test_delete_model_request(self):
        req = DeleteModelRequest(path="path/to/model")
        assert req.path == "path/to/model"

    def test_upload_file_request(self):
        req = UploadFileRequest(
            filename="test.png",
            content_base64="base64data",
            directory="input"
        )
        assert req.filename == "test.png"
        assert req.content_base64 == "base64data"

    def test_validate_models_request(self):
        req = ValidateModelsRequest()
        assert req.directory == "models/checkpoints" # default
        assert req.delete_invalid is False # default
