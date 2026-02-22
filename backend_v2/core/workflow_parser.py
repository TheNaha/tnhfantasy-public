# Workflow Parser - Extract model references from ComfyUI workflows
"""
Utility to parse ComfyUI workflow JSON and extract model filenames.
Used for pre-flight validation to check if required models are available on providers.
"""
from typing import Dict, List, Any, Set

# Node types that load model files, mapped to (input_key, directory)
MODEL_LOADER_NODES: Dict[str, tuple[str, str]] = {
    # Checkpoint loaders
    "CheckpointLoaderSimple": ("ckpt_name", "checkpoints"),
    "CheckpointLoader": ("ckpt_name", "checkpoints"),
    "unCLIPCheckpointLoader": ("ckpt_name", "checkpoints"),
    
    # UNET loaders
    "UNETLoader": ("unet_name", "unet"),
    
    # LoRA loaders
    "LoraLoader": ("lora_name", "loras"),
    "LoraLoaderModelOnly": ("lora_name", "loras"),
    
    # VAE loaders
    "VAELoader": ("vae_name", "vae"),
    
    # ControlNet loaders
    "ControlNetLoader": ("control_net_name", "controlnet"),
    "DiffControlNetLoader": ("control_net_name", "controlnet"),
    
    # Upscale model loaders
    "UpscaleModelLoader": ("model_name", "upscale_models"),
    
    # CLIP loaders
    "CLIPLoader": ("clip_name", "clip"),
    "DualCLIPLoader": ("clip_name1", "clip"),  # Has two inputs
    
    # Hypernetwork
    "HypernetworkLoader": ("hypernetwork_name", "hypernetworks"),
    
    # GLIGEN
    "GLIGENLoader": ("gligen_name", "gligen"),
    
    # Style models
    "StyleModelLoader": ("style_model_name", "style_models"),
    
    # Embeddings/Textual Inversion are typically loaded by name reference in prompts
    # Not file-based in the same way, so we skip them for now
}

# Nodes with multiple model inputs
MULTI_INPUT_NODES: Dict[str, List[tuple[str, str]]] = {
    "DualCLIPLoader": [("clip_name1", "clip"), ("clip_name2", "clip")],
}


def extract_models_from_workflow(workflow: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Extract model filenames from a ComfyUI workflow.
    
    Args:
        workflow: ComfyUI workflow dictionary
        
    Returns:
        Dictionary mapping directory names to lists of model filenames.
        Example: {"checkpoints": ["model.safetensors"], "loras": ["lora1.safetensors"]}
    """
    result: Dict[str, Set[str]] = {}
    
    # Get nodes from workflow - handle both formats
    # Format 1: {"nodes": {...}} or {"nodes": [...]}
    # Format 2: Direct node dict {"1": {...}, "2": {...}}
    nodes = workflow.get("nodes", workflow)
    
    # If nodes is a list (from some workflow formats), convert to dict
    if isinstance(nodes, list):
        nodes = {str(i): node for i, node in enumerate(nodes)}
    
    for node_id, node_data in nodes.items():
        if not isinstance(node_data, dict):
            continue
            
        class_type = node_data.get("class_type", "")
        inputs = node_data.get("inputs", {})
        
        # Check for single-input model loaders
        if class_type in MODEL_LOADER_NODES:
            input_key, directory = MODEL_LOADER_NODES[class_type]
            model_name = inputs.get(input_key)
            
            if model_name and isinstance(model_name, str):
                if directory not in result:
                    result[directory] = set()
                result[directory].add(model_name)
        
        # Check for multi-input model loaders
        if class_type in MULTI_INPUT_NODES:
            for input_key, directory in MULTI_INPUT_NODES[class_type]:
                model_name = inputs.get(input_key)
                
                if model_name and isinstance(model_name, str):
                    if directory not in result:
                        result[directory] = set()
                    result[directory].add(model_name)
    
    # Convert sets to sorted lists for consistent output
    return {dir_name: sorted(list(files)) for dir_name, files in result.items()}


def get_all_required_files(workflow: Dict[str, Any]) -> List[tuple[str, str]]:
    """
    Get all required model files as a flat list of (directory, filename) tuples.
    
    Args:
        workflow: ComfyUI workflow dictionary
        
    Returns:
        List of (directory, filename) tuples
    """
    models = extract_models_from_workflow(workflow)
    result = []
    
    for directory, filenames in models.items():
        for filename in filenames:
            result.append((directory, filename))
    
    return result


def get_required_storage_paths(workflow: Dict[str, Any]) -> List[str]:
    """
    Get all required model files as storage paths.
    
    Args:
        workflow: ComfyUI workflow dictionary
        
    Returns:
        List of storage paths like "models/checkpoints/model.safetensors"
    """
    models = extract_models_from_workflow(workflow)
    result = []
    
    for directory, filenames in models.items():
        for filename in filenames:
            result.append(f"models/{directory}/{filename}")
    
    return result
