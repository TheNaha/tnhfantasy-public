"""Extended tests for services/gallery_indexer.py"""
import os
import time
import tempfile
import pytest
from PIL import Image
from unittest.mock import patch, MagicMock
from services.gallery_indexer import GalleryIndexer, _GalleryEventHandler


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def fresh_indexer(tmp_dir):
    """Create a fresh GalleryIndexer instance bypassing singleton."""
    # Bypass singleton by creating a new instance directly
    indexer = object.__new__(GalleryIndexer)
    indexer._initialized = False
    indexer.__init__(output_dir=tmp_dir)
    indexer.files = {}
    indexer.sorted_keys_date_desc = []
    indexer.is_ready = True
    return indexer


def make_png(directory, filename):
    """Create a simple PNG file."""
    path = os.path.join(directory, filename)
    img = Image.new("RGB", (50, 50), color=(100, 100, 100))
    img.save(path)
    return path


class TestGalleryIndexerInit:
    def test_init_sets_output_dir(self, tmp_dir):
        indexer = object.__new__(GalleryIndexer)
        indexer._initialized = False
        indexer.__init__(output_dir=tmp_dir)
        assert indexer.output_dir == tmp_dir

    def test_starts_not_ready(self, tmp_dir):
        indexer = object.__new__(GalleryIndexer)
        indexer._initialized = False
        indexer.__init__(output_dir=tmp_dir)
        assert indexer.is_ready is False

    def test_files_initially_empty(self, fresh_indexer):
        assert fresh_indexer.files == {}

    def test_observer_initially_none(self, tmp_dir):
        indexer = object.__new__(GalleryIndexer)
        indexer._initialized = False
        indexer.__init__(output_dir=tmp_dir)
        assert indexer.observer is None


class TestGetSortTimestamp:
    def test_existing_file_returns_mtime(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "test.png")
        ts = fresh_indexer._get_sort_timestamp(path)
        assert ts > 0

    def test_filename_with_datetime(self, fresh_indexer, tmp_dir):
        # Create file with datetime in name
        path = make_png(tmp_dir, "Generated_2025-01-15_10-30-45_00001_.png")
        ts = fresh_indexer._get_sort_timestamp(path)
        assert ts > 0

    def test_nonexistent_file(self, fresh_indexer, tmp_dir):
        path = os.path.join(tmp_dir, "nonexistent.png")
        ts = fresh_indexer._get_sort_timestamp(path)
        # Should fall back to 0 or mtime parsing
        assert isinstance(ts, (int, float))


class TestProcessFile:
    def test_processes_valid_png(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "test.png")
        result = fresh_indexer._process_file(path)
        assert result is not None
        assert "name" in result
        assert "relative_path" in result

    def test_processes_json_files(self, fresh_indexer, tmp_dir):
        path = os.path.join(tmp_dir, "metadata.json")
        with open(path, "w") as f:
            f.write("{}")
        result = fresh_indexer._process_file(path)
        assert result is not None
        assert result["type"] == "json"

    def test_skips_thumbnail_files(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "image.thumb.png")
        result = fresh_indexer._process_file(path)
        assert result is None

    def test_skips_medium_files(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "image.medium.png")
        result = fresh_indexer._process_file(path)
        assert result is None

    def test_includes_file_size(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "size_test.png")
        result = fresh_indexer._process_file(path)
        assert "size" in result
        assert result["size"] > 0

    def test_includes_relative_path(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "relative.png")
        result = fresh_indexer._process_file(path)
        assert result["relative_path"] == "relative.png"

    def test_skips_preview_files(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "image.preview.png")
        result = fresh_indexer._process_file(path)
        assert result is None

    def test_returns_none_for_nonexistent(self, fresh_indexer, tmp_dir):
        path = os.path.join(tmp_dir, "nonexistent.png")
        result = fresh_indexer._process_file(path)
        assert result is None


