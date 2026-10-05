"""Tests for infrastructure/image_processor.py"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from PIL import Image

from infrastructure.image_processor import (
    generate_thumbnails,
    get_image_dimensions,
    get_output_path,
    get_thumb_output_path,
    read_image_metadata,
    resize_image,
    save_image_with_metadata,
    write_metadata_sidecar,
)


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test images."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_image(tmp_dir):
    """Create a sample PNG image."""
    img = Image.new("RGB", (100, 80), color=(128, 64, 32))
    path = os.path.join(tmp_dir, "test.png")
    img.save(path)
    return path


@pytest.fixture
def sample_rgba_image(tmp_dir):
    """Create a sample RGBA PNG image."""
    img = Image.new("RGBA", (100, 80), color=(128, 64, 32, 200))
    path = os.path.join(tmp_dir, "test_rgba.png")
    img.save(path)
    return path


class TestGetOutputPath:
    def test_creates_directory(self, tmp_dir):
        path = get_output_path(base_dir=tmp_dir)
        assert os.path.exists(path)

    def test_with_subdir(self, tmp_dir):
        path = get_output_path(base_dir=tmp_dir, subdir="thumb")
        assert os.path.exists(path)
        assert "thumb" in path

    def test_no_date_hierarchy(self, tmp_dir):
        # Partition (/user_id/workspace/) is always applied; only the date
        # YYYY/MM/DD suffix is suppressed when the hierarchy is disabled.
        with patch("config.get_output_date_hierarchy", return_value=False):
            path = get_output_path(base_dir=tmp_dir)
            assert path == os.path.join(tmp_dir, "default_user", "main")
            assert os.path.exists(path)

    def test_with_date_hierarchy(self, tmp_dir):
        with patch("config.get_output_date_hierarchy", return_value=True):
            path = get_output_path(base_dir=tmp_dir)
            assert os.path.exists(path)

    def test_default_base_dir_uses_env(self, tmp_dir):
        with patch.dict(os.environ, {"OUTPUT_DIR": tmp_dir}):
            path = get_output_path()
            assert os.path.exists(path)


class TestSaveImageWithMetadata:
    def test_saves_image_with_metadata(self, tmp_dir, sample_image):
        img = Image.open(sample_image)
        path = os.path.join(tmp_dir, "output.png")
        metadata = {"workflow": {"node": 1}, "prompt": "test prompt"}
        result = save_image_with_metadata(img, path, metadata)
        assert os.path.exists(result)

    def test_embeds_workflow_metadata(self, tmp_dir, sample_image):
        img = Image.open(sample_image)
        path = os.path.join(tmp_dir, "output_meta.png")
        metadata = {"workflow": {"key": "value"}}
        save_image_with_metadata(img, path, metadata)

        with Image.open(path) as saved:
            assert "workflow" in saved.info or "comfy_metadata" in saved.info

    def test_embeds_comfy_metadata(self, tmp_dir, sample_image):
        img = Image.open(sample_image)
        path = os.path.join(tmp_dir, "output_comfy.png")
        metadata = {"test_key": "test_value"}
        save_image_with_metadata(img, path, metadata)

        with Image.open(path) as saved:
            assert "comfy_metadata" in saved.info
            parsed = json.loads(saved.info["comfy_metadata"])
            assert parsed["test_key"] == "test_value"

    def test_returns_path(self, tmp_dir, sample_image):
        img = Image.open(sample_image)
        path = os.path.join(tmp_dir, "output_ret.png")
        result = save_image_with_metadata(img, path, {})
        assert result == path

    def test_metadata_without_workflow(self, tmp_dir, sample_image):
        img = Image.open(sample_image)
        path = os.path.join(tmp_dir, "output_nw.png")
        metadata = {"prompt": "hello"}
        save_image_with_metadata(img, path, metadata)
        assert os.path.exists(path)


class TestReadImageMetadata:
    def test_reads_embedded_metadata(self, tmp_dir, sample_image):
        img = Image.open(sample_image)
        path = os.path.join(tmp_dir, "output.png")
        metadata = {"test": "embedded"}
        save_image_with_metadata(img, path, metadata)

        result = read_image_metadata(path)
        assert result["test"] == "embedded"

    def test_fallback_to_sidecar_json(self, tmp_dir):
        # Create image without embedded metadata
        img = Image.new("RGB", (50, 50), color=(0, 0, 0))
        path = os.path.join(tmp_dir, "plain.png")
        img.save(path)

        # Create sidecar JSON
        sidecar = {"source": "sidecar"}
        with open(f"{path}.json", "w") as f:
            json.dump(sidecar, f)

        result = read_image_metadata(path)
        assert result.get("source") == "sidecar"

    def test_returns_empty_if_no_metadata(self, tmp_dir):
        img = Image.new("RGB", (50, 50), color=(0, 0, 0))
        path = os.path.join(tmp_dir, "no_meta.png")
        img.save(path)
        result = read_image_metadata(path)
        assert result == {}

    def test_handles_missing_file_gracefully(self, tmp_dir):
        path = os.path.join(tmp_dir, "nonexistent.png")
        result = read_image_metadata(path)
        assert result == {}


class TestWriteMetadataSidecar:
    def test_writes_sidecar_json(self, tmp_dir):
        path = os.path.join(tmp_dir, "output.png")
        metadata = {"job_id": "job-1", "prompt": "test"}

        sidecar_path = write_metadata_sidecar(path, metadata)

        assert sidecar_path == f"{path}.json"
        with open(sidecar_path, "r", encoding="utf-8") as f:
            stored = json.load(f)
        assert stored == metadata


class TestGenerateThumbnails:
    def test_generates_thumbnail(self, tmp_dir, sample_image):
        with patch("config.get_thumbnail_sizes", return_value={"medium": 50}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_output_date_hierarchy", return_value=False):
            result = generate_thumbnails(sample_image, output_base_dir=tmp_dir)
        assert "medium" in result
        assert os.path.exists(result["medium"])

    def test_raises_if_image_not_found(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            generate_thumbnails(os.path.join(tmp_dir, "nonexistent.png"))

    def test_thumbnail_is_smaller_than_original(self, tmp_dir, sample_image):
        with patch("config.get_thumbnail_sizes", return_value={"medium": 50}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_output_date_hierarchy", return_value=False):
            result = generate_thumbnails(sample_image, output_base_dir=tmp_dir)
        with Image.open(result["medium"]) as thumb:
            assert max(thumb.size) <= 50

    def test_handles_rgba_image(self, tmp_dir, sample_rgba_image):
        with patch("config.get_thumbnail_sizes", return_value={"medium": 50}), \
             patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_output_date_hierarchy", return_value=False):
            result = generate_thumbnails(sample_rgba_image, output_base_dir=tmp_dir)
        assert "medium" in result

    def test_custom_sizes(self, tmp_dir, sample_image):
        with patch("config.get_thumbnail_format", return_value="webp"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_output_date_hierarchy", return_value=False):
            result = generate_thumbnails(
                sample_image,
                sizes={"small": 32},
                output_base_dir=tmp_dir
            )
        assert "small" in result

    def test_jpeg_format(self, tmp_dir, sample_image):
        with patch("config.get_thumbnail_sizes", return_value={"medium": 50}), \
             patch("config.get_thumbnail_format", return_value="jpg"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_output_date_hierarchy", return_value=False):
            result = generate_thumbnails(sample_image, output_base_dir=tmp_dir)
        assert "medium" in result

    def test_png_format(self, tmp_dir, sample_image):
        with patch("config.get_thumbnail_sizes", return_value={"medium": 50}), \
             patch("config.get_thumbnail_format", return_value="png"), \
             patch("config.get_thumbnail_directory", return_value="thumb"), \
             patch("config.get_thumbnail_quality", return_value=85), \
             patch("config.get_output_date_hierarchy", return_value=False):
            result = generate_thumbnails(sample_image, output_base_dir=tmp_dir)
        assert "medium" in result


class TestGetImageDimensions:
    def test_returns_correct_dimensions(self, sample_image):
        w, h = get_image_dimensions(sample_image)
        assert w == 100
        assert h == 80

    def test_correct_tuple_format(self, sample_image):
        result = get_image_dimensions(sample_image)
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestResizeImage:
    def test_resizes_image(self, tmp_dir, sample_image):
        output = os.path.join(tmp_dir, "resized.jpg")
        result = resize_image(sample_image, 50, output_path=output)
        with Image.open(result) as img:
            assert max(img.size) <= 50

    def test_overwrites_in_place_when_no_output_path(self, tmp_dir):
        img = Image.new("RGB", (200, 200), color=(100, 100, 100))
        path = os.path.join(tmp_dir, "big.jpg")
        img.save(path)
        resize_image(path, 50)
        with Image.open(path) as resized:
            assert max(resized.size) <= 50

    def test_handles_rgba(self, tmp_dir, sample_rgba_image):
        output = os.path.join(tmp_dir, "resized_rgba.jpg")
        result = resize_image(sample_rgba_image, 50, output_path=output)
        assert os.path.exists(result)

    def test_returns_output_path(self, tmp_dir, sample_image):
        output = os.path.join(tmp_dir, "out.jpg")
        result = resize_image(sample_image, 50, output_path=output)
        assert result == output


# ---------------------------------------------------------------------------
# Date partition is UTC, because Asset.created_at is UTC
# ---------------------------------------------------------------------------


class _HostDatetime:
    """`datetime` stand-in whose naive `now()` is the HOST's local wall clock.

    The production container runs UTC, so `datetime.now()` and
    `datetime.now(timezone.utc)` return the same thing there — which is exactly
    why a local-time call in this path survived review and shipping. This fakes
    a host that is genuinely ahead of UTC (UTC+2) at 23:30 local, i.e. the one
    moment of day where the two disagree about which day it is.
    """

    LOCAL_OFFSET_HOURS = 2
    # 23:30 UTC on a UTC+2 host is already 01:30 the NEXT day locally: the one
    # window where the two disagree about which day it is.
    INSTANT = datetime(2026, 3, 14, 23, 30, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        # tz=None is what a naive caller gets: the host's LOCAL wall clock.
        # A tz-aware caller gets the same instant expressed in that zone.
        if tz is None:
            return (cls.INSTANT + timedelta(hours=cls.LOCAL_OFFSET_HOURS)).replace(tzinfo=None)
        return cls.INSTANT.astimezone(tz)

    @classmethod
    def utcnow(cls):
        return cls.INSTANT.replace(tzinfo=None)

    def __getattr__(self, item):
        return getattr(datetime, item)

    def __class_getitem__(cls, item):
        return datetime[item]


def test_output_date_partition_uses_the_utc_day_not_the_local_day(tmp_dir):
    """The partition must agree with the `created_at` the row is stored with.

    `Asset.created_at` is a UTC column and the gallery's date rail buckets on
    UTC. With a local `now()`, an image generated at 23:30 in UTC+2 was filed
    under *tomorrow's* directory while its `created_at` read 21:30 the same
    day — so the on-disk tree and the UI disagreed for every image in the
    offset window around local midnight, and neither was wrong on its own.
    """
    with patch("config.get_output_date_hierarchy", return_value=True), patch(
        "infrastructure.image_processor.datetime", _HostDatetime
    ):
        path = get_output_path(base_dir=tmp_dir)

    # The host clock really was on the next day; otherwise this proves nothing.
    assert _HostDatetime.now().date() == datetime(2026, 3, 15).date()

    utc_today = _HostDatetime.INSTANT
    assert path.endswith(
        os.path.join(
            str(utc_today.year), f"{utc_today.month:02d}", f"{utc_today.day:02d}"
        )
    ), (
        "partitioned under the LOCAL date, which disagrees with the UTC "
        "created_at the row is written with"
    )


def test_thumbnail_partition_matches_the_full_size_partition(tmp_dir):
    """The two must not disagree either — the thumb mirrors the image tree."""
    with patch("config.get_output_date_hierarchy", return_value=True), patch(
        "infrastructure.image_processor.datetime", _HostDatetime
    ):
        image_dir = get_output_path(base_dir=tmp_dir)
        thumb_dir = get_thumb_output_path(base_dir=tmp_dir)

    # image_dir ends .../<y>/<m>/<d>; thumb_dir ends .../thumb/<y>/<m>/<d>.
    assert image_dir.split(os.sep)[-3:] == thumb_dir.split(os.sep)[-3:]
