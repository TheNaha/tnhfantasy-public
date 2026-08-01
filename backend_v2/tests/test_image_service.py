"""Tests for services/image_service.py"""
import base64
import io
import os
import tempfile
from unittest.mock import patch

import pytest
from PIL import Image

import services.image_service as image_service_module
from services.image_service import ImageService, get_image_service


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_png_bytes():
    """Create a sample PNG image in bytes."""
    img = Image.new("RGB", (100, 80), color=(128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton between tests."""
    image_service_module._image_service = None
    yield
    image_service_module._image_service = None


class TestImageServiceInit:
    def test_init_with_custom_dir(self, tmp_dir):
        svc = ImageService(output_dir=tmp_dir)
        assert svc.output_dir == tmp_dir

    def test_init_defaults_to_env(self):
        with patch.dict(os.environ, {"OUTPUT_DIR": "/tmp/test_output"}):
            svc = ImageService()
            assert svc.output_dir == "/tmp/test_output"

    def test_init_without_env_uses_default(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove OUTPUT_DIR if present
            os.environ.pop("OUTPUT_DIR", None)
            svc = ImageService()
            assert svc.output_dir is not None


class TestSaveGeneratedImage:
    async def test_saves_image(self, tmp_dir, sample_png_bytes):
        svc = ImageService(output_dir=tmp_dir)
        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_thumbnail_sizes", return_value={"medium": 512}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_blurhash_components", return_value=(4, 3)), \
             patch("config.get_blurhash_resize_max", return_value=400), \
             patch("config.get_embed_metadata_in_png", return_value=True):
            result = await svc.save_generated_image(sample_png_bytes)

        assert "filename" in result
        assert "width" in result
        assert "height" in result
        assert result["width"] == 100
        assert result["height"] == 80

    async def test_auto_generates_filename(self, tmp_dir, sample_png_bytes):
        svc = ImageService(output_dir=tmp_dir)
        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_thumbnail_sizes", return_value={"medium": 512}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_blurhash_components", return_value=(4, 3)), \
             patch("config.get_blurhash_resize_max", return_value=400), \
             patch("config.get_embed_metadata_in_png", return_value=True):
            result = await svc.save_generated_image(sample_png_bytes)

        assert result["filename"].endswith(".png")
        assert "Generated_" in result["filename"]

    async def test_custom_filename(self, tmp_dir, sample_png_bytes):
        svc = ImageService(output_dir=tmp_dir)
        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_thumbnail_sizes", return_value={"medium": 512}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_blurhash_components", return_value=(4, 3)), \
             patch("config.get_blurhash_resize_max", return_value=400), \
             patch("config.get_embed_metadata_in_png", return_value=True):
            result = await svc.save_generated_image(
                sample_png_bytes, filename="custom_image.png"
            )

        assert result["filename"] == "custom_image.png"

    async def test_with_job_id(self, tmp_dir, sample_png_bytes):
        svc = ImageService(output_dir=tmp_dir)
        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_thumbnail_sizes", return_value={"medium": 512}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_blurhash_components", return_value=(4, 3)), \
             patch("config.get_blurhash_resize_max", return_value=400), \
             patch("config.get_embed_metadata_in_png", return_value=True):
            result = await svc.save_generated_image(
                sample_png_bytes, job_id="abc12345-def-ghi"
            )

        assert "abc12345" in result["filename"]

    async def test_with_metadata(self, tmp_dir, sample_png_bytes):
        svc = ImageService(output_dir=tmp_dir)
        metadata = {"prompt": "a beautiful landscape", "seed": 42}
        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_thumbnail_sizes", return_value={"medium": 512}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_blurhash_components", return_value=(4, 3)), \
             patch("config.get_blurhash_resize_max", return_value=400), \
             patch("config.get_embed_metadata_in_png", return_value=True):
            result = await svc.save_generated_image(sample_png_bytes, metadata=metadata)

        assert result is not None

    async def test_thumbnail_failure_handled_gracefully(self, tmp_dir, sample_png_bytes):
        svc = ImageService(output_dir=tmp_dir)
        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_embed_metadata_in_png", return_value=True), \
             patch("services.image_service.generate_thumbnails", side_effect=Exception("thumb error")), \
             patch("services.image_service.encode_blurhash", return_value="LKO2?U%2Tw=w]~RBVZRi};RPxuwH"):
            result = await svc.save_generated_image(sample_png_bytes)

        assert result is not None
        assert "thumbnail" not in result

    async def test_blurhash_failure_handled_gracefully(self, tmp_dir, sample_png_bytes):
        svc = ImageService(output_dir=tmp_dir)
        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_thumbnail_sizes", return_value={"medium": 512}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_embed_metadata_in_png", return_value=True), \
             patch("services.image_service.encode_blurhash", side_effect=Exception("hash error")):
            result = await svc.save_generated_image(sample_png_bytes)

        assert result is not None
        assert "blurhash" not in result

    async def test_returns_path_info(self, tmp_dir, sample_png_bytes):
        svc = ImageService(output_dir=tmp_dir)
        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_thumbnail_sizes", return_value={"medium": 512}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_blurhash_components", return_value=(4, 3)), \
             patch("config.get_blurhash_resize_max", return_value=400), \
             patch("config.get_embed_metadata_in_png", return_value=True):
            result = await svc.save_generated_image(sample_png_bytes)

        assert "path" in result
        assert "relative_path" in result


class TestSaveImagesFromBase64:
    async def test_saves_base64_images(self, tmp_dir, sample_png_bytes):
        svc = ImageService(output_dir=tmp_dir)
        b64_data = base64.b64encode(sample_png_bytes).decode()
        images = [{"data": b64_data}]

        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_thumbnail_sizes", return_value={"medium": 512}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_blurhash_components", return_value=(4, 3)), \
             patch("config.get_blurhash_resize_max", return_value=400), \
             patch("config.get_embed_metadata_in_png", return_value=True):
            results = await svc.save_images_from_base64(images, job_id="job-1")

        assert len(results) == 1

    async def test_saves_raw_base64_string(self, tmp_dir, sample_png_bytes):
        svc = ImageService(output_dir=tmp_dir)
        b64_data = base64.b64encode(sample_png_bytes).decode()

        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_thumbnail_sizes", return_value={"medium": 512}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_blurhash_components", return_value=(4, 3)), \
             patch("config.get_blurhash_resize_max", return_value=400), \
             patch("config.get_embed_metadata_in_png", return_value=True):
            results = await svc.save_images_from_base64([b64_data])

        assert len(results) == 1

    async def test_skips_invalid_base64(self, tmp_dir):
        svc = ImageService(output_dir=tmp_dir)
        images = [{"data": "INVALID_BASE64!!"}]

        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_embed_metadata_in_png", return_value=True):
            results = await svc.save_images_from_base64(images)

        assert len(results) == 0

    async def test_saves_multiple_images(self, tmp_dir, sample_png_bytes):
        svc = ImageService(output_dir=tmp_dir)
        b64_data = base64.b64encode(sample_png_bytes).decode()
        images = [{"data": b64_data}, {"data": b64_data}]

        with patch("config.get_output_date_hierarchy", return_value=False), \
             patch("config.get_thumbnail_sizes", return_value={"medium": 512}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_blurhash_components", return_value=(4, 3)), \
             patch("config.get_blurhash_resize_max", return_value=400), \
             patch("config.get_embed_metadata_in_png", return_value=True):
            results = await svc.save_images_from_base64(images, job_id="batch-job")

        assert len(results) == 2


class TestGetImageService:
    def test_returns_instance(self):
        svc = get_image_service()
        assert isinstance(svc, ImageService)

    def test_singleton(self):
        s1 = get_image_service()
        s2 = get_image_service()
        assert s1 is s2

    def test_creates_new_when_none(self):
        image_service_module._image_service = None
        svc = get_image_service()
        assert svc is not None
