"""Tests for api/routes/statistics.py - _calculate_statistics and _calculate_detailed_statistics"""
from unittest.mock import patch

import pytest

from infrastructure.cache import invalidate_cache


# Helper to create file data structure returned by the assets index
def create_file_data(metadata: dict = None) -> dict:
    return {
        "name": "test.png",
        "relative_path": "test.png",
        "full_path": "/tmp/test.png",
        "size": 1024,
        "date": 1600000000,
        "metadata": metadata or {}
    }

class TestCalculateStatisticsInternal:
    """Tests for the private _calculate_statistics function using mocked assets index."""

    @patch("api.routes.statistics._all_gallery_files")
    def test_empty_gallery(self, mock_indexer):
        mock_indexer.return_value = []
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        assert result["total_images"] == 0
        assert isinstance(result, dict)

    @patch("api.routes.statistics._all_gallery_files")
    def test_with_no_metadata(self, mock_indexer):
        mock_indexer.return_value = [create_file_data({})]
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        # Files without metadata are skipped
        assert result["total_images"] == 0

    @patch("api.routes.statistics._all_gallery_files")
    def test_with_enriched_metadata(self, mock_indexer):
        metadata = {
            "metadata_version": "2.0",
            "checkpoint": "test_model.safetensors",
            "sampler": "euler",
            "scheduler": "normal",
            "steps": 20,
            "cfg": 7.0,
            "width": 512,
            "height": 512,
            "prompt": "a beautiful cat sitting on a table",
            "seed": 12345
        }
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        assert result["total_images"] == 1
        assert result["enriched_metadata_count"] == 1

    @patch("api.routes.statistics._all_gallery_files")
    def test_with_legacy_metadata(self, mock_indexer):
        metadata = {
            "checkpoint": "old_model.safetensors",
            "sampler": "dpm",
        }
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        assert result["total_images"] == 1
        assert result["legacy_metadata_count"] == 1

    @patch("api.routes.statistics._all_gallery_files")
    def test_model_usage_tracking(self, mock_indexer):
        metadata = {
            "checkpoint": "anime_model.safetensors",
            "sampler": "euler_a",
        }
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        assert "anime_model.safetensors" in result["models"]
        assert result["models"]["anime_model.safetensors"] == 1

    @patch("api.routes.statistics._all_gallery_files")
    def test_sampler_tracking(self, mock_indexer):
        metadata = {"sampler": "dpm2_karras"}
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        assert "dpm2_karras" in result["samplers"]

    @patch("api.routes.statistics._all_gallery_files")
    def test_multiple_images(self, mock_indexer):
        files = []
        for i in range(3):
            metadata = {"checkpoint": f"model_{i}.safetensors", "sampler": "euler"}
            files.append(create_file_data(metadata))

        mock_indexer.return_value = files
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        assert result["total_images"] == 3

    @patch("api.routes.statistics._all_gallery_files")
    def test_lora_tracking(self, mock_indexer):
        metadata = {
            "loras": [{"name": "style_lora.safetensors", "weight": 0.8}]
        }
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        assert "style_lora.safetensors" in result["loras"]

    @patch("api.routes.statistics._all_gallery_files")
    def test_generation_time_tracking(self, mock_indexer):
        metadata = {
            "checkpoint": "perf_model.safetensors",
            "job": {"duration_seconds": 3.5}
        }
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        assert result["total_generation_time"] == 3.5
        assert result["avg_generation_time"] == 3.5

    @patch("api.routes.statistics._all_gallery_files")
    def test_steps_tracking(self, mock_indexer):
        metadata = {"steps": 30}
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        assert "popular_settings" in result
        assert "steps" in result["popular_settings"]
        assert result["popular_settings"]["steps"]["30"] == 1

    @patch("api.routes.statistics._all_gallery_files")
    def test_resolution_tracking(self, mock_indexer):
        metadata = {"width": 768, "height": 512}
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        assert "768x512" in result["popular_settings"]["resolution"]

    @patch("api.routes.statistics._all_gallery_files")
    def test_checkpoint_dict_format(self, mock_indexer):
        """Test that checkpoint as a dict is handled correctly."""
        metadata = {
            "checkpoint": {"name": "dict_model.safetensors", "type": "Checkpoint"}
        }
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_statistics

        result = _calculate_statistics()

        assert "dict_model.safetensors" in result["models"]


