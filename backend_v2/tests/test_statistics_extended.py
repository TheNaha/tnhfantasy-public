"""Extended tests for api/routes/statistics.py"""
import os
import pytest
from unittest.mock import patch


class TestStatisticsExtended:
    """Extended tests for statistics API endpoints."""

    def test_get_basic_statistics(self, client):
        response = client.get("/api/statistics")
        assert response.status_code == 200

    def test_get_basic_statistics_no_output_dir(self, client):
        with patch.dict(os.environ, {"OUTPUT_DIR": "/tmp/nonexistent_dir_xyz"}):
            response = client.get("/api/statistics")
        assert response.status_code == 200

    def test_basic_stats_structure(self, client):
        response = client.get("/api/statistics")
        data = response.json()
        # Statistics endpoint should return a dict
        assert isinstance(data, dict)

    def test_get_detailed_statistics(self, client):
        response = client.get("/api/statistics/detailed")
        assert response.status_code == 200

    def test_detailed_stats_structure(self, client):
        response = client.get("/api/statistics/detailed")
        data = response.json()
        assert isinstance(data, dict)

    def test_get_summary(self, client):
        response = client.get("/api/statistics/summary")
        assert response.status_code == 200

    def test_summary_structure(self, client):
        response = client.get("/api/statistics/summary")
        data = response.json()
        assert isinstance(data, dict)

    def test_statistics_with_empty_output(self, client, tmp_path):
        """Test statistics with empty output directory."""
        with patch.dict(os.environ, {"OUTPUT_DIR": str(tmp_path)}):
            response = client.get("/api/statistics")
        assert response.status_code == 200

    def test_detailed_statistics_with_empty_output(self, client, tmp_path):
        """Test detailed statistics with empty output directory."""
        with patch.dict(os.environ, {"OUTPUT_DIR": str(tmp_path)}):
            response = client.get("/api/statistics/detailed")
        assert response.status_code == 200

    def test_summary_with_empty_output(self, client, tmp_path):
        """Test summary statistics with empty output directory."""
        with patch.dict(os.environ, {"OUTPUT_DIR": str(tmp_path)}):
            response = client.get("/api/statistics/summary")
        assert response.status_code == 200
