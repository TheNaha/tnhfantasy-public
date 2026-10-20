"""The limits on a scene-graph-authored image.

A leaf module, like `core/pipeline_limits.py`: it imports nothing, so
anything can import it without a cycle.

Why these exist
----------------

The Illustrator agent may author the *parameters* of a scene image — the
sampler, the resolution, the steps, the LoRA. It may not author the graph.
`POST /api/v2/generate` already accepts an arbitrary ComfyUI workflow, and
that path has no ceiling on what a workflow may ask for: `EmptyLatentImage`
takes `width` and `height` with no bound, `KSampler` takes `steps` with no
bound, and `batch_size` has no bound either. `core.upload_validation.py`'s
`MAX_IMAGE_DIMENSION` applies to uploaded image BYTES, not to the dimensions
a workflow requests.

An LLM in the loop inherits all of that and amplifies it. These limits are
what a scene-graph spec is checked against, and they are checked BEFORE the
job is created — ComfyUI's own validation happens at dispatch, which is
after the job has been billed.
"""

from __future__ import annotations

# Sampler steps for the base pass. The stock image job uses 20; a scene that
# wants more detail can ask for more, up to a ceiling that keeps one image
# from costing an unbounded number of forward passes.
MAX_SCENE_STEPS = 60
MIN_SCENE_STEPS = 1

# The hires-fix pass runs on top of the base pass, so it is budgeted
# separately and more tightly.
MAX_SCENE_HIRES_STEPS = 30
MIN_SCENE_HIRES_STEPS = 1

# Pixel dimensions. 2048 is comfortably above the stock 1024 and below the
# point where a single image takes minutes on a consumer GPU.
MAX_SCENE_WIDTH = 2048
MAX_SCENE_HEIGHT = 2048
MIN_SCENE_DIMENSION = 256

# Total pixels, which is what actually costs. A 2048x2048 image is 4.2M
# pixels and is allowed; two 2048-wide images at once are not, because the
# batch multiplies the cost.
MAX_SCENE_PIXELS = 4_194_304  # 2048 * 2048

# How many images one spec may produce.
MAX_SCENE_BATCH = 2

# LoRA strength. Above about 1.5 the LoRA overwhelms the checkpoint and the
# image stops resembling the character.
MAX_SCENE_LORA_STRENGTH = 1.5
MIN_SCENE_LORA_STRENGTH = 0.0

# ControlNet and IPAdapter influence.
MAX_SCENE_CONTROLNET_STRENGTH = 1.0
MAX_SCENE_IPADAPTER_WEIGHT = 1.0

# CFG. Above about 12 the image goes over-saturated; the stock job uses 7.
MAX_SCENE_CFG = 15.0
MIN_SCENE_CFG = 1.0

# Denoise for the base pass.
MAX_SCENE_DENOISE = 1.0
MIN_SCENE_DENOISE = 0.0

# The samplers and schedulers ComfyUI ships. A name outside this set is
# dropped rather than passed through, because an unknown sampler name makes
# ComfyUI reject the whole job at dispatch — after it was billed.
SCENE_SAMPLERS = frozenset({
    "euler", "euler_ancestral", "euler_ancestral_sde", "heun", "dpm_2",
    "dpm_2_ancestral", "dpm_2_sde", "dpm_2_sde_gpu", "dpm_2_sde_gpu_noanc",
    "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_2m", "dpmpp_2m_sde",
    "dpmpp_2m_sde_gpu", "dpmpp_3m_sde", "dpmpp_3m_sde_gpu", "ddim", "uni_pc",
})

SCENE_SCHEDULERS = frozenset({
    "normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform",
    "beta",
})

# The hires upscalers ComfyUI ships.
SCENE_HIRES_UPSCALERS = frozenset({"latent", "bilinear", "nearest-exact"})

# The relative sizes a scene may ask for. A width that is not a multiple of
# 8 is silently truncated by ComfyUI, so the spec is rounded rather than
# passed through.
SCENE_DIMENSION_MULTIPLE = 8
