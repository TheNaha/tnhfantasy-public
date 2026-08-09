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
