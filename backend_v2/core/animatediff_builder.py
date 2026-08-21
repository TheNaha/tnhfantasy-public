import math
from typing import Any, Optional

def build_animatediff_workflow(
    prompt: str,
    negative: str = "worst quality, low quality, bad anatomy, bad hands, missing fingers, extra limbs, extra digit, text, signature, watermark, username",
    checkpoint: str = "sd_xl_base_1.0.safetensors",
    motion_model: str = "mm_sdxl_v10_beta.ckpt",
    filename_prefix: str = "ComfyUI_Video",
    width: int = 512,
    height: int = 512,
    frames: int = 16,
    fps: int = 8,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 0,
    sampler_name: str = "euler",
    scheduler: str = "normal",
    format: str = "video/webp",
) -> dict[str, Any]:
    nodes = {}
    node_id_counter = 1

    def add_node(class_type: str, inputs: dict) -> str:
        nonlocal node_id_counter
        nid = str(node_id_counter)
        node_id_counter += 1
        nodes[nid] = {"class_type": class_type, "inputs": inputs}
        return nid

    # Loaders
    ckpt_id = add_node("CheckpointLoaderSimple", {"ckpt_name": checkpoint})
    
    # AnimateDiff Context
    context_id = add_node("ADE_AnimateDiffUniformContextOptions", {
        "context_length": frames,
        "context_stride": 1,
        "context_overlap": 4,
        "context_schedule": "uniform",
        "closed_loop": False
    })
    
    # AnimateDiff Loader
    ad_loader_id = add_node("ADE_AnimateDiffLoaderWithContext", {
        "model_name": motion_model,
        "beta_schedule": "sqrt_linear (AnimateDiff)",
        "model": [ckpt_id, 0],
        "context_options": [context_id, 0]
    })
    
    # Text Prompts
    pos_id = add_node("CLIPTextEncode", {"text": prompt, "clip": [ckpt_id, 1]})
    neg_id = add_node("CLIPTextEncode", {"text": negative, "clip": [ckpt_id, 1]})
    
    # Empty Latent (video length = frames)
    latent_id = add_node("EmptyLatentImage", {
        "width": width,
        "height": height,
        "batch_size": frames
    })
    
    # KSampler
    sampler_id = add_node("KSampler", {
        "seed": seed,
        "steps": steps,
        "cfg": cfg,
        "sampler_name": sampler_name,
        "scheduler": scheduler,
        "denoise": 1.0,
        "model": [ad_loader_id, 0],
        "positive": [pos_id, 0],
        "negative": [neg_id, 0],
        "latent_image": [latent_id, 0]
    })
    
    # VAE Decode
    decode_id = add_node("VAEDecode", {
        "samples": [sampler_id, 0],
        "vae": [ckpt_id, 2]
    })
    
    # Video Save
    save_id = add_node("VHS_VideoCombine", {
        "frame_rate": fps,
        "loop_count": 0,
        "filename_prefix": filename_prefix,
        "format": format,
        "pingpong": False,
        "save_output": True,
        "images": [decode_id, 0]
    })
    
    return nodes