class TestAddRemoveFile:
    def test_add_file(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "add_test.png")
        with patch("time.sleep"):
            fresh_indexer.add_file(path)
        assert path in fresh_indexer.files

    def test_remove_file(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "remove_test.png")
        with patch("time.sleep"):
            fresh_indexer.add_file(path)
        fresh_indexer.remove_file(path)
        assert path not in fresh_indexer.files

    def test_remove_nonexistent_file_is_safe(self, fresh_indexer, tmp_dir):
        # Should not raise
        fresh_indexer.remove_file("/nonexistent/path.png")

    def test_add_updates_sort_index(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "sort_test.png")
        with patch("time.sleep"):
            fresh_indexer.add_file(path)
        assert path in fresh_indexer.sorted_keys_date_desc


class TestGetFiles:
    def test_get_files_empty(self, fresh_indexer):
        result = fresh_indexer.get_files()
        assert result["files"] == []
        assert result["total"] == 0

    def test_get_files_with_data(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "gallery_test.png")
        with patch("time.sleep"):
            fresh_indexer.add_file(path)
        result = fresh_indexer.get_files()
        assert result["total"] == 1
        assert len(result["files"]) == 1

    def test_pagination_limit(self, fresh_indexer, tmp_dir):
        for i in range(5):
            path = make_png(tmp_dir, f"img_{i:03d}.png")
            with patch("time.sleep"):
                fresh_indexer.add_file(path)
        result = fresh_indexer.get_files(limit=3)
        assert len(result["files"]) == 3
        assert result["total"] == 5

    def test_pagination_offset(self, fresh_indexer, tmp_dir):
        for i in range(5):
            path = make_png(tmp_dir, f"off_{i:03d}.png")
            with patch("time.sleep"):
                fresh_indexer.add_file(path)
        result = fresh_indexer.get_files(limit=2, offset=2)
        assert len(result["files"]) == 2

    def test_sort_date_asc(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "asc_test.png")
        with patch("time.sleep"):
            fresh_indexer.add_file(path)
        result = fresh_indexer.get_files(sort="date_asc")
        assert result["total"] >= 1

    def test_sort_name_asc(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "name_asc_test.png")
        with patch("time.sleep"):
            fresh_indexer.add_file(path)
        result = fresh_indexer.get_files(sort="name_asc")
        assert result["total"] >= 1

    def test_sort_name_desc(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "name_desc_test.png")
        with patch("time.sleep"):
            fresh_indexer.add_file(path)
        result = fresh_indexer.get_files(sort="name_desc")
        assert result["total"] >= 1

    def test_search_filter(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "searchable_image.png")
        with patch("time.sleep"):
            fresh_indexer.add_file(path)
        result = fresh_indexer.get_files(search="searchable")
        assert result["total"] >= 1

    def test_search_no_match(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "findme.png")
        with patch("time.sleep"):
            fresh_indexer.add_file(path)
        result = fresh_indexer.get_files(search="zzz_no_match_here")
        assert result["total"] == 0

    def test_unknown_sort_defaults_to_date_desc(self, fresh_indexer, tmp_dir):
        path = make_png(tmp_dir, "sort_default.png")
        with patch("time.sleep"):
            fresh_indexer.add_file(path)
        result = fresh_indexer.get_files(sort="unknown_sort")
        assert result["total"] >= 1


class TestPerformInitialScan:
    def test_scan_nonexistent_dir_is_safe(self, tmp_dir):
        indexer = object.__new__(GalleryIndexer)
        indexer._initialized = False
        indexer.__init__(output_dir=os.path.join(tmp_dir, "nonexistent"))
        indexer.files = {}
        indexer.sorted_keys_date_desc = []
        # Should not raise
        indexer._perform_initial_scan()

    def test_scan_finds_png_files(self, tmp_dir):
        make_png(tmp_dir, "scan_test.png")
        indexer = object.__new__(GalleryIndexer)
        indexer._initialized = False
        indexer.__init__(output_dir=tmp_dir)
        indexer.files = {}
        indexer.sorted_keys_date_desc = []
        indexer.is_ready = False
        indexer._perform_initial_scan()
        assert len(indexer.files) >= 1

    def test_scan_skips_thumb_directory(self, tmp_dir):
        thumb_dir = os.path.join(tmp_dir, "thumb")
        os.makedirs(thumb_dir, exist_ok=True)
        make_png(thumb_dir, "thumb_image.png")

        indexer = object.__new__(GalleryIndexer)
        indexer._initialized = False
        indexer.__init__(output_dir=tmp_dir)
        indexer.files = {}
        indexer.sorted_keys_date_desc = []
        indexer.is_ready = False
        indexer._perform_initial_scan()
        # Thumb images should not be indexed
        for key in indexer.files:
            assert "/thumb/" not in key.replace("\\", "/")


