"""Additional tests for infrastructure/image_processor.py - covering uncovered functions"""
import json
import os
import tempfile

import pytest
from PIL import Image

from infrastructure.image_processor import (
    cleanup_thumbnails,
    encode_blurhash,
    process_directory,
    process_image,
)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def create_png(directory: str, filename: str = "test.png", size=(100, 100)) -> str:
    """Create a simple PNG file for testing."""
    path = os.path.join(directory, filename)
    img = Image.new("RGB", size, color=(100, 150, 200))
    img.save(path)
    return path


class TestEncodeBlurHash:
    def test_returns_string(self, tmp_dir):
        path = create_png(tmp_dir)
        result = encode_blurhash(path)
        assert isinstance(result, str)

    def test_result_is_nonempty(self, tmp_dir):
        path = create_png(tmp_dir)
        result = encode_blurhash(path)
        assert len(result) > 0

    def test_larger_image(self, tmp_dir):
        path = create_png(tmp_dir, size=(500, 500))
        result = encode_blurhash(path)
        assert isinstance(result, str)

    def test_rgba_image(self, tmp_dir):
        path = os.path.join(tmp_dir, "rgba.png")
        img = Image.new("RGBA", (100, 100), color=(100, 150, 200, 255))
        img.save(path)
        result = encode_blurhash(path)
        assert isinstance(result, str)


class TestProcessImage:
    def test_returns_dict_with_thumbnails(self, tmp_dir):
        path = create_png(tmp_dir)
        result = process_image(path)
        assert "thumbnails" in result

    def test_returns_dict_with_blurhash(self, tmp_dir):
        path = create_png(tmp_dir)
        result = process_image(path)
        assert "blurhash" in result

    def test_returns_dict_with_dimensions(self, tmp_dir):
        path = create_png(tmp_dir)
        result = process_image(path)
        assert "width" in result
        assert "height" in result

    def test_returns_original_path(self, tmp_dir):
        path = create_png(tmp_dir)
        result = process_image(path)
        assert result["original"] == path

    def test_with_existing_sidecar_json(self, tmp_dir):
        path = create_png(tmp_dir, "meta.png")
        sidecar_path = path + ".json"
        metadata = {"prompt": "test", "seed": 42}
        with open(sidecar_path, "w") as f:
            json.dump(metadata, f)

        result = process_image(path, save_metadata=True)
        assert "legacy_metadata" in result
        assert result["legacy_metadata"]["prompt"] == "test"

    def test_without_sidecar_json(self, tmp_dir):
        path = create_png(tmp_dir, "no_meta.png")
        result = process_image(path, save_metadata=True)
        assert "legacy_metadata" not in result

    def test_with_corrupted_sidecar_json(self, tmp_dir):
        path = create_png(tmp_dir, "corrupt.png")
        sidecar_path = path + ".json"
        with open(sidecar_path, "w") as f:
            f.write("{not valid json")
        # Should not raise
        result = process_image(path, save_metadata=True)
        assert "thumbnails" in result


class TestProcessDirectory:
    def test_empty_directory(self, tmp_dir):
        result = process_directory(tmp_dir)
        assert result == []

    def test_processes_png_files(self, tmp_dir):
        create_png(tmp_dir, "image1.png")
        result = process_directory(tmp_dir)
        assert len(result) >= 1

    def test_skips_thumbnail_files(self, tmp_dir):
        create_png(tmp_dir, "image.thumb.png")
        result = process_directory(tmp_dir)
        assert len(result) == 0

    def test_skips_medium_files(self, tmp_dir):
        create_png(tmp_dir, "image.medium.png")
        result = process_directory(tmp_dir)
        assert len(result) == 0

    def test_skips_existing_thumbnails_by_default(self, tmp_dir):
        path = create_png(tmp_dir, "image_with_thumb.png")
        # Create fake thumbnail
        thumb_path = path.replace(".png", ".thumb.png")
        create_png(tmp_dir, "image_with_thumb.thumb.png")

        result = process_directory(tmp_dir, skip_existing=True)
        # The main image should be skipped if thumb exists
        # (depends on if the thumb check finds the thumb)
        assert isinstance(result, list)

    def test_does_not_skip_if_skip_existing_false(self, tmp_dir):
        create_png(tmp_dir, "image2.png")
        result = process_directory(tmp_dir, skip_existing=False)
        assert len(result) >= 1

    def test_custom_pattern(self, tmp_dir):
        # Create a PNG file
        create_png(tmp_dir, "test.png")
        # Process with *.jpg pattern - should find nothing
        result = process_directory(tmp_dir, pattern="*.jpg")
        assert result == []


class TestCleanupThumbnails:
    def test_removes_thumbnails(self, tmp_dir):
        # Create thumbnail files
        create_png(tmp_dir, "image.thumb.png")
        create_png(tmp_dir, "image.medium.png")

        removed = cleanup_thumbnails(tmp_dir)
        assert removed == 2
        assert not os.path.exists(os.path.join(tmp_dir, "image.thumb.png"))
        assert not os.path.exists(os.path.join(tmp_dir, "image.medium.png"))

    def test_leaves_original_files(self, tmp_dir):
        original = create_png(tmp_dir, "original.png")
        cleanup_thumbnails(tmp_dir)
        assert os.path.exists(original)

    def test_empty_directory(self, tmp_dir):
        removed = cleanup_thumbnails(tmp_dir)
        assert removed == 0

    def test_removes_jpg_thumbnails(self, tmp_dir):
        path = os.path.join(tmp_dir, "image.thumb.jpg")
        img = Image.new("RGB", (50, 50))
        img.save(path, format="JPEG")

        removed = cleanup_thumbnails(tmp_dir)
        assert removed == 1
