"""Tests for memory_snapshot_helper prestartup_script.py"""
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def setup_memory_snapshot_mocks():
    """Mock dependencies and prevent module-level execution."""
    # Mock server module
    mock_server = MagicMock()
    mock_server.PromptServer = MagicMock()
    mock_server.PromptServer.instance = MagicMock()
    mock_server.PromptServer.instance.routes = MagicMock()
    mock_server.PromptServer.instance.routes.post = MagicMock(return_value=lambda f: f)
    sys.modules["server"] = mock_server

    # Remove cached modules so they can be re-imported
    for key in list(sys.modules.keys()):
        if "memory_snapshot_helper" in key:
            del sys.modules[key]

    yield

    # Cleanup
    if "server" in sys.modules and sys.modules["server"] is mock_server:
        del sys.modules["server"]
    for key in list(sys.modules.keys()):
        if "memory_snapshot_helper" in key:
            del sys.modules[key]


class TestMemorySnapshotHelperPrestartup:
    """Tests for memory_snapshot_helper/prestartup_script.py."""

    def _import_ps_with_patched(self, tmp_path):
        """Import prestartup_script with is_patched=True to skip module-level execution."""
        comfy_dir = tmp_path / "comfy"
        comfy_dir.mkdir()

        # Import with is_patched=True to skip the module-level patch call
        with patch("os.path.exists", return_value=True):
            import memory_snapshot_helper.prestartup_script as ps
        return ps, comfy_dir

    def test_apply_cuda_safe_patch_applies_patch(self, tmp_path):
        """Test that _apply_cuda_safe_patch modifies model_management.py correctly."""
        comfy_dir = tmp_path / "comfy"
        comfy_dir.mkdir()

        model_management_content = (
            "import torch\n"
            "import logging\n\n"
            "def get_torch_device():\n"
            "    return torch.device(torch.cuda.current_device())\n"
        )
        model_management_path = comfy_dir / "model_management.py"
        model_management_path.write_text(model_management_content)
        original_path = comfy_dir / "model_management_original.py"

        with patch("os.path.exists", return_value=True):
            import memory_snapshot_helper.prestartup_script as ps

        with patch.object(ps, "model_management_path", str(model_management_path)), \
             patch.object(ps, "original_model_management_path", str(original_path)):
            ps._apply_cuda_safe_patch()

        # Check backup was created
        assert original_path.exists()
        # Check patch was applied
        patched_content = model_management_path.read_text()
        assert "is_available" in patched_content

    def test_apply_cuda_safe_patch_raises_if_target_not_found(self, tmp_path):
        """Test that _apply_cuda_safe_patch raises if the target string is not found."""
        comfy_dir = tmp_path / "comfy"
        comfy_dir.mkdir()

        model_management_path = comfy_dir / "model_management.py"
        model_management_path.write_text("# No target string here\n")
        original_path = comfy_dir / "model_management_original.py"

        with patch("os.path.exists", return_value=True):
            import memory_snapshot_helper.prestartup_script as ps

        with patch.object(ps, "model_management_path", str(model_management_path)), \
             patch.object(ps, "original_model_management_path", str(original_path)):
            with pytest.raises(Exception, match="Failed to patch"):
                ps._apply_cuda_safe_patch()


class TestMemorySnapshotHelperInit:
    """Tests for memory_snapshot_helper/__init__.py"""

    def test_node_class_mappings_empty(self):
        """Test that NODE_CLASS_MAPPINGS is an empty dict."""
        with patch("os.path.exists", return_value=True):
            import memory_snapshot_helper
        assert memory_snapshot_helper.NODE_CLASS_MAPPINGS == {}
