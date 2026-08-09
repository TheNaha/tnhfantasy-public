# Statistics API Tests
from unittest.mock import patch


class TestStatisticsEndpoints:
    """Tests for the statistics API endpoints."""

    def test_get_statistics_returns_ok(self, client):
        """Statistics endpoint returns 200."""
        response = client.get("/api/statistics")
        assert response.status_code == 200

    def test_get_statistics_structure(self, client):
        """Statistics response has expected top-level keys."""
        response = client.get("/api/statistics")
        data = response.json()
        assert "total_images" in data
        assert "models" in data
        assert "loras" in data
        assert "samplers" in data
        assert "schedulers" in data
        assert "avg_generation_time" in data
        assert "images_by_date" in data
        assert "popular_settings" in data

    @patch('api.routes.statistics._all_gallery_files')
    def test_get_statistics_empty_output(self, mock_get_all, client):
        """Statistics returns zeros when no output images exist."""
        mock_get_all.return_value = []
        from infrastructure.cache import invalidate_cache
        invalidate_cache('stats')

        response = client.get("/api/statistics")
        data = response.json()
        assert data["total_images"] == 0
        assert data["models"] == {}
        assert data["loras"] == {}

    def test_get_detailed_statistics_returns_ok(self, client):
        """Detailed statistics endpoint returns 200."""
        response = client.get("/api/statistics/detailed")
        assert response.status_code == 200

    def test_get_detailed_statistics_structure(self, client):
        """Detailed statistics response has expected structure."""
        response = client.get("/api/statistics/detailed")
        data = response.json()
        assert "timeline" in data
        assert "models" in data
        assert "settings" in data
        assert "prompts" in data
        assert "performance" in data
        assert "total_images" in data

    def test_get_detailed_timeline_structure(self, client):
        """Timeline data has daily/hourly/weekday breakdowns."""
        response = client.get("/api/statistics/detailed")
        timeline = response.json()["timeline"]
        assert "daily" in timeline
        assert "hourly" in timeline
        assert "weekday" in timeline

    def test_get_summary_returns_ok(self, client):
        """Summary statistics endpoint returns 200."""
        response = client.get("/api/statistics/summary")
        assert response.status_code == 200

    def test_get_summary_structure(self, client):
        """Summary response has expected keys."""
        response = client.get("/api/statistics/summary")
        data = response.json()
        assert "total_images" in data
        assert "models_used" in data
        assert "loras_used" in data
        assert "avg_generation_time" in data

    @patch('api.routes.statistics._all_gallery_files')
    def test_get_summary_empty_output(self, mock_get_all, client):
        """Summary returns zero counts when no images."""
        mock_get_all.return_value = []
        from infrastructure.cache import invalidate_cache
        invalidate_cache('stats')

        response = client.get("/api/statistics/summary")
        data = response.json()
        assert data["total_images"] == 0
        assert data["models_used"] == 0
        assert data["loras_used"] == 0
        assert data["top_model"] is None
