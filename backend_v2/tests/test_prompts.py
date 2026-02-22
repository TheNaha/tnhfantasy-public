# Prompts API Tests
import pytest


@pytest.fixture
def sample_prompt_data():
    """Sample prompt creation data."""
    return {
        "name": "Portrait Test",
        "text": "portrait of a woman, highly detailed, realistic",
        "negative": "blur, low quality",
        "category": "Portrait",
        "tags": ["portrait", "realistic"],
        "favorite": False,
    }


class TestPromptsListEmpty:
    """Test listing when no prompts exist."""

    def test_list_prompts_empty(self, client):
        response = client.get("/api/prompts")
        assert response.status_code == 200
        data = response.json()
        assert "prompts" in data
        assert "count" in data
        assert data["count"] == 0

    def test_get_categories(self, client):
        """Categories endpoint returns default categories."""
        response = client.get("/api/prompts/categories")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert "Custom" in data["categories"]

    def test_get_favorites_empty(self, client):
        response = client.get("/api/prompts/favorites")
        assert response.status_code == 200
        data = response.json()
        assert "prompts" in data
        assert data["prompts"] == []

    def test_get_most_used_empty(self, client):
        response = client.get("/api/prompts/most-used")
        assert response.status_code == 200
        data = response.json()
        assert "prompts" in data


class TestPromptsCreate:
    """Tests for prompt creation."""

    def test_create_prompt(self, client, sample_prompt_data):
        response = client.post("/api/prompts", json=sample_prompt_data)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Portrait Test"
        assert data["text"] == "portrait of a woman, highly detailed, realistic"
        assert data["category"] == "Portrait"
        assert data["id"] is not None

    def test_create_prompt_minimal(self, client):
        """Minimal prompt with only required fields."""
        response = client.post("/api/prompts", json={"name": "minimal", "text": "a cat"})
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "minimal"
        assert data["category"] == "Custom"

    def test_create_prompt_with_settings(self, client):
        """Prompt with full generation settings."""
        response = client.post("/api/prompts", json={
            "name": "with-settings",
            "text": "test",
            "settings": {"steps": 30, "cfg": 7.0, "sampler": "euler"}
        })
        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["steps"] == 30


class TestPromptsRead:
    """Tests for reading prompts."""

    def test_get_prompt_by_id(self, client, sample_prompt_data):
        create_resp = client.post("/api/prompts", json=sample_prompt_data)
        prompt_id = create_resp.json()["id"]

        response = client.get(f"/api/prompts/{prompt_id}")
        assert response.status_code == 200
        assert response.json()["id"] == prompt_id

    def test_get_prompt_not_found(self, client):
        response = client.get("/api/prompts/99999")
        assert response.status_code == 404

    def test_list_prompts_after_create(self, client, sample_prompt_data):
        client.post("/api/prompts", json=sample_prompt_data)
        response = client.get("/api/prompts")
        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_list_prompts_filter_by_category(self, client):
        client.post("/api/prompts", json={"name": "p1", "text": "t1", "category": "Portrait"})
        client.post("/api/prompts", json={"name": "p2", "text": "t2", "category": "Landscape"})

        response = client.get("/api/prompts?category=Portrait")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["prompts"][0]["name"] == "p1"

    def test_list_prompts_filter_favorites(self, client):
        client.post("/api/prompts", json={"name": "fav", "text": "t", "favorite": True})
        client.post("/api/prompts", json={"name": "not-fav", "text": "t", "favorite": False})

        response = client.get("/api/prompts?favorite=true")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["prompts"][0]["name"] == "fav"


class TestPromptsUpdate:
    """Tests for prompt updates."""

    def test_update_prompt_name(self, client, sample_prompt_data):
        create_resp = client.post("/api/prompts", json=sample_prompt_data)
        prompt_id = create_resp.json()["id"]

        response = client.put(f"/api/prompts/{prompt_id}", json={"name": "Updated Name"})
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"

    def test_update_prompt_favorite(self, client, sample_prompt_data):
        create_resp = client.post("/api/prompts", json=sample_prompt_data)
        prompt_id = create_resp.json()["id"]

        response = client.put(f"/api/prompts/{prompt_id}", json={"favorite": True})
        assert response.status_code == 200
        assert response.json()["favorite"] is True

    def test_update_prompt_not_found(self, client):
        response = client.put("/api/prompts/99999", json={"name": "new"})
        assert response.status_code == 404

    def test_increment_usage(self, client, sample_prompt_data):
        create_resp = client.post("/api/prompts", json=sample_prompt_data)
        prompt_id = create_resp.json()["id"]

        response = client.post(f"/api/prompts/{prompt_id}/use")
        assert response.status_code == 200
        data = response.json()
        assert data["usage_count"] == 1

    def test_increment_usage_multiple_times(self, client, sample_prompt_data):
        create_resp = client.post("/api/prompts", json=sample_prompt_data)
        prompt_id = create_resp.json()["id"]

        for _ in range(3):
            client.post(f"/api/prompts/{prompt_id}/use")

        response = client.get(f"/api/prompts/{prompt_id}")
        assert response.json()["usage_count"] == 3


class TestPromptsDelete:
    """Tests for prompt deletion."""

    def test_delete_prompt(self, client, sample_prompt_data):
        create_resp = client.post("/api/prompts", json=sample_prompt_data)
        prompt_id = create_resp.json()["id"]

        response = client.delete(f"/api/prompts/{prompt_id}")
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_prompt_removes_it(self, client, sample_prompt_data):
        create_resp = client.post("/api/prompts", json=sample_prompt_data)
        prompt_id = create_resp.json()["id"]

        client.delete(f"/api/prompts/{prompt_id}")

        get_response = client.get(f"/api/prompts/{prompt_id}")
        assert get_response.status_code == 404

    def test_delete_prompt_not_found(self, client):
        response = client.delete("/api/prompts/99999")
        assert response.status_code == 404


class TestPromptsImportExport:
    """Tests for bulk import."""

    def test_import_prompts(self, client):
        data = {
            "prompts": [
                {"name": "p1", "text": "text one"},
                {"name": "p2", "text": "text two", "category": "Landscape"},
            ]
        }
        response = client.post("/api/prompts/import", json=data)
        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        assert result["imported"] == 2