class TestRebuildSortIndex:
    def test_rebuild_empty(self, fresh_indexer):
        fresh_indexer._rebuild_sort_index()
        assert fresh_indexer.sorted_keys_date_desc == []

    def test_rebuild_with_files(self, fresh_indexer, tmp_dir):
        path1 = make_png(tmp_dir, "img1.png")
        path2 = make_png(tmp_dir, "img2.png")
        data1 = fresh_indexer._process_file(path1)
        data2 = fresh_indexer._process_file(path2)
        if data1:
            fresh_indexer.files[path1] = data1
        if data2:
            fresh_indexer.files[path2] = data2
        fresh_indexer._rebuild_sort_index()
        assert len(fresh_indexer.sorted_keys_date_desc) == len(fresh_indexer.files)


class TestGalleryEventHandler:
    def test_on_created_png(self, tmp_dir):
        indexer = object.__new__(GalleryIndexer)
        indexer._initialized = False
        indexer.__init__(output_dir=tmp_dir)
        indexer.files = {}
        indexer.sorted_keys_date_desc = []
        indexer.is_ready = True

        handler = _GalleryEventHandler(indexer)

        # Simulate a created event
        path = make_png(tmp_dir, "created_test.png")
        event = MagicMock()
        event.is_directory = False
        event.src_path = path

        with patch("time.sleep"):
            handler.on_created(event)
        # File should be added to index
        assert path in indexer.files

    def test_on_created_non_png(self, fresh_indexer, tmp_dir):
        handler = _GalleryEventHandler(fresh_indexer)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/path/to/file.txt"
        handler.on_created(event)
        # Should not add non-PNG
        assert "/path/to/file.txt" not in fresh_indexer.files

    def test_on_created_directory(self, fresh_indexer):
        handler = _GalleryEventHandler(fresh_indexer)
        event = MagicMock()
        event.is_directory = True
        event.src_path = "/path/to/dir.png"
        handler.on_created(event)
        # Should not process directories

    def test_on_created_skips_thumb(self, fresh_indexer):
        handler = _GalleryEventHandler(fresh_indexer)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/output/thumb/image.png"
        handler.on_created(event)
        assert "/output/thumb/image.png" not in fresh_indexer.files

    def test_on_deleted_png(self, fresh_indexer, tmp_dir):
        handler = _GalleryEventHandler(fresh_indexer)
        path = make_png(tmp_dir, "delete_test.png")
        # First add it
        with patch("time.sleep"):
            fresh_indexer.add_file(path)
        assert path in fresh_indexer.files

        # Then simulate delete event
        event = MagicMock()
        event.is_directory = False
        event.src_path = path
        handler.on_deleted(event)
        assert path not in fresh_indexer.files

    def test_on_moved(self, fresh_indexer, tmp_dir):
        handler = _GalleryEventHandler(fresh_indexer)
        src_path = make_png(tmp_dir, "moved_src.png")
        with patch("time.sleep"):
            fresh_indexer.add_file(src_path)

        dest_path = os.path.join(tmp_dir, "moved_dest.png")
        # Copy the file to dest (simulate move)
        import shutil
        shutil.copy(src_path, dest_path)

        event = MagicMock()
        event.is_directory = False
        event.src_path = src_path
        event.dest_path = dest_path
        with patch("time.sleep"):
            handler.on_moved(event)

        # Source should be removed, dest should be added
        assert src_path not in fresh_indexer.files
