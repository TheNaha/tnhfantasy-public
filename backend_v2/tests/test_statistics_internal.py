"""Tests for api/routes/statistics.py - _calculate_statistics and _calculate_detailed_statistics"""
import os
import json
import tempfile
import pytest
from PIL import Image, PngImagePlugin
from unittest.mock import patch


def create_png_with_metadata(directory: str, filename: str, metadata: dict) -> str:
    """Create a PNG file with embedded comfy_metadata."""
    path = os.path.join(directory, filename)
    img = Image.new("RGB", (512, 512), color=(100, 150, 200))
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("comfy_metadata", json.dumps(metadata))
    img.save(path, pnginfo=pnginfo)
    return path


@pytest.fixture
def tmp_output_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestCalculateStatisticsInternal:
    """Tests for the private _calculate_statistics function."""

    def test_empty_output_dir(self, tmp_output_dir):
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert result["total_images"] == 0
        assert isinstance(result, dict)

    def test_nonexistent_output_dir(self, tmp_path):
        from api.routes.statistics import _calculate_statistics
        nonexistent = str(tmp_path / "nonexistent")
        with patch("api.routes.statistics.OUTPUT_DIR", nonexistent):
            result = _calculate_statistics()
        assert result["total_images"] == 0

    def test_with_png_no_metadata(self, tmp_output_dir):
        # Create a plain PNG with no metadata
        path = os.path.join(tmp_output_dir, "plain.png")
        img = Image.new("RGB", (100, 100))
        img.save(path)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        # plain PNG has no metadata so may not count
        assert isinstance(result, dict)

    def test_with_enriched_metadata(self, tmp_output_dir):
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
        create_png_with_metadata(tmp_output_dir, "image1.png", metadata)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert result["total_images"] >= 1
        assert result["enriched_metadata_count"] >= 1

    def test_with_legacy_metadata(self, tmp_output_dir):
        metadata = {
            "checkpoint": "old_model.safetensors",
            "sampler": "dpm",
        }
        create_png_with_metadata(tmp_output_dir, "legacy.png", metadata)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert result["total_images"] >= 1
        assert result["legacy_metadata_count"] >= 1

    def test_model_usage_tracking(self, tmp_output_dir):
        metadata = {
            "checkpoint": "anime_model.safetensors",
            "sampler": "euler_a",
        }
        create_png_with_metadata(tmp_output_dir, "model_test.png", metadata)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert "anime_model.safetensors" in result["models"]

    def test_sampler_tracking(self, tmp_output_dir):
        metadata = {"sampler": "dpm2_karras"}
        create_png_with_metadata(tmp_output_dir, "sampler_test.png", metadata)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert "dpm2_karras" in result["samplers"]

    def test_skips_thumbnail_files(self, tmp_output_dir):
        # Create a thumbnail
        path = os.path.join(tmp_output_dir, "image.thumb.png")
        img = Image.new("RGB", (50, 50))
        img.save(path)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert result["total_images"] == 0

    def test_skips_preview_files(self, tmp_output_dir):
        path = os.path.join(tmp_output_dir, "image.preview.png")
        img = Image.new("RGB", (50, 50))
        img.save(path)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert result["total_images"] == 0

    def test_multiple_images(self, tmp_output_dir):
        for i in range(3):
            metadata = {"checkpoint": f"model_{i}.safetensors", "sampler": "euler"}
            create_png_with_metadata(tmp_output_dir, f"image_{i}.png", metadata)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert result["total_images"] >= 3

    def test_lora_tracking(self, tmp_output_dir):
        metadata = {
            "loras": [{"name": "style_lora.safetensors", "weight": 0.8}]
        }
        create_png_with_metadata(tmp_output_dir, "lora_test.png", metadata)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert "style_lora.safetensors" in result["loras"]

    def test_generation_time_tracking(self, tmp_output_dir):
        metadata = {
            "checkpoint": "perf_model.safetensors",
            "job": {"duration_seconds": 3.5}
        }
        create_png_with_metadata(tmp_output_dir, "time_test.png", metadata)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert result["total_generation_time"] > 0

    def test_steps_tracking(self, tmp_output_dir):
        metadata = {"steps": 30}
        create_png_with_metadata(tmp_output_dir, "steps_test.png", metadata)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert "popular_settings" in result
        assert "steps" in result["popular_settings"]

    def test_resolution_tracking(self, tmp_output_dir):
        metadata = {"width": 768, "height": 512}
        create_png_with_metadata(tmp_output_dir, "res_test.png", metadata)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert "768x512" in result["popular_settings"]["resolution"]

    def test_checkpoint_dict_format(self, tmp_output_dir):
        """Test that checkpoint as a dict is handled correctly."""
        metadata = {
            "checkpoint": {"name": "dict_model.safetensors", "type": "Checkpoint"}
        }
        create_png_with_metadata(tmp_output_dir, "dict_ckpt.png", metadata)
        from api.routes.statistics import _calculate_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_statistics()
        assert "dict_model.safetensors" in result["models"]


