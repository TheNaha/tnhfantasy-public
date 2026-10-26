from unittest.mock import MagicMock
import pytest

import services.external_model_service as ext_module
from services.external_model_service import ExternalModelService


@pytest.mark.asyncio
async def test_civitai_search_includes_auth_header(monkeypatch):
    monkeypatch.setenv("CIVITAI_TOKEN", "test_civitai_secret_token_123")

    mock_client = MagicMock()
    recorded_calls = []

    async def fake_get(url, **kwargs):
        recorded_calls.append((url, kwargs))
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"items": [{"id": 1, "name": "Model 1"}]}
        return resp

    mock_client.get = fake_get
    monkeypatch.setattr(ext_module, "get_http_client", lambda: mock_client)

    service = ExternalModelService()
    result = await service.search_civitai(query="anime")

    assert len(recorded_calls) == 1
    url, kwargs = recorded_calls[0]
    assert "https://civitai.com/api/v1/models" in url
    assert kwargs.get("headers", {}).get("Authorization") == "Bearer test_civitai_secret_token_123"
    assert len(result.get("items", [])) == 1


@pytest.mark.asyncio
async def test_civitai_search_without_token(monkeypatch):
    monkeypatch.delenv("CIVITAI_TOKEN", raising=False)

    mock_client = MagicMock()
    recorded_calls = []

    async def fake_get(url, **kwargs):
        recorded_calls.append((url, kwargs))
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"items": []}
        return resp

    mock_client.get = fake_get
    monkeypatch.setattr(ext_module, "get_http_client", lambda: mock_client)

    service = ExternalModelService()
    await service.search_civitai(query="test")

    assert len(recorded_calls) == 1
    _, kwargs = recorded_calls[0]
    assert "Authorization" not in kwargs.get("headers", {})


@pytest.mark.asyncio
async def test_huggingface_search_includes_auth_header(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test_secret_token_456")

    mock_client = MagicMock()
    recorded_calls = []

    async def fake_get(url, **kwargs):
        recorded_calls.append((url, kwargs))
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = [{"id": "user/repo", "tags": ["diffusers"]}]
        return resp

    mock_client.get = fake_get
    monkeypatch.setattr(ext_module, "get_http_client", lambda: mock_client)

    service = ExternalModelService()
    result = await service.search_huggingface(query="pony")

    assert len(recorded_calls) == 1
    url, kwargs = recorded_calls[0]
    assert "https://huggingface.co/api/models" in url
    assert kwargs.get("headers", {}).get("Authorization") == "Bearer hf_test_secret_token_456"
    assert len(result.get("items", [])) == 1


@pytest.mark.asyncio
async def test_civitai_model_fallback_to_red_on_404(monkeypatch):
    monkeypatch.setenv("CIVITAI_TOKEN", "civ_token_xyz")

    mock_client = MagicMock()
    recorded_urls = []

    async def fake_get(url, **kwargs):
        recorded_urls.append((url, kwargs))
        resp = MagicMock()
        if "civitai.com" in url:
            resp.status_code = 404
        else:
            resp.status_code = 200
            resp.json.return_value = {"id": 1234, "name": "Red Model"}
        return resp

    mock_client.get = fake_get
    monkeypatch.setattr(ext_module, "get_http_client", lambda: mock_client)

    service = ExternalModelService()
    result = await service.get_civitai_model(1234)

    assert result["name"] == "Red Model"
    assert len(recorded_urls) == 2
    assert recorded_urls[0][0] == "https://civitai.com/api/v1/models/1234"
    assert recorded_urls[1][0] == "https://civitai.red/api/v1/models/1234"
    assert recorded_urls[0][1]["headers"]["Authorization"] == "Bearer civ_token_xyz"
    assert recorded_urls[1][1]["headers"]["Authorization"] == "Bearer civ_token_xyz"


@pytest.mark.asyncio
async def test_civitai_model_version_fallback_to_red_on_404(monkeypatch):
    monkeypatch.setenv("CIVITAI_TOKEN", "civ_token_xyz")

    mock_client = MagicMock()
    recorded_urls = []

    async def fake_get(url, **kwargs):
        recorded_urls.append((url, kwargs))
        resp = MagicMock()
        if "civitai.com" in url:
            resp.status_code = 404
        else:
            resp.status_code = 200
            resp.json.return_value = {"id": 5678, "name": "v1.0"}
        return resp

    mock_client.get = fake_get
    monkeypatch.setattr(ext_module, "get_http_client", lambda: mock_client)

    service = ExternalModelService()
    result = await service.get_civitai_model_version(5678)

    assert result["name"] == "v1.0"
    assert len(recorded_urls) == 2
    assert recorded_urls[0][0] == "https://civitai.com/api/v1/model-versions/5678"
    assert recorded_urls[1][0] == "https://civitai.red/api/v1/model-versions/5678"


@pytest.mark.asyncio
async def test_parse_civitai_red_url_prefers_red_domain(monkeypatch):
    mock_client = MagicMock()
    recorded_urls = []

    async def fake_get(url, **kwargs):
        recorded_urls.append(url)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"id": 9999, "name": "Parsed Red Model"}
        return resp

    mock_client.get = fake_get
    monkeypatch.setattr(ext_module, "get_http_client", lambda: mock_client)

    service = ExternalModelService()
    result = await service.parse_model_url("https://civitai.red/models/9999/some-model")

    assert result["name"] == "Parsed Red Model"
    assert len(recorded_urls) == 1
    assert recorded_urls[0] == "https://civitai.red/api/v1/models/9999"
