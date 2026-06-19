"""Tests for helper functions in api/routes/files.py"""
import os
import pytest
from core.exceptions import ValidationError


class TestGetSafePath:
    def test_simple_path(self, tmp_path):
        from api.routes.files import get_safe_path
        result = get_safe_path(str(tmp_path), "subdir/file.txt")
        assert result == str(tmp_path / "subdir" / "file.txt")

    def test_path_within_base(self, tmp_path):
        from api.routes.files import get_safe_path
        result = get_safe_path(str(tmp_path), "a/b/c.txt")
        assert str(tmp_path) in result

    def test_traversal_raises_403(self, tmp_path):
        from api.routes.files import get_safe_path
        with pytest.raises(ValidationError):
            get_safe_path(str(tmp_path), "../../etc/passwd")

    def test_leading_slash_stripped(self, tmp_path):
        from api.routes.files import get_safe_path
        result = get_safe_path(str(tmp_path), "/file.txt")
        assert result == str(tmp_path / "file.txt")

    def test_empty_path(self, tmp_path):
        from api.routes.files import get_safe_path
        with pytest.raises(ValidationError):
            get_safe_path(str(tmp_path), "")

        with pytest.raises(ValidationError):
            get_safe_path(str(tmp_path), "/")

        with pytest.raises(ValidationError):
            get_safe_path(str(tmp_path), "\\")

    def test_same_dir(self, tmp_path):
        from api.routes.files import get_safe_path
        result = get_safe_path(str(tmp_path), ".")
        # This is valid (same directory)
        assert str(tmp_path) in result


class TestEncodeFilenameForHeader:
    def test_ascii_filename(self):
        from api.routes.files import encode_filename_for_header
        result = encode_filename_for_header("model.safetensors")
        assert "model.safetensors" in result
        assert "UTF-8" in result

    def test_unicode_filename(self):
        from api.routes.files import encode_filename_for_header
        result = encode_filename_for_header("模型.safetensors")
        assert "UTF-8" in result

    def test_filename_with_spaces(self):
        from api.routes.files import encode_filename_for_header
        result = encode_filename_for_header("my model.safetensors")
        assert "UTF-8" in result

    def test_filename_with_special_chars(self):
        from api.routes.files import encode_filename_for_header
        result = encode_filename_for_header("my-model (v2).safetensors")
        assert "UTF-8" in result


class TestMatchesSearch:
    def test_no_query_matches_all(self):
        from api.routes.files import matches_search
        assert matches_search({"name": "test"}, "") is True
        assert matches_search({"name": "test"}, None) is True

    def test_matches_by_name(self):
        from api.routes.files import matches_search
        item = {"name": "my_model.safetensors", "metadata": {}}
        assert matches_search(item, "my_model") is True

    def test_no_match_by_name(self):
        from api.routes.files import matches_search
        item = {"name": "my_model.safetensors", "metadata": {}}
        assert matches_search(item, "zzz_nomatch_xyz") is False

    def test_matches_by_metadata_str(self):
        from api.routes.files import matches_search
        item = {"name": "model.safetensors", "metadata": {"author": "john_doe"}}
        assert matches_search(item, "john_doe") is True

    def test_matches_by_metadata_list(self):
        from api.routes.files import matches_search
        item = {"name": "model.safetensors", "metadata": {"tags": ["anime", "realistic"]}}
        assert matches_search(item, "anime") is True

    def test_no_match_in_metadata(self):
        from api.routes.files import matches_search
        item = {"name": "model.safetensors", "metadata": {"author": "john"}}
        assert matches_search(item, "zzz_nomatch_xyz") is False

    def test_string_item_match(self):
        from api.routes.files import matches_search
        assert matches_search("test_filename.png", "test") is True

    def test_string_item_no_match(self):
        from api.routes.files import matches_search
        assert matches_search("test_filename.png", "zzz_nomatch_xyz") is False

    def test_unknown_type_returns_false(self):
        from api.routes.files import matches_search
        assert matches_search(12345, "test") is False

    def test_case_insensitive_match(self):
        from api.routes.files import matches_search
        item = {"name": "MyModel.SAFETENSORS", "metadata": {}}
        assert matches_search(item, "mymodel") is True


class TestFilesRouteEndpoints:
    def test_list_files(self, client):
        response = client.get("/api/files")
        assert response.status_code == 200

    def test_list_files_with_params(self, client):
        response = client.get("/api/files?limit=10&offset=0")
        assert response.status_code == 200

    def test_view_nonexistent_file(self, client):
        response = client.get("/api/view/output/nonexistent_file.png")
        assert response.status_code in (200, 404)

    def test_batch_metadata_empty(self, client):
        response = client.post("/api/files/metadata/batch", json={"paths": []})
        assert response.status_code in (200, 422)
