"""The scene graph spec — what the Illustrator agent is allowed to author.

The Illustrator used to produce prompt TEXT, which was fed into a fixed
workflow. It could say *what the scene looks like* and nothing else: the
sampler, the resolution, the steps, the LoRA, the hires pass were all
fixed.

This is the closed vocabulary it may author instead. It is a SPEC, not a
ComfyUI graph: the backend renders it with the existing `WorkflowBuilder`,
so the node graph stays the one the system knows how to build, the gallery
metadata stays populated, and the generation parameters are bounded.

Why not a raw graph
-------------------

A raw LLM-authored graph is not safe to build, and the reasons are concrete
rather than theoretical:

* There is no node allow-list anywhere in the system. A raw graph can
  contain any node the provider has installed, including custom nodes that
  read files, reach the network or spawn processes. The only server-side
  gate is ComfyUI's own validation, which runs at DISPATCH — after the job
  has been billed.
* There is no cost guard. `EmptyLatentImage.width` and `height` are
  unbounded, `KSampler.steps` is unbounded, and `batch_size` is unbounded.
  `core/upload_validation.py`'s `MAX_IMAGE_DIMENSION` is about uploaded
  image BYTES and says nothing about the dimensions a workflow requests.
* The gallery depends on the builder's metadata. `prompt`, `seed`, `steps`,
  `checkpoint`, `width` and `height` are what the assets table and
  `frontend_v2/src/utils/reuseParameters.js` read. A raw graph bypasses
  that and breaks "reuse parameters".

So the LLM picks the meaningful axes and the backend renders them. The
result is still node-level control over everything that matters — sampler,
scheduler, steps, CFG, resolution, batch, LoRA, hires fix, ControlNet,
IPAdapter, detailer — and the graph stays correct, bounded and
gallery-compatible.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.workflow_builder import GeneratorOptions, LoraOption
from core.workflow_limits import (
    MAX_SCENE_BATCH,
    MAX_SCENE_CFG,
    MAX_SCENE_CONTROLNET_STRENGTH,
    MAX_SCENE_DENOISE,
    MAX_SCENE_HIRES_STEPS,
    MAX_SCENE_HEIGHT,
    MAX_SCENE_IPADAPTER_WEIGHT,
    MAX_SCENE_LORA_STRENGTH,
    MAX_SCENE_PIXELS,
    MAX_SCENE_STEPS,
    MAX_SCENE_WIDTH,
    MIN_SCENE_CFG,
    MIN_SCENE_DIMENSION,
    MIN_SCENE_DENOISE,
    MIN_SCENE_HIRES_STEPS,
    MIN_SCENE_LORA_STRENGTH,
    MIN_SCENE_STEPS,
    SCENE_DIMENSION_MULTIPLE,
    SCENE_HIRES_UPSCALERS,
    SCENE_SAMPLERS,
    SCENE_SCHEDULERS,
)


#: How the scene's upscaler vocabulary maps onto the generator's.
#:
#: The two are not the same vocabulary, and the scene's was passed through
#: untranslated - so NONE of the scene's three values matched the builder's.
#:
#: The scene says which UPSCALING to do (`latent`, `bilinear`,
#: `nearest-exact`); the generator's options say which UPSCALER to use
#: (`Latent`, `Pixel`, or a model name). The builder branches on
#: `"Latent"` and `"Pixel"` and treats everything else as a MODEL name, so
#: a scene with a hires fix asked the provider for a model called "latent",
#: and the job failed on a file nobody had.
#:
#: Two of the scene's values are latent upscales (the difference is the
#: resampling method, which the builder hardcodes) and one is a pixel
#: upscale, so the three collapse onto the generator's two.
SCENE_UPSCALER_TO_GENERATOR: dict[str, str] = {
    "latent": "Latent",
    "bilinear": "Latent",
    "nearest-exact": "Pixel",
}


def hires_upscaler_for_generator(upscaler: str | None) -> str:
    """The generator's name for the scene's upscaler.

    A value that is not one of the scene's own is a MODEL name, and the
    generator takes model names as they are.
    """
    if not upscaler:
        return "Latent"
    key = str(upscaler).strip().lower()
    return SCENE_UPSCALER_TO_GENERATOR.get(key, upscaler)


def _round_dimension(value: int) -> int:
    """ComfyUI silently truncates a dimension that is not a multiple of 8.

    Rounding here means the metadata the gallery records is the dimension
    that was actually rendered.
    """
    return max(
        MIN_SCENE_DIMENSION,
        int(round(value / SCENE_DIMENSION_MULTIPLE) * SCENE_DIMENSION_MULTIPLE),
    )


class SceneSamplerSpec(BaseModel):
    """How the diffusion pass runs."""

    name: str = "euler"
    scheduler: str = "normal"
    steps: int = 20
    cfg: float = 7.0
    denoise: float = 1.0
    seed: int = 0


class SceneCompositionSpec(BaseModel):
    """The shape of the image."""

    width: int = 1024
    height: int = 1024
    batch_size: int = 1


class SceneLoraSpec(BaseModel):
    """A LoRA to load, and how hard."""

    name: str
    strength: float = 0.8


class SceneHiresFixSpec(BaseModel):
    """The second, higher-resolution pass."""

    enabled: bool = False
    upscaler: str = "latent"
    scale_by: float = 1.5
    steps: int = 10
    denoise: float = 0.3


class SceneControlNetSpec(BaseModel):
    """A ControlNet to apply. The image is chosen by the caller, not the LLM."""

    name: str
    strength: float = 0.6


class SceneIPAdapterSpec(BaseModel):
    """An IPAdapter to apply. The reference image is chosen by the caller."""

    name: str
    weight: float = 0.4
    clip_vision: str = ""


class SceneDetailerSpec(BaseModel):
    """An ADetailer pass for the face or hands."""

    enabled: bool = False
    model: str = ""
    steps: int = 20
    denoise: float = 0.4


class SceneGraphSpec(BaseModel):
    """What the Illustrator agent may say about an image.

    Every field has a default, so a partial answer is a usable answer: a
    model that returns only a prompt gets the stock workflow's parameters
    with its own prompt.
    """

    prompt: str = ""
    negative_prompt: str = ""
    composition: SceneCompositionSpec = Field(default_factory=SceneCompositionSpec)
    sampler: SceneSamplerSpec = Field(default_factory=SceneSamplerSpec)
    lora: Optional[SceneLoraSpec] = None
    hires_fix: SceneHiresFixSpec = Field(default_factory=SceneHiresFixSpec)
    controlnet: Optional[SceneControlNetSpec] = None
    ipadapter: Optional[SceneIPAdapterSpec] = None
    detailer: SceneDetailerSpec = Field(default_factory=SceneDetailerSpec)


class SceneSpecIssue(BaseModel):
    """One thing wrong with a spec, and what was done about it."""

    field: str
    value: Any = None
    problem: str
    resolution: str


def validate_scene_spec(spec: SceneGraphSpec) -> list[SceneSpecIssue]:
    """Check a spec against the limits. Returns the issues found.

    This runs BEFORE the job is created. A value that is out of range is
    clamped where clamping is safe (a step count of 200 becomes 60) and
    dropped where it is not (a sampler name ComfyUI does not have would make
    it reject the whole job at dispatch, after it was billed).
    """
    issues: list[SceneSpecIssue] = []

    sampler = spec.sampler
    if sampler.name not in SCENE_SAMPLERS:
        issues.append(SceneSpecIssue(
            field="sampler.name",
            value=sampler.name,
            problem="not a sampler ComfyUI ships",
            resolution="dropped; the default sampler is used",
        ))
    if sampler.scheduler not in SCENE_SCHEDULERS:
        issues.append(SceneSpecIssue(
            field="sampler.scheduler",
            value=sampler.scheduler,
            problem="not a scheduler ComfyUI ships",
            resolution="dropped; the default scheduler is used",
        ))
    if not (MIN_SCENE_STEPS <= sampler.steps <= MAX_SCENE_STEPS):
        clamped = max(MIN_SCENE_STEPS, min(MAX_SCENE_STEPS, sampler.steps))
        issues.append(SceneSpecIssue(
            field="sampler.steps",
            value=sampler.steps,
            problem=f"outside {MIN_SCENE_STEPS}..{MAX_SCENE_STEPS}",
            resolution=f"clamped to {clamped}",
        ))
    if not (MIN_SCENE_CFG <= sampler.cfg <= MAX_SCENE_CFG):
        clamped = max(MIN_SCENE_CFG, min(MAX_SCENE_CFG, sampler.cfg))
        issues.append(SceneSpecIssue(
            field="sampler.cfg",
            value=sampler.cfg,
            problem=f"outside {MIN_SCENE_CFG}..{MAX_SCENE_CFG}",
            resolution=f"clamped to {clamped}",
        ))
    if not (MIN_SCENE_DENOISE <= sampler.denoise <= MAX_SCENE_DENOISE):
        clamped = max(MIN_SCENE_DENOISE, min(MAX_SCENE_DENOISE, sampler.denoise))
        issues.append(SceneSpecIssue(
            field="sampler.denoise",
            value=sampler.denoise,
            problem=f"outside {MIN_SCENE_DENOISE}..{MAX_SCENE_DENOISE}",
            resolution=f"clamped to {clamped}",
        ))

    composition = spec.composition
    for field in ("width", "height"):
        value = getattr(composition, field)
        if not (MIN_SCENE_DIMENSION <= value <= max(MAX_SCENE_WIDTH, MAX_SCENE_HEIGHT)):
            clamped = _round_dimension(max(MIN_SCENE_DIMENSION, min(value, MAX_SCENE_WIDTH)))
            issues.append(SceneSpecIssue(
                field=f"composition.{field}",
                value=value,
                problem=f"outside {MIN_SCENE_DIMENSION}..{MAX_SCENE_WIDTH}",
                resolution=f"clamped to {clamped}",
            ))
    pixels = composition.width * composition.height
    if pixels > MAX_SCENE_PIXELS:
        issues.append(SceneSpecIssue(
            field="composition",
            value=f"{composition.width}x{composition.height}",
            problem=f"more than {MAX_SCENE_PIXELS} pixels",
            resolution="the batch is reduced until it fits",
        ))
    if composition.batch_size > MAX_SCENE_BATCH:
        issues.append(SceneSpecIssue(
            field="composition.batch_size",
            value=composition.batch_size,
            problem=f"more than {MAX_SCENE_BATCH}",
            resolution=f"clamped to {MAX_SCENE_BATCH}",
        ))

    if spec.lora is not None and not (
        MIN_SCENE_LORA_STRENGTH <= spec.lora.strength <= MAX_SCENE_LORA_STRENGTH
    ):
        clamped = max(MIN_SCENE_LORA_STRENGTH, min(MAX_SCENE_LORA_STRENGTH, spec.lora.strength))
        issues.append(SceneSpecIssue(
            field="lora.strength",
            value=spec.lora.strength,
            problem=f"outside {MIN_SCENE_LORA_STRENGTH}..{MAX_SCENE_LORA_STRENGTH}",
            resolution=f"clamped to {clamped}",
        ))

    if spec.hires_fix.enabled:
        if spec.hires_fix.upscaler not in SCENE_HIRES_UPSCALERS:
            issues.append(SceneSpecIssue(
                field="hires_fix.upscaler",
                value=spec.hires_fix.upscaler,
                problem="not an upscaler ComfyUI ships",
                resolution="dropped; the default upscaler is used",
            ))
        if not (MIN_SCENE_HIRES_STEPS <= spec.hires_fix.steps <= MAX_SCENE_HIRES_STEPS):
            clamped = max(
                MIN_SCENE_HIRES_STEPS, min(MAX_SCENE_HIRES_STEPS, spec.hires_fix.steps)
            )
            issues.append(SceneSpecIssue(
                field="hires_fix.steps",
                value=spec.hires_fix.steps,
                problem=f"outside {MIN_SCENE_HIRES_STEPS}..{MAX_SCENE_HIRES_STEPS}",
                resolution=f"clamped to {clamped}",
            ))

    if spec.controlnet is not None and spec.controlnet.strength > MAX_SCENE_CONTROLNET_STRENGTH:
        issues.append(SceneSpecIssue(
            field="controlnet.strength",
            value=spec.controlnet.strength,
            problem=f"above {MAX_SCENE_CONTROLNET_STRENGTH}",
            resolution=f"clamped to {MAX_SCENE_CONTROLNET_STRENGTH}",
        ))

    if spec.ipadapter is not None and spec.ipadapter.weight > MAX_SCENE_IPADAPTER_WEIGHT:
        issues.append(SceneSpecIssue(
            field="ipadapter.weight",
            value=spec.ipadapter.weight,
            problem=f"above {MAX_SCENE_IPADAPTER_WEIGHT}",
            resolution=f"clamped to {MAX_SCENE_IPADAPTER_WEIGHT}",
        ))

    return issues


def apply_scene_spec_limits(spec: SceneGraphSpec) -> SceneGraphSpec:
    """Return a spec with every value inside the limits.

    Clamping rather than rejecting: a scene that asked for 200 steps wanted a
    detailed image, and 60 steps is a reasonable answer to that. Refusing the
    whole illustration because one number was too large would lose the
    prompt too, and the prompt is the part the model actually thought about.
    """
    sampler = spec.sampler
    if sampler.name not in SCENE_SAMPLERS:
        sampler = sampler.model_copy(update={"name": "euler"})
    if sampler.scheduler not in SCENE_SCHEDULERS:
        sampler = sampler.model_copy(update={"scheduler": "normal"})
    sampler = sampler.model_copy(update={
        "steps": max(MIN_SCENE_STEPS, min(MAX_SCENE_STEPS, sampler.steps)),
        "cfg": max(MIN_SCENE_CFG, min(MAX_SCENE_CFG, sampler.cfg)),
        "denoise": max(MIN_SCENE_DENOISE, min(MAX_SCENE_DENOISE, sampler.denoise)),
    })

    composition = spec.composition
    width = _round_dimension(max(MIN_SCENE_DIMENSION, min(composition.width, MAX_SCENE_WIDTH)))
    height = _round_dimension(max(MIN_SCENE_DIMENSION, min(composition.height, MAX_SCENE_HEIGHT)))
    batch = max(1, min(MAX_SCENE_BATCH, composition.batch_size))
    while width * height * batch > MAX_SCENE_PIXELS and batch > 1:
        batch -= 1
    if width * height > MAX_SCENE_PIXELS:
        # A single image bigger than the pixel budget: scale it down to fit.
        scale = math.sqrt(MAX_SCENE_PIXELS / (width * height))
        width = _round_dimension(int(width * scale))
        height = _round_dimension(int(height * scale))
    composition = composition.model_copy(update={
        "width": width,
        "height": height,
        "batch_size": batch,
    })

    lora = spec.lora
    if lora is not None:
        lora = lora.model_copy(update={
            "strength": max(
                MIN_SCENE_LORA_STRENGTH, min(MAX_SCENE_LORA_STRENGTH, lora.strength)
            )
        })

    hires = spec.hires_fix
    if hires.enabled:
        hires = hires.model_copy(update={
            "upscaler": hires.upscaler if hires.upscaler in SCENE_HIRES_UPSCALERS else "latent",
            "steps": max(MIN_SCENE_HIRES_STEPS, min(MAX_SCENE_HIRES_STEPS, hires.steps)),
        })

    controlnet = spec.controlnet
    if controlnet is not None:
        controlnet = controlnet.model_copy(update={
            "strength": min(MAX_SCENE_CONTROLNET_STRENGTH, controlnet.strength)
        })

    ipadapter = spec.ipadapter
    if ipadapter is not None:
        ipadapter = ipadapter.model_copy(update={
            "weight": min(MAX_SCENE_IPADAPTER_WEIGHT, ipadapter.weight)
        })

    return spec.model_copy(update={
        "sampler": sampler,
        "composition": composition,
        "lora": lora,
        "hires_fix": hires,
        "controlnet": controlnet,
        "ipadapter": ipadapter,
    })


def scene_spec_to_options(
    spec: SceneGraphSpec,
    *,
    checkpoint: str,
    model_type: str = "sdxl",
    lora_name: str | None = None,
    controlnet_image: str | None = None,
    ipadapter_image: str | None = None,
) -> GeneratorOptions:
    """Render a spec into the generator options the workflow builder takes.

    The model names are resolved by the CALLER, not by the spec: the spec
    says which LoRA it wants, the caller says whether that LoRA is installed
    and what to do about it if it is not.
    """
    composition = spec.composition
    sampler = spec.sampler

    loras: list[LoraOption] = []
    if lora_name:
        loras.append(LoraOption(name=lora_name, strength=spec.lora.strength if spec.lora else 0.8))

    controlnets = []
    if spec.controlnet is not None and controlnet_image:
        from core.workflow_builder import ControlNetOption

        controlnets.append(ControlNetOption(
            name=spec.controlnet.name,
            image=controlnet_image,
            strength=spec.controlnet.strength,
        ))

    ip_adapters = []
    if spec.ipadapter is not None and ipadapter_image:
        from core.workflow_builder import IPAdapterOption

        ip_adapters.append(IPAdapterOption(
            model=spec.ipadapter.name,
            image=ipadapter_image,
            clipVision=spec.ipadapter.clip_vision or "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
            weight=spec.ipadapter.weight,
        ))

    return GeneratorOptions(
        mode="t2i",
        prompt=spec.prompt,
        negativePrompt=spec.negative_prompt,
        seed=sampler.seed,
        steps=sampler.steps,
        cfg=sampler.cfg,
        sampler=sampler.name,
        scheduler=sampler.scheduler,
        width=composition.width,
        height=composition.height,
        batchSize=composition.batch_size,
        denoise=sampler.denoise,
        checkpoint=checkpoint,
        modelType=model_type,
        loras=loras,
        controlnets=controlnets,
        ipAdapters=ip_adapters,
        hiresFix=spec.hires_fix.enabled,
        hiresUpscaler=hires_upscaler_for_generator(spec.hires_fix.upscaler),
        hiresDenoise=spec.hires_fix.denoise,
        hiresUpscale=spec.hires_fix.scale_by,
        hiresSteps=spec.hires_fix.steps,
        adetailer=spec.detailer.enabled,
        adetailerModel=spec.detailer.model or None,
        adetailerSteps=spec.detailer.steps,
        adetailerDenoise=spec.detailer.denoise,
    )


def scene_spec_cost(spec: SceneGraphSpec) -> float:
    """A rough relative cost for a spec.

    Steps and pixels are what cost anything; the model and the sampler do
    not. The number is not a price — it is a budget unit, so a chat can cap
    how much scene authoring it is allowed to spend.
    """
    composition = spec.composition
    pixels = composition.width * composition.height
    steps = spec.sampler.steps
    cost = (pixels / (1024 * 1024)) * (steps / 20.0) * composition.batch_size
    if spec.hires_fix.enabled:
        cost *= 1.0 + (spec.hires_fix.scale_by ** 2) * (spec.hires_fix.steps / 10.0)
    return round(cost, 3)


def parse_scene_spec(raw: str) -> Optional[SceneGraphSpec]:
    """Parse an LLM's answer into a spec, or None if it is not one.

    The model is asked for JSON. It sometimes answers with prose or with
    JSON wrapped in a fenced code block, so both are handled — and if none
    of it parses, the caller falls back to the prompt-text path, which is
    the difference between an illustration and no illustration.
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()
    if text.startswith("```"):
        # ```json ... ``` or ``` ... ```
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()

    try:
        import json

        data = json.loads(text)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    try:
        return SceneGraphSpec.model_validate(data)
    except Exception:
        return None
