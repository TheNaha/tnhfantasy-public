import os
import pytest
import shutil
import tempfile
import sys
import json
from unittest.mock import patch, MagicMock

# Add backend_v2 to path so we can import from api
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.routes.files import batch_get_metadata, BatchMetadataRequest

# Mock image processor to avoid PIL dependency
@pytest.fixture
def mock_read_metadata():
    with patch("api.deps.read_image_metadata") as mock:
        mock.return_value = {"workflow": {}, "prompt": {}, "blurhash": "LEHV6nWB2yk8pyo0adR*.7kCMdnj"}
        yield mock

@pytest.mark.asyncio
async def test_batch_get_metadata_optimization(mock_read_metadata):
    # Setup temporary directory structure
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = os.path.join(temp_dir, "output")
        os.makedirs(output_dir)

        # Structure:
        # output/direct.png
        # output/2023/10/deep.png
        # output/thumb/thumb.png (should be ignored)

        # Create files
        with open(os.path.join(output_dir, "direct.png"), "w") as f:
            f.write("fake png")

        deep_dir = os.path.join(output_dir, "2023", "10")
        os.makedirs(deep_dir)
        with open(os.path.join(deep_dir, "deep.png"), "w") as f:
            f.write("fake png")

        thumb_dir = os.path.join(output_dir, "thumb")
        os.makedirs(thumb_dir)
        with open(os.path.join(thumb_dir, "thumb.png"), "w") as f:
            f.write("fake png")

        # Patch OUTPUT_DIR in the module
        with patch("api.routes.files.OUTPUT_DIR", output_dir):

            # Request paths
            paths = [
                "direct.png",          # Direct hit
                "deep.png",            # Needs search
                "missing.png",         # Not found
                "output/direct.png",   # Should be normalized
                "thumb.png"            # In thumb dir, should NOT be found (or filtered out)
            ]

            req = BatchMetadataRequest(paths=paths)

            # Run the function
            response = await batch_get_metadata(req)
            results = response["results"]

            # Verify direct.png
            assert results["direct.png"]["success"] is True, f"Failed for direct.png: {results['direct.png']}"
            assert results["direct.png"]["metadata"]["blurhash"] == "LEHV6nWB2yk8pyo0adR*.7kCMdnj"

            # Verify deep.png
            assert results["deep.png"]["success"] is True, f"Failed for deep.png: {results['deep.png']}"
            assert results["deep.png"]["metadata"]["blurhash"] == "LEHV6nWB2yk8pyo0adR*.7kCMdnj"

            # Verify missing.png
            assert results["missing.png"]["error"] == "not_found", f"Unexpected result for missing.png: {results['missing.png']}"

            # Verify output/direct.png (normalized)
            assert results["output/direct.png"]["success"] is True, f"Failed for output/direct.png: {results['output/direct.png']}"

            # Verify thumb.png
            # The logic explicitly skips 'thumb' directory during walk.
            # So it should be not_found unless it exists elsewhere.
            assert results["thumb.png"].get("error") == "not_found", f"thumb.png should not be found: {results['thumb.png']}"

            # Verify that we didn't call read_metadata for missing files
            # mock_read_metadata should be called 3 times (direct, deep, output/direct)
            assert mock_read_metadata.call_count == 3
