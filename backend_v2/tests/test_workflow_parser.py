# Workflow Parser Tests
from core.workflow_parser import (
    extract_models_from_workflow,
    get_all_required_files,
    get_required_storage_paths,
)


class TestExtractModelsFromWorkflow:
    """Tests for extract_models_from_workflow function."""
    
    def test_empty_workflow(self):
        """Empty workflow returns empty dict."""
        result = extract_models_from_workflow({})
        assert result == {}
    
    def test_no_loader_nodes(self):
        """Workflow without loader nodes returns empty dict."""
        workflow = {
            "1": {"class_type": "KSampler", "inputs": {"seed": 12345}},
            "2": {"class_type": "VAEDecode", "inputs": {}},
        }
        result = extract_models_from_workflow(workflow)
        assert result == {}
    
    def test_checkpoint_loader_simple(self):
        """Extract checkpoint from CheckpointLoaderSimple."""
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"}
            }
        }
        result = extract_models_from_workflow(workflow)
        assert result == {"checkpoints": ["model.safetensors"]}
    
    def test_lora_loader(self):
        """Extract LoRA from LoraLoader."""
        workflow = {
            "1": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "my_lora.safetensors", "strength_model": 1.0}
            }
        }
        result = extract_models_from_workflow(workflow)
        assert result == {"loras": ["my_lora.safetensors"]}
    
    def test_multiple_loras(self):
        """Extract multiple LoRAs from chained loaders."""
        workflow = {
            "1": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "lora1.safetensors"}
            },
            "2": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "lora2.safetensors"}
            },
            "3": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "lora3.safetensors"}
            }
        }
        result = extract_models_from_workflow(workflow)
        assert "loras" in result
        assert len(result["loras"]) == 3
        assert set(result["loras"]) == {"lora1.safetensors", "lora2.safetensors", "lora3.safetensors"}
    
    def test_mixed_loaders(self):
        """Extract models from mixed loader types."""
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "checkpoint.safetensors"}
            },
            "2": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "lora.safetensors"}
            },
            "3": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": "vae.pt"}
            }
        }
        result = extract_models_from_workflow(workflow)
        assert result == {
            "checkpoints": ["checkpoint.safetensors"],
            "loras": ["lora.safetensors"],
            "vae": ["vae.pt"]
        }
    
    def test_duplicate_models(self):
        """Duplicate model references are deduplicated."""
        workflow = {
            "1": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "same_lora.safetensors"}
            },
            "2": {
                "class_type": "LoraLoader",
                "inputs": {"lora_name": "same_lora.safetensors"}
            }
        }
        result = extract_models_from_workflow(workflow)
        assert result == {"loras": ["same_lora.safetensors"]}
    
    def test_nested_nodes_structure(self):
        """Handle workflow with 'nodes' wrapper."""
        workflow = {
            "nodes": {
                "1": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "model.safetensors"}
                }
            }
        }
        result = extract_models_from_workflow(workflow)
        assert result == {"checkpoints": ["model.safetensors"]}
    
    def test_list_format_nodes(self):
        """Handle workflow with list-format nodes."""
        workflow = {
            "nodes": [
                {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
                {"class_type": "LoraLoader", "inputs": {"lora_name": "lora.safetensors"}}
            ]
        }
        result = extract_models_from_workflow(workflow)
        assert "checkpoints" in result
        assert "loras" in result
    
    def test_missing_inputs(self):
        """Handle nodes with missing inputs gracefully."""
        workflow = {
            "1": {"class_type": "CheckpointLoaderSimple"},  # No inputs key
            "2": {"class_type": "CheckpointLoaderSimple", "inputs": {}},  # Empty inputs
        }
        result = extract_models_from_workflow(workflow)
        assert result == {}
    
    def test_non_string_model_name(self):
        """Ignore non-string model names (e.g., linked inputs)."""
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": ["other_node", 0]}  # Link reference
            }
        }
        result = extract_models_from_workflow(workflow)
        assert result == {}


class TestGetAllRequiredFiles:
    """Tests for get_all_required_files function."""
    
    def test_returns_tuples(self):
        """Returns list of (directory, filename) tuples."""
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"}
            }
        }
        result = get_all_required_files(workflow)
        assert result == [("checkpoints", "model.safetensors")]


class TestGetRequiredStoragePaths:
    """Tests for get_required_storage_paths function."""
    
    def test_returns_paths(self):
        """Returns storage path strings."""
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"}
            }
        }
        result = get_required_storage_paths(workflow)
        assert result == ["models/checkpoints/model.safetensors"]
