import pytest

from api.provider_client import validate_success_payload


def test_validate_success_payload_accepts_valid_images():
    payload = {
        "status": "success",
        "images": [
            {
                "filename": "image-1.png",
                "data": "YWJj",
                "_base64_encoded": True,
            }
        ],
    }

    validate_success_payload(payload)


def test_validate_success_payload_allows_success_without_images():
    payload = {
        "status": "success",
        "message": "Completed",
    }

    validate_success_payload(payload)


def test_validate_success_payload_rejects_non_list_images():
    payload = {
        "status": "success",
        "images": {"filename": "image-1.png"},
    }

    with pytest.raises(ValueError, match="images must be a list"):
        validate_success_payload(payload)


def test_validate_success_payload_rejects_missing_filename():
    payload = {
        "status": "success",
        "images": [{"data": "YWJj", "_base64_encoded": True}],
    }

    with pytest.raises(ValueError, match="missing filename"):
        validate_success_payload(payload)


def test_validate_success_payload_rejects_missing_encoded_data():
    payload = {
        "status": "success",
        "images": [{"filename": "image-1.png", "_base64_encoded": True}],
    }

    with pytest.raises(ValueError, match="missing base64 data"):
        validate_success_payload(payload)
