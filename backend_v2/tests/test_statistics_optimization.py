
from unittest.mock import patch

import pytest

from api.routes.statistics import _calculate_detailed_statistics, _calculate_statistics


class TestStatisticsOptimization:
    """Tests for the optimized statistics logic using GalleryIndexer."""

    @patch('api.routes.statistics.gallery_indexer')
    def test_calculate_statistics_uses_indexer(self, mock_indexer):
        """Verify _calculate_statistics uses gallery_indexer instead of glob."""
        # Setup mock return value
        mock_indexer.get_all_files.return_value = [
            {
                "metadata": {
                    "metadata_version": "2.0",
                    "checkpoint": {"name": "model_v1"},
                    "loras": [{"name": "lora_v1"}],
                    "sampler": "euler_a",
                    "scheduler": "normal",
                    "steps": 20,
                    "cfg": 7.0,
                    "width": 512,
                    "height": 512,
                    "job": {"duration_seconds": 5.0, "completed_at": 1600000000}
                }
            }
        ]

        # Execute
        stats = _calculate_statistics()

        # Verify
        mock_indexer.get_all_files.assert_called_once()

        # Check stats correctness
        assert stats["total_images"] == 1
        assert stats["models"]["model_v1"] == 1
        assert stats["loras"]["lora_v1"] == 1
        assert stats["avg_generation_time"] == 5.0
        assert stats["popular_settings"]["steps"]["20"] == 1

    @patch('api.routes.statistics.gallery_indexer')
    def test_calculate_detailed_statistics_uses_indexer(self, mock_indexer):
        """Verify _calculate_detailed_statistics uses gallery_indexer instead of glob."""
        # Setup mock return value
        mock_indexer.get_all_files.return_value = [
            {
                "metadata": {
                    "metadata_version": "2.0",
                    "checkpoint": {"name": "model_v1"},
                    "loras": [{"name": "lora_v1", "weight": 0.8}],
                    "sampler": "euler_a",
                    "scheduler": "normal",
                    "steps": 20,
                    "cfg": 7.0,
                    "width": 512,
                    "height": 512,
                    "prompt": "a beautiful landscape",
                    "job": {"duration_seconds": 5.0, "completed_at": 1600000000}
                }
            }
        ]

        # Execute
        stats = _calculate_detailed_statistics()

        # Verify
        mock_indexer.get_all_files.assert_called_once()

        # Check stats correctness
        assert stats["total_images"] == 1
        assert stats["models"]["checkpoints"]["model_v1"] == 1
        assert stats["performance"]["avg_time"] == 5.0
        assert stats["prompts"]["total"] == 1
        assert "beautiful" in stats["prompts"]["keywords"]

if __name__ == '__main__':
    pytest.main()
