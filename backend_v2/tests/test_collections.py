# Collections API Tests
import pytest


@pytest.fixture
def sample_collection_data():
    """Sample collection creation data."""
    return {
        "name": "My Collection",
        "color": "#FF5733",
        "description": "A test collection",
    }


class TestCollectionsListEmpty:
    """Test listing when no collections exist."""

    def test_list_collections_empty(self, client):
        response = client.get("/api/collections")
        assert response.status_code == 200
        data = response.json()
        assert "collections" in data
        assert data["collections"] == []


class TestCollectionsCreate:
    """Tests for collection creation."""

    def test_create_collection(self, client, sample_collection_data):
        response = client.post("/api/collections", json=sample_collection_data)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "My Collection"
        assert data["color"] == "#FF5733"
        assert data["id"] is not None

    def test_create_collection_minimal(self, client):
        """Minimal collection with only name."""
        response = client.post("/api/collections", json={"name": "Minimal"})
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Minimal"
        assert data["color"] == "#3B82F6"  # Default color

    def test_create_collection_with_description(self, client):
        response = client.post("/api/collections", json={
            "name": "Described",
            "description": "A meaningful description"
        })
        assert response.status_code == 200
        assert response.json()["description"] == "A meaningful description"


class TestCollectionsRead:
    """Tests for reading collections."""

    def test_get_collection_by_id(self, client, sample_collection_data):
        create_resp = client.post("/api/collections", json=sample_collection_data)
        col_id = create_resp.json()["id"]

        response = client.get(f"/api/collections/{col_id}")
        assert response.status_code == 200
        assert response.json()["id"] == col_id

    def test_get_collection_not_found(self, client):
        response = client.get("/api/collections/99999")
        assert response.status_code == 404

    def test_get_collection_includes_images_by_default(self, client, sample_collection_data):
        create_resp = client.post("/api/collections", json=sample_collection_data)
        col_id = create_resp.json()["id"]

        response = client.get(f"/api/collections/{col_id}")
        data = response.json()
        assert "images" in data
        assert "image_count" in data

    def test_list_collections_after_create(self, client, sample_collection_data):
        client.post("/api/collections", json=sample_collection_data)

        response = client.get("/api/collections")
        data = response.json()
        assert len(data["collections"]) == 1


class TestCollectionsUpdate:
    """Tests for collection updates."""

    def test_update_collection_name(self, client, sample_collection_data):
        create_resp = client.post("/api/collections", json=sample_collection_data)
        col_id = create_resp.json()["id"]

        response = client.put(f"/api/collections/{col_id}", json={"name": "Renamed"})
        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"

    def test_update_collection_color(self, client, sample_collection_data):
        create_resp = client.post("/api/collections", json=sample_collection_data)
        col_id = create_resp.json()["id"]

        response = client.put(f"/api/collections/{col_id}", json={"color": "#000000"})
        assert response.status_code == 200
        assert response.json()["color"] == "#000000"

    def test_update_collection_not_found(self, client):
        response = client.put("/api/collections/99999", json={"name": "new"})
        assert response.status_code == 404


class TestCollectionsImages:
    """Tests for adding/removing images."""

    def test_add_images_to_collection(self, client, sample_collection_data):
        create_resp = client.post("/api/collections", json=sample_collection_data)
        col_id = create_resp.json()["id"]

        response = client.post(
            f"/api/collections/{col_id}/images",
            json={"images": ["image1.png", "image2.png"]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["added"] == 2

    def test_add_images_duplicate_not_added(self, client, sample_collection_data):
        """Adding same image twice only adds it once."""
        create_resp = client.post("/api/collections", json=sample_collection_data)
        col_id = create_resp.json()["id"]

        client.post(f"/api/collections/{col_id}/images", json={"images": ["image.png"]})
        response = client.post(f"/api/collections/{col_id}/images", json={"images": ["image.png"]})

        assert response.status_code == 200
        assert response.json()["added"] == 0  # Already exists

    def test_collection_image_count_after_add(self, client, sample_collection_data):
        create_resp = client.post("/api/collections", json=sample_collection_data)
        col_id = create_resp.json()["id"]

        client.post(f"/api/collections/{col_id}/images", json={"images": ["a.png", "b.png", "c.png"]})

        response = client.get(f"/api/collections/{col_id}")
        assert response.json()["image_count"] == 3

    def test_remove_images_from_collection(self, client, sample_collection_data):
        import json as json_module
        create_resp = client.post("/api/collections", json=sample_collection_data)
        col_id = create_resp.json()["id"]

        client.post(f"/api/collections/{col_id}/images", json={"images": ["a.png", "b.png"]})
        response = client.request(
            "DELETE",
            f"/api/collections/{col_id}/images",
            content=json_module.dumps({"images": ["a.png"]}),
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 200
        assert response.json()["removed"] == 1

    def test_add_images_to_nonexistent_collection(self, client):
        response = client.post("/api/collections/99999/images", json={"images": ["x.png"]})
        assert response.status_code == 404


class TestCollectionsDelete:
    """Tests for collection deletion."""

    def test_delete_collection(self, client, sample_collection_data):
        create_resp = client.post("/api/collections", json=sample_collection_data)
        col_id = create_resp.json()["id"]

        response = client.delete(f"/api/collections/{col_id}")
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_collection_removes_it(self, client, sample_collection_data):
        create_resp = client.post("/api/collections", json=sample_collection_data)
        col_id = create_resp.json()["id"]

        client.delete(f"/api/collections/{col_id}")

        get_response = client.get(f"/api/collections/{col_id}")
        assert get_response.status_code == 404

    def test_delete_collection_not_found(self, client):
        response = client.delete("/api/collections/99999")
        assert response.status_code == 404


class TestCollectionsImportExport:
    """Tests for bulk import."""

    def test_import_collections(self, client):
        data = {
            "collections": [
                {"name": "Batch 1", "images": ["a.png", "b.png"]},
                {"name": "Batch 2", "color": "#FF0000"},
            ]
        }
        response = client.post("/api/collections/import", json=data)
        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        assert result["imported"] == 2