class TestCalculateDetailedStatisticsInternal:
    """Tests for the private _calculate_detailed_statistics function."""

    def test_empty_output_dir(self, tmp_output_dir):
        from api.routes.statistics import _calculate_detailed_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_detailed_statistics()
        assert result["total_images"] == 0
        assert "timeline" in result
        assert "models" in result

    def test_nonexistent_dir(self, tmp_path):
        from api.routes.statistics import _calculate_detailed_statistics
        nonexistent = str(tmp_path / "nonexistent")
        with patch("api.routes.statistics.OUTPUT_DIR", nonexistent):
            result = _calculate_detailed_statistics()
        assert result["total_images"] == 0

    def test_timeline_tracking(self, tmp_output_dir):
        metadata = {"metadata_version": "2.0", "checkpoint": "model.safetensors"}
        create_png_with_metadata(tmp_output_dir, "timeline.png", metadata)
        from api.routes.statistics import _calculate_detailed_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_detailed_statistics()
        assert result["total_images"] == 1
        assert isinstance(result["timeline"]["daily"], dict)

    def test_prompt_analytics(self, tmp_output_dir):
        metadata = {
            "prompt": "a beautiful girl with blue eyes",
            "negative": "bad quality, blurry"
        }
        create_png_with_metadata(tmp_output_dir, "prompt_test.png", metadata)
        from api.routes.statistics import _calculate_detailed_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_detailed_statistics()
        assert "prompts" in result

    def test_performance_metrics(self, tmp_output_dir):
        metadata = {
            "checkpoint": "perf_model.safetensors",
            "generation_time": 3.5,
            "steps": 20
        }
        create_png_with_metadata(tmp_output_dir, "perf_test.png", metadata)
        from api.routes.statistics import _calculate_detailed_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_detailed_statistics()
        assert "performance" in result

    def test_lora_weight_tracking(self, tmp_output_dir):
        metadata = {
            "loras": [{"name": "style.safetensors", "weight": 0.7}]
        }
        create_png_with_metadata(tmp_output_dir, "lora_weight.png", metadata)
        from api.routes.statistics import _calculate_detailed_statistics
        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            result = _calculate_detailed_statistics()
        assert "loras" in result["models"]


class TestStatisticsEndpointWithData:
    """Integration tests for the statistics API with real image data."""

    def test_statistics_endpoint_with_images(self, client, tmp_output_dir):
        metadata = {
            "metadata_version": "2.0",
            "checkpoint": "test_model.safetensors",
            "sampler": "euler",
            "steps": 20
        }
        create_png_with_metadata(tmp_output_dir, "stat_image.png", metadata)

        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            response = client.get("/api/statistics")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_detailed_statistics_endpoint_with_images(self, client, tmp_output_dir):
        metadata = {"checkpoint": "model.safetensors", "prompt": "test prompt"}
        create_png_with_metadata(tmp_output_dir, "detail_image.png", metadata)

        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            response = client.get("/api/statistics/detailed")
        assert response.status_code == 200

    def test_summary_endpoint_with_images(self, client, tmp_output_dir):
        metadata = {"checkpoint": "model.safetensors"}
        create_png_with_metadata(tmp_output_dir, "summary_image.png", metadata)

        with patch("api.routes.statistics.OUTPUT_DIR", tmp_output_dir):
            response = client.get("/api/statistics/summary")
        assert response.status_code == 200