class TestCalculateDetailedStatisticsInternal:
    """Tests for the private _calculate_detailed_statistics function."""

    @patch("api.routes.statistics._all_gallery_files")
    def test_empty_gallery(self, mock_indexer):
        mock_indexer.return_value = []
        from api.routes.statistics import _calculate_detailed_statistics

        result = _calculate_detailed_statistics()

        assert result["total_images"] == 0
        assert "timeline" in result
        assert "models" in result

    @patch("api.routes.statistics._all_gallery_files")
    def test_timeline_tracking(self, mock_indexer):
        metadata = {
            "metadata_version": "2.0",
            "checkpoint": "model.safetensors",
            "job": {"completed_at": 1600000000}  # Fixed timestamp
        }
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_detailed_statistics

        result = _calculate_detailed_statistics()

        assert result["total_images"] == 1
        assert isinstance(result["timeline"]["daily"], dict)
        # Verify specific date key if needed, or just that data exists

    @patch("api.routes.statistics._all_gallery_files")
    def test_prompt_analytics(self, mock_indexer):
        metadata = {
            "prompt": "a beautiful girl with blue eyes",
            "negativePrompt": "bad quality, blurry"  # Note key change to negativePrompt if that's what implementation uses
        }
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_detailed_statistics

        result = _calculate_detailed_statistics()

        assert "prompts" in result
        assert result["prompts"]["total"] == 1
        assert "beautiful" in result["prompts"]["keywords"]
        assert result["prompts"]["negative_usage"] == 1

    @patch("api.routes.statistics._all_gallery_files")
    def test_performance_metrics(self, mock_indexer):
        metadata = {
            "checkpoint": {"name": "perf_model.safetensors"},
            "job": {"duration_seconds": 3.5},
            "steps": 20
        }
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_detailed_statistics

        result = _calculate_detailed_statistics()

        assert "performance" in result
        assert result["performance"]["total_time"] == 3.5
        assert "perf_model.safetensors" in result["performance"]["by_model"]

    @patch("api.routes.statistics._all_gallery_files")
    def test_lora_weight_tracking(self, mock_indexer):
        metadata = {
            "loras": [{"name": "style.safetensors", "weight": 0.7}]
        }
        mock_indexer.return_value = [create_file_data(metadata)]
        from api.routes.statistics import _calculate_detailed_statistics

        result = _calculate_detailed_statistics()

        assert "lora_weights" in result["models"]
        # Implementation might put it elsewhere, checking structure from logic
        found = False
        for lora in result["models"]["lora_weights"]:
            if lora["name"] == "style.safetensors":
                assert lora["avg_weight"] == 0.7
                found = True
        assert found


class TestStatisticsEndpointWithData:
    """Integration tests for the statistics API with real image data."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear the statistics cache before each test."""
        invalidate_cache("stats")
        yield
        invalidate_cache("stats")

    @patch("api.routes.statistics._all_gallery_files")
    def test_statistics_endpoint_with_images(self, mock_get_all_files, client):
        metadata = {
            "metadata_version": "2.0",
            "checkpoint": "test_model.safetensors",
            "sampler": "euler",
            "steps": 20
        }
        mock_get_all_files.return_value = [create_file_data(metadata)]

        response = client.get("/api/statistics")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert data["total_images"] == 1

    @patch("api.routes.statistics._all_gallery_files")
    def test_detailed_statistics_endpoint_with_images(self, mock_get_all_files, client):
        metadata = {"checkpoint": "model.safetensors", "prompt": "test prompt"}
        mock_get_all_files.return_value = [create_file_data(metadata)]

        response = client.get("/api/statistics/detailed")
        assert response.status_code == 200
        data = response.json()
        assert data["total_images"] == 1

    @patch("api.routes.statistics._all_gallery_files")
    def test_summary_endpoint_with_images(self, mock_get_all_files, client):
        metadata = {"checkpoint": "model.safetensors"}
        mock_get_all_files.return_value = [create_file_data(metadata)]

        response = client.get("/api/statistics/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_images"] == 1
