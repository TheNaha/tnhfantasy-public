"""Additional workflow parser tests for uncovered edge cases."""
from core.workflow_parser import (
    MODEL_LOADER_NODES,
    extract_models_from_workflow,
    get_all_required_files,
    get_required_storage_paths,
)


class TestWorkflowParserEdgeCases:
    def test_node_data_not_a_dict_is_skipped(self):
        """Test that non-dict node values are skipped (line 79: continue)."""
        workflow = {
            "1": "string_node_data",  # Not a dict - should be skipped
            "2": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"}
            }
        }
        result = extract_models_from_workflow(workflow)
        assert "checkpoints" in result
        assert "model.safetensors" in result["checkpoints"]

    def test_node_data_integer_is_skipped(self):
        """Non-dict node data (integer) is skipped."""
        workflow = {
            "1": 42,
            "2": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model2.safetensors"}
            }
        }
        result = extract_models_from_workflow(workflow)
        assert "checkpoints" in result

    def test_node_data_none_is_skipped(self):
        """None node data is skipped gracefully."""
        workflow = {
            "1": None,
            "2": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model3.safetensors"}
            }
        }
        result = extract_models_from_workflow(workflow)
        # None is not a dict, should be skipped
        assert "checkpoints" in result

    def test_dual_clip_loader_multi_input(self):
        """Test DualCLIPLoader with two clip inputs (MULTI_INPUT_NODES coverage)."""
        workflow = {
            "1": {
                "class_type": "DualCLIPLoader",
                "inputs": {
                    "clip_name1": "clip1.safetensors",
                    "clip_name2": "clip2.safetensors"
                }
            }
        }
        result = extract_models_from_workflow(workflow)
        assert "clip" in result
        assert "clip1.safetensors" in result["clip"]
        assert "clip2.safetensors" in result["clip"]

    def test_dual_clip_loader_missing_second_input(self):
        """Test DualCLIPLoader with only one clip input."""
        workflow = {
            "1": {
                "class_type": "DualCLIPLoader",
                "inputs": {
                    "clip_name1": "clip1.safetensors"
                    # clip_name2 is missing
                }
            }
        }
        result = extract_models_from_workflow(workflow)
        assert "clip" in result
        assert "clip1.safetensors" in result["clip"]

    def test_all_model_loader_node_types(self):
        """Test all node types in MODEL_LOADER_NODES are handled."""
        for node_type, (input_key, directory) in MODEL_LOADER_NODES.items():
            workflow = {
                "1": {
                    "class_type": node_type,
                    "inputs": {input_key: f"model_{node_type}.safetensors"}
                }
            }
            result = extract_models_from_workflow(workflow)
            assert directory in result
            assert f"model_{node_type}.safetensors" in result[directory]

    def test_unet_loader(self):
        """Test UNETLoader node."""
        workflow = {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "flux_unet.safetensors"}
            }
        }
        result = extract_models_from_workflow(workflow)
        assert "unet" in result
        assert "flux_unet.safetensors" in result["unet"]

    def test_controlnet_loader(self):
        """Test ControlNetLoader node."""
        workflow = {
            "1": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": "control_sd.safetensors"}
            }
        }
        result = extract_models_from_workflow(workflow)
        assert "controlnet" in result

    def test_upscale_model_loader(self):
        """Test UpscaleModelLoader node."""
        workflow = {
            "1": {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": "4x-UltraSharp.pth"}
            }
        }
        result = extract_models_from_workflow(workflow)
        assert "upscale_models" in result

    def test_get_all_required_files_empty_workflow(self):
        """Test get_all_required_files with empty workflow."""
        result = get_all_required_files({})
        assert result == []

    def test_get_all_required_files_multiple(self):
        """Test get_all_required_files with multiple models."""
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"}
            },
            "2": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "style.safetensors"}
            }
        }
        result = get_all_required_files(workflow)
        assert len(result) == 2
        assert ("checkpoints", "model.safetensors") in result
        assert ("loras", "style.safetensors") in result

    def test_get_required_storage_paths_empty_workflow(self):
        """Test get_required_storage_paths with empty workflow."""
        result = get_required_storage_paths({})
        assert result == []

    def test_get_required_storage_paths_multiple(self):
        """Test get_required_storage_paths with multiple models."""
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"}
            },
            "2": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": "vae.safetensors"}
            }
        }
        result = get_required_storage_paths(workflow)
        assert "models/checkpoints/model.safetensors" in result
        assert "models/vae/vae.safetensors" in result
