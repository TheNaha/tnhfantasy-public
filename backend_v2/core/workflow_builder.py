"""
Shared ComfyUI workflow builder.

Previously, two near-identical copies of an SDXL text-to-image workflow
existed — one in ``services/orchestrator_service.py`` (with LoRA support)
and a simpler variant in ``api/routes/world_vault/stories.py``.  This module
provides a single canonical implementation that both call sites can use,
eliminating the duplication and ensuring consistency.
"""

from typing import Any, Optional

# ---------------------------------------------------------------------------
# Default negative prompt — reused across all image-generation workflows so
# output quality is consistent wherever workflows are built.
# ---------------------------------------------------------------------------
DEFAULT_NEGATIVE_PROMPT = (
    "worst quality, low quality, bad anatomy, bad hands, missing fingers, "
    "extra limbs, extra digit, text, signature, watermark, username"
)

# Default filename prefix written into SaveImage nodes.
DEFAULT_FILENAME_PREFIX = "ComfyUI"


def build_image_workflow(
    prompt: str,
    negative: str = DEFAULT_NEGATIVE_PROMPT,
    checkpoint: str = "sd_xl_base_1.0.safetensors",
    lora: Optional[str] = None,
    filename_prefix: str = DEFAULT_FILENAME_PREFIX,
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 0,
    sampler_name: str = "euler",
    scheduler: str = "normal",
    denoise: float = 1.0,
) -> dict[str, Any]:
    """Build a standard SDXL text-to-image ComfyUI workflow.

    Parameters
    ----------
    prompt
        Positive prompt (Danbooru-style tags, comma-separated).
    negative
        Negative prompt.  Defaults to :data:`DEFAULT_NEGATIVE_PROMPT`.
    checkpoint
        Filename of the checkpoint model to load (e.g.
        ``"animagine_xl_v31_v31_403131.safetensors"``).
    lora
        Optional LoRA filename.  When provided a ``LoraLoader`` node is
        inserted and both CLIP text-encode nodes are rewired to use the
        LoRA-enhanced clip.
    filename_prefix
        Prefix used by the ``SaveImage`` node.
    width / height
        Latent image dimensions.
    steps / cfg / seed / sampler_name / scheduler / denoise
        KSampler hyper-parameters.

    Returns
    -------
    dict[str, Any]
        ComfyUI workflow dictionary keyed by node id (as strings).
    """
    # Node "4" is always the CheckpointLoader / LoRA chain root, so the
    # CLIP/text-encode/latent/model references stay stable whether or not
    # a LoRA is present.
    clip_ref = ["10", 1] if lora else ["4", 1]
    model_ref = ["10", 0] if lora else ["4", 0]

    workflow: dict[str, dict[str, Any]] = {
        # KSampler
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": denoise,
                "model": model_ref,
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        # Checkpoint loader
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        # Empty latent
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"batch_size": 1, "width": width, "height": height},
        },
        # Positive CLIP text encode
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": clip_ref},
        },
        # Negative CLIP text encode
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": clip_ref},
        },
        # VAE decode
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        # Save image
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": filename_prefix, "images": ["8", 0]},
        },
    }

    if lora:
        workflow["10"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": lora,
                "strength_model": 1.0,
                "strength_clip": 1.0,
                "model": ["4", 0],
                "clip": ["4", 1],
            },
        }

    return workflow
