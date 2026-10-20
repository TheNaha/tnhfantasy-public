import math
from typing import Any, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field


# Single source of truth for the last-resort checkpoint filename.
#
# This literal was previously re-spelled in seven places
# (workflow_builder x3, animatediff_builder, job_processing, image_submission,
# model_availability_service, job_submission_service, world_vault/characters),
# which is how "why does character illustration use a different checkpoint than
# the generator" bugs happen. The configured override still lives in
# config.json under generator.default_checkpoint; this is only the final
# fallback when nothing is installed.
# Re-exported from config, which is the lowest-level module: infrastructure
# imports config, so config cannot import from core without a cycle. Keeping the
# literal in two places is how they drifted.
from config import DEFAULT_CHECKPOINT, settings  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Prompt shortcut / textual-inversion embedding expansion
# ---------------------------------------------------------------------------

#: File extensions recognised for embedding files in `models/embeddings/`.
# The prompt post-processing lives in `core.workflow_postprocess`, because the
# graph path needs it too and it cannot import this module - this module
# imports it. The names are re-exported here because the builder's callers
# have always imported them from here.
from core.workflow_postprocess import (  # noqa: F401
    embedding_file_exists as _embedding_file_exists,
    expand_prompt_shortcuts,
    extract_embedding_names,
    postprocess_prompt_text,
)


class LoraOption(BaseModel):
    name: str
    strength: float = 1.0


class ControlNetOption(BaseModel):
    name: str
    image: Union[str, dict[str, Any]]
    preprocessor: str = "None"
    strength: float = 1.0


class IPAdapterOption(BaseModel):
    model: str
    image: Union[str, dict[str, Any]]
    clipVision: str
    weight: float = 1.0
    # The generator UI renders a "Stop At" slider per adapter and the store
    # ships it as `stopAt`, but this model declared only the four fields above,
    # so pydantic discarded it and `IPAdapterApply` was never given an
    # `end_at` — a control that looked live and did nothing. Aliased rather than
    # renamed so the existing store payload keeps working; `populate_by_name`
    # means `stop_at` is accepted too.
    stopAt: float = Field(default=1.0, ge=0.0, le=1.0, alias="stop_at")
    model_config = {"populate_by_name": True}


class GeneratorOptions(BaseModel):
    mode: str = "t2i"  # t2i, img2img, inpaint
    
    # Text
    prompt: str
    negativePrompt: str = ""
    
    # Base Generation
    seed: int = 0
    steps: int = 20
    cfg: float = 7.0
    sampler: str = "euler"
    scheduler: str = "normal"
    width: int = 1024
    height: int = 1024
    batchSize: int = 1
    
    # Models
    checkpoint: str = ""
    unet: str | None = None
    clip: str | None = None
    clip2: str | None = None
    vae: str | None = None
    modelType: str = "sdxl" # sdxl, flux, sd15, auraflow, pony
    
    # Enhancements
    clipSkip: int = 1
    enableFreeU: bool = False
    enablePAG: bool = False
    pagScale: float = 3.0
    loras: list[LoraOption] = Field(default_factory=list)
    ipAdapters: list[IPAdapterOption] = Field(default_factory=list)
    controlnets: list[ControlNetOption] = Field(default_factory=list)
    
    # Image to Image / Inpaint
    inputImage: Union[str, dict[str, Any], None] = None
    maskImage: Union[str, dict[str, Any], None] = None
    denoise: float = 0.7
    growMask: int = 0
    maskBlur: int = 0
    
    # Upscale / Hires Fix
    hiresFix: bool = False
    hiresUpscaler: str = "Latent"
    hiresDenoise: float = 0.3
    hiresUpscale: float = 1.5
    hiresSteps: int = 10
    enableLatentUpscale: bool = False
    latentUpscaleMultiplier: float = 1.5
    
    # ADetailer
    adetailer: bool = False
    adetailerModel: str | None = None
    adetailerPrompt: str = ""
    adetailerSteps: int = 20
    adetailerDenoise: float = 0.4
    adetailerInpaintMasked: bool = True

    # `SaveImage.filename_prefix`. `None` means "derive one from the mode and
    # the clock" (`_generate_filename_prefix`), which is the right default for
    # an ad-hoc generation and the wrong one for a job that wants its output
    # filed under `ChatIllustrate` or `StoryAgenticGen`. It is `None` and not
    # `""` so that an explicit empty string is still honoured rather than
    # silently replaced.
    filenamePrefix: str | None = None


class WorkflowBuilder:
    def __init__(self):
        self.nodes = {}
        self.last_node_id = 0

    def add_node(self, class_type: str, inputs: dict[str, Any]) -> str:
        self.last_node_id += 1
        node_id = str(self.last_node_id)
        self.nodes[node_id] = {"inputs": inputs, "class_type": class_type}
        return node_id

    def _generate_filename_prefix(self, type_str: str = "T2I") -> str:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H-%M-%S")
        return f"{type_str}_{date_str}_{time_str}"
        
    def _get_image_str(self, image_input: Union[str, dict[str, Any]]) -> str:
        if isinstance(image_input, dict):
            return image_input.get("filename", "")
        return image_input

    def apply_loras(self, current_model, current_clip, loras: list[LoraOption]):
        for lora in loras:
            if not lora.name:
                continue
            lora_node = self.add_node("LoraLoader", {
                "model": current_model,
                "clip": current_clip,
                "lora_name": lora.name,
                "strength_model": lora.strength,
                "strength_clip": lora.strength
            })
            current_model = [lora_node, 0]
            current_clip = [lora_node, 1]
        return current_model, current_clip

    def apply_freeu(self, current_model, model_type: str):
        is_sd15 = (model_type == "sd15")
        freeu_node = self.add_node("FreeU_V2", {
            "model": current_model,
            "b1": 1.2 if is_sd15 else 1.3,
            "b2": 1.4,
            "s1": 0.9,
            "s2": 0.2
        })
        return [freeu_node, 0]

    def apply_pag(self, current_model, scale: float):
        pag_node = self.add_node("PerturbedAttentionGuidance", {
            "model": current_model,
            "scale": scale
        })
        return [pag_node, 0]

    def apply_clip_skip(self, current_clip, skip: int):
        clip_skip_node = self.add_node("CLIPSetLastLayer", {
            "clip": current_clip,
            "stop_at_clip_layer": -abs(skip)
        })
        return [clip_skip_node, 0]

    def apply_controlnets(self, positive_conditioning, controlnets: list[ControlNetOption]):
        current_cond = positive_conditioning
        for cn in controlnets:
            if not cn.name or not cn.image:
                continue

            cn_loader = self.add_node("ControlNetLoader", {
                "control_net_name": cn.name
            })

            img_str = self._get_image_str(cn.image)
            image_loader = self.add_node("LoadImage", {
                "image": img_str
            })

            processed_image = [image_loader, 0]
            if cn.preprocessor == "Canny":
                canny = self.add_node("CannyEdgePreprocessor", {
                    "image": [image_loader, 0],
                    "low_threshold": 100,
                    "high_threshold": 200,
                    "resolution": 512
                })
                processed_image = [canny, 0]

            cn_apply = self.add_node("ControlNetApply", {
                "conditioning": current_cond,
                "control_net": [cn_loader, 0],
                "image": processed_image,
                "strength": cn.strength
            })

            current_cond = [cn_apply, 0]
        return current_cond

    def apply_ip_adapters(self, current_model, ip_adapters: list[IPAdapterOption]):
        model = current_model
        for ip in ip_adapters:
            if not ip.model or not ip.image or not ip.clipVision:
                continue

            ip_loader = self.add_node("IPAdapterModelLoader", {
                "ipadapter_file": ip.model
            })

            self.add_node("CLIPVisionLoader", {
                "clip_name": ip.clipVision
            })

            img_str = self._get_image_str(ip.image)
            image_loader = self.add_node("LoadImage", {
                "image": img_str
            })

            # `end_at` is ComfyUI's "Stop At" — the fraction of the diffusion
            # schedule over which this adapter applies. Omitted when it is the
            # default 1.0 so the generated workflow keeps matching what the node
            # produces for an unconfigured adapter.
            apply_inputs: dict[str, Any] = {
                "ipadapter": [ip_loader, 0],
                "model": model,
                "weight": ip.weight,
                "image": [image_loader, 0],
            }
            if ip.stopAt < 1.0:
                apply_inputs["end_at"] = ip.stopAt

            ip_apply = self.add_node("IPAdapterApply", apply_inputs)

            model = [ip_apply, 0]
        return model

    def apply_latent_modifiers(self, latent_image, options: GeneratorOptions):
        latent = latent_image
        if options.enableLatentUpscale and options.latentUpscaleMultiplier > 1.0:
            upscale_node = self.add_node("LatentUpscaleBy", {
                "samples": latent,
                "upscale_method": "bilinear",
                "scale_by": options.latentUpscaleMultiplier
            })
            latent = [upscale_node, 0]
        return latent

    def apply_adetailer(self, final_image, current_model, current_clip, current_vae, positive_cond, negative_cond, options: GeneratorOptions):
        bbox_loader = self.add_node("UltralyticsDetectorProvider", {
            "model_name": f"bbox/{options.adetailerModel}"
        })

        face_detailer = self.add_node("FaceDetailer", {
            "image": final_image,
            "model": current_model,
            "clip": current_clip,
            "vae": current_vae,
            "positive": positive_cond,
            "negative": negative_cond,
            "guide_size": 256,
            "guide_size_for": True,
            "max_size": 768,
            "seed": options.seed,
            "steps": options.adetailerSteps,
            "cfg": options.cfg,
            "sampler_name": options.sampler,
            "scheduler": options.scheduler,
            "denoise": options.adetailerDenoise,
            "feather": 5,
            "noise_mask": True,
            "force_inpaint": True,
            "bbox_threshold": 0.5,
            "bbox_dilation": 10,
            "bbox_crop_factor": 3.0,
            "sam_detection_hint": "center-1",
            "sam_dilation": 0,
            "sam_threshold": 0.93,
            "sam_bbox_expansion": 0,
            "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False",
            "drop_size": 10,
            "wildcard": options.adetailerPrompt,
            "cycle": 1,
            "bbox_detector": [bbox_loader, 0],
            "sam_model_opt": None,
            "segm_detector_opt": None,
            "detailer_hook": None
        })

        return [face_detailer, 0]

    def load_models(self, options: GeneratorOptions):
        if options.unet and options.clip:
            # Split Loader Mode (Flux, SD3, AuraFlow)
            current_model = [self.add_node("UNETLoader", {
                "unet_name": options.unet,
                "weight_dtype": "default"
            }), 0]

            if options.clip2:
                clip1_name = options.clip
                clip2_name = options.clip2
                loader_type = "flux"

                if options.modelType == "sdxl":
                    clip1_name = options.clip2
                    clip2_name = options.clip
                    loader_type = "sdxl"

                current_clip = [self.add_node("DualCLIPLoader", {
                    "clip_name1": clip1_name,
                    "clip_name2": clip2_name,
                    "type": loader_type
                }), 0]
            else:
                current_clip = [self.add_node("CLIPLoader", {
                    "clip_name": options.clip,
                    "type": "stable_diffusion"
                }), 0]

            vae_name = options.vae if (options.vae and options.vae != "Baked in") else "ae.safetensors"
            current_vae = [self.add_node("VAELoader", {
                "vae_name": vae_name
            }), 0]
        else:
            # Standard Checkpoint Loader
            checkpoint_loader = self.add_node("CheckpointLoaderSimple", {
                "ckpt_name": options.checkpoint
            })
            current_model = [checkpoint_loader, 0]
            current_clip = [checkpoint_loader, 1]
            current_vae = [checkpoint_loader, 2]

            if options.vae and options.vae != "Baked in":
                current_vae = [self.add_node("VAELoader", {
                    "vae_name": options.vae
                }), 0]

        return current_model, current_clip, current_vae

    def build_core(self, options: GeneratorOptions) -> dict[str, Any]:
        mode = options.mode
        current_model, current_clip, current_vae = self.load_models(options)

        # Enhancements
        if options.clipSkip > 1:
            current_clip = self.apply_clip_skip(current_clip, options.clipSkip)

        current_model, current_clip = self.apply_loras(current_model, current_clip, options.loras)

        if options.enableFreeU and options.modelType != "flux":
            current_model = self.apply_freeu(current_model, options.modelType)

        if options.enablePAG and options.modelType != "flux":
            current_model = self.apply_pag(current_model, options.pagScale)

        current_model = self.apply_ip_adapters(current_model, options.ipAdapters)

        # CLIP Encoding — expand prompt shortcuts and validate embedding
        # references before the text reaches ComfyUI.
        #
        # The same treatment the graph path gets, from the same module: the
        # graph path used to skip it entirely, so a graph with an
        # `embedding:` reference to a file that does not exist reached the
        # provider and failed there.
        expanded_prompt = postprocess_prompt_text(options.prompt)
        expanded_negative = postprocess_prompt_text(options.negativePrompt, field="negativePrompt")

        positive_cond = [self.add_node("CLIPTextEncode", {
            "text": expanded_prompt,
            "clip": current_clip
        }), 0]

        negative_cond = [self.add_node("CLIPTextEncode", {
            "text": expanded_negative,
            "clip": current_clip
        }), 0]

        positive_cond = self.apply_controlnets(positive_cond, options.controlnets)

        # Latent Setup based on mode
        if mode == 't2i':
            latent_image = [self.add_node("EmptyLatentImage", {
                "width": options.width,
                "height": options.height,
                "batch_size": options.batchSize
            }), 0]
        elif mode == 'img2img':
            img_str = self._get_image_str(options.inputImage)
            load_image = [self.add_node("LoadImage", {"image": img_str}), 0]
            latent_image = [self.add_node("VAEEncode", {
                "pixels": load_image,
                "vae": current_vae
            }), 0]
        elif mode == 'inpaint':
            img_str = self._get_image_str(options.inputImage)
            mask_str = self._get_image_str(options.maskImage)
            load_image = [self.add_node("LoadImage", {"image": img_str}), 0]
            load_mask = [self.add_node("LoadImageMask", {"image": mask_str, "channel": "red"}), 0]
            
            processed_mask = load_mask
            if options.growMask > 0:
                processed_mask = [self.add_node("GrowMask", {
                    "mask": processed_mask, 
                    "expand": options.growMask, 
                    "tapered_corners": True
                }), 0]
            if options.maskBlur > 0:
                processed_mask = [self.add_node("FeatherMask", {
                    "mask": processed_mask, 
                    "left": options.maskBlur, 
                    "right": options.maskBlur, 
                    "top": options.maskBlur, 
                    "bottom": options.maskBlur
                }), 0]

            latent_image = [self.add_node("VAEEncodeForInpaint", {
                "pixels": load_image,
                "vae": current_vae,
                "mask": processed_mask,
                "grow_mask_by": 6
            }), 0]
        else:
            raise ValueError(f"Unknown mode: {mode}")

        latent_image = self.apply_latent_modifiers(latent_image, options)

        # KSampler
        denoise = 1.0 if mode == 't2i' else (options.denoise if options.denoise else 0.7)
        final_latent = [self.add_node("KSampler", {
            "seed": options.seed,
            "steps": options.steps,
            "cfg": options.cfg,
            "sampler_name": options.sampler,
            "scheduler": options.scheduler,
            "denoise": denoise,
            "model": current_model,
            "positive": positive_cond,
            "negative": negative_cond,
            "latent_image": latent_image
        }), 0]

        # Hires Fix (T2I only)
        if mode == 't2i' and options.hiresFix:
            if options.hiresUpscaler == "Latent":
                final_latent = [self.add_node("LatentUpscaleBy", {
                    "samples": final_latent,
                    "upscale_method": "bilinear",
                    "scale_by": options.hiresUpscale
                }), 0]
            else:
                vae_decode1 = [self.add_node("VAEDecode", {"samples": final_latent, "vae": current_vae}), 0]
                
                if options.hiresUpscaler == "Pixel":
                    upscale_image = [self.add_node("ImageScaleBy", {
                        "image": vae_decode1,
                        "upscale_method": "nearest-exact",
                        "scale_by": options.hiresUpscale
                    }), 0]
                else:
                    upscaler_loader = [self.add_node("UpscaleModelLoader", {"model_name": options.hiresUpscaler}), 0]
                    upscale_with_model = [self.add_node("ImageUpscaleWithModel", {
                        "upscale_model": upscaler_loader,
                        "image": vae_decode1
                    }), 0]
                    target_width = math.floor(options.width * options.hiresUpscale)
                    target_height = math.floor(options.height * options.hiresUpscale)
                    upscale_image = [self.add_node("ImageScale", {
                        "image": upscale_with_model,
                        "upscale_method": "lanczos",
                        "width": target_width,
                        "height": target_height,
                        "crop": "disabled"
                    }), 0]
                final_latent = [self.add_node("VAEEncode", {"pixels": upscale_image, "vae": current_vae}), 0]

            final_latent = [self.add_node("KSampler", {
                "seed": options.seed,
                "steps": options.hiresSteps,
                "cfg": options.cfg,
                "sampler_name": options.sampler,
                "scheduler": options.scheduler,
                "denoise": options.hiresDenoise,
                "model": current_model,
                "positive": positive_cond,
                "negative": negative_cond,
                "latent_image": final_latent
            }), 0]

        final_image = [self.add_node("VAEDecode", {"samples": final_latent, "vae": current_vae}), 0]

        if options.adetailer:
            final_image = self.apply_adetailer(final_image, current_model, current_clip, current_vae, positive_cond, negative_cond, options)

        prefix_type = "T2I"
        if mode == 't2i':
            prefix_type = "T2I_Hires" if options.hiresFix else "T2I"
        elif mode == 'img2img':
            prefix_type = "Img2Img"
        elif mode == 'inpaint':
            prefix_type = "Inpaint"

        # An explicit prefix wins. It used to be accepted by
        # `build_image_workflow(filename_prefix=...)` and then dropped on the
        # floor — six call sites passed `ChatIllustrate` / `StoryAgenticGen` /
        # `AgenticGen` and every one of them produced a `T2I_<timestamp>`
        # prefix instead, so the outputs could not be told apart by origin. The
        # video path has always honoured its own parameter; this makes the two
        # agree.
        prefix = options.filenamePrefix or self._generate_filename_prefix(prefix_type)

        self.add_node("SaveImage", {
            "filename_prefix": prefix,
            "images": final_image
        })

        return self.nodes

    def build(self, options: Union[GeneratorOptions, dict[str, Any]]) -> dict[str, Any]:
        if isinstance(options, dict):
            options = GeneratorOptions(**options)
        return self.build_core(options)

DEFAULT_NEGATIVE_PROMPT = (
    "worst quality, low quality, bad anatomy, bad hands, missing fingers, "
    "extra limbs, extra digit, text, signature, watermark, username"
)
DEFAULT_FILENAME_PREFIX = "ComfyUI"

def build_image_workflow(
    prompt: str,
    negative: str = DEFAULT_NEGATIVE_PROMPT,
    checkpoint: str = DEFAULT_CHECKPOINT,
    lora: Optional[str] = None,
    filename_prefix: Optional[str] = None,
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 0,
    sampler_name: str = "euler",
    scheduler: str = "normal",
    denoise: float = 1.0,
) -> dict[str, Any]:
    opts = GeneratorOptions(
        prompt=prompt,
        negativePrompt=negative,
        checkpoint=checkpoint,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        seed=seed,
        sampler=sampler_name,
        scheduler=scheduler,
        denoise=denoise,
        filenamePrefix=filename_prefix,
        loras=[LoraOption(name=lora)] if lora else []
    )
    builder = WorkflowBuilder()
    return builder.build(opts)


def build_image_job_workflow(
    prompt: str,
    negative: str = DEFAULT_NEGATIVE_PROMPT,
    checkpoint: str = DEFAULT_CHECKPOINT,
    lora: Optional[str] = None,
    filename_prefix: Optional[str] = None,
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = 0,
    sampler_name: str = "euler",
    scheduler: str = "normal",
    denoise: float = 1.0,
    source: Optional[str] = None,
    workspace: str = "main",
    chat_id: Optional[str] = None,
    character_id: Optional[str] = None,
    story_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    parent_job_id: Optional[str] = None,
    branch_id: Optional[str] = None,
    extra_metadata: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow = build_image_workflow(
        prompt=prompt,
        negative=negative,
        checkpoint=checkpoint,
        lora=lora,
        filename_prefix=filename_prefix,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        seed=seed,
        sampler_name=sampler_name,
        scheduler=scheduler,
        denoise=denoise,
    )

    metadata: dict[str, Any] = {
        "source": source,
        "workspace": workspace,
        "prompt": prompt,
        "negativePrompt": negative,
        "checkpoint": checkpoint,
        "steps": steps,
        "cfg": cfg,
        "sampler": sampler_name,
        "scheduler": scheduler,
        "width": width,
        "height": height,
        "seed": seed,
    }
    if lora:
        metadata["loras"] = [lora]
    if chat_id is not None:
        metadata["chat_id"] = chat_id
    if character_id is not None:
        metadata["character_id"] = character_id
    if story_id is not None:
        metadata["story_id"] = story_id
    if chapter_id is not None:
        metadata["chapter_id"] = chapter_id
    if parent_job_id is not None:
        metadata["parent_job_id"] = parent_job_id
    if branch_id is not None:
        metadata["branch_id"] = branch_id
    if extra_metadata:
        metadata.update(extra_metadata)

    return workflow, metadata


def build_scene_job_workflow(
    spec: Any,
    *,
    checkpoint: str = DEFAULT_CHECKPOINT,
    model_type: str = "sdxl",
    filename_prefix: Optional[str] = None,
    source: Optional[str] = None,
    workspace: str = "main",
    chat_id: Optional[str] = None,
    character_id: Optional[str] = None,
    story_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    parent_job_id: Optional[str] = None,
    branch_id: Optional[str] = None,
    extra_metadata: Optional[dict[str, Any]] = None,
    lora_name: Optional[str] = None,
    controlnet_image: Optional[str] = None,
    ipadapter_image: Optional[str] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Render a scene-graph spec into a workflow and its job metadata.

    The graph itself is the same one the stock image job produces — the
    `WorkflowBuilder` — so the node structure, the gallery metadata and the
    "reuse parameters" reverse mapping all keep working. What the spec
    changes is the VALUES: the sampler, the resolution, the steps, the LoRA,
    the hires pass.

    `spec` is a `core.scene_graph.SceneGraphSpec`. It is typed loosely here
    so that `core.workflow_builder` does not have to import
    `core.scene_graph`, which imports this module.
    """
    from core.scene_graph import scene_spec_to_options

    options = scene_spec_to_options(
        spec,
        checkpoint=checkpoint,
        model_type=model_type,
        lora_name=lora_name,
        controlnet_image=controlnet_image,
        ipadapter_image=ipadapter_image,
    )
    options.filenamePrefix = filename_prefix
    builder = WorkflowBuilder()
    workflow = builder.build(options)

    composition = spec.composition
    sampler = spec.sampler
    metadata: dict[str, Any] = {
        "source": source,
        "workspace": workspace,
        "prompt": spec.prompt,
        "negativePrompt": spec.negative_prompt,
        "checkpoint": checkpoint,
        "steps": sampler.steps,
        "cfg": sampler.cfg,
        "sampler": sampler.name,
        "scheduler": sampler.scheduler,
        "width": composition.width,
        "height": composition.height,
        "seed": sampler.seed,
        "scene_graph": True,
    }
    if lora_name:
        metadata["loras"] = [lora_name]
    if chat_id is not None:
        metadata["chat_id"] = chat_id
    if character_id is not None:
        metadata["character_id"] = character_id
    if story_id is not None:
        metadata["story_id"] = story_id
    if chapter_id is not None:
        metadata["chapter_id"] = chapter_id
    if parent_job_id is not None:
        metadata["parent_job_id"] = parent_job_id
    if branch_id is not None:
        metadata["branch_id"] = branch_id
    if extra_metadata:
        metadata.update(extra_metadata)

    return workflow, metadata


def build_video_job_workflow(
    prompt: str,
    negative: str = DEFAULT_NEGATIVE_PROMPT,
    checkpoint: str = DEFAULT_CHECKPOINT,
    motion_model: str = "mm_sdxl_v10_beta.ckpt",
    filename_prefix: str = DEFAULT_FILENAME_PREFIX,
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
    source: Optional[str] = None,
    workspace: str = "main",
    chat_id: Optional[str] = None,
    character_id: Optional[str] = None,
    story_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    parent_job_id: Optional[str] = None,
    extra_metadata: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from .animatediff_builder import build_animatediff_workflow
    nodes = build_animatediff_workflow(
        prompt=prompt,
        negative=negative,
        checkpoint=checkpoint,
        motion_model=motion_model,
        filename_prefix=filename_prefix,
        width=width,
        height=height,
        frames=frames,
        fps=fps,
        steps=steps,
        cfg=cfg,
        seed=seed,
        sampler_name=sampler_name,
        scheduler=scheduler,
        format=format,
    )
    
    workflow = nodes

    metadata: dict[str, Any] = {
        "source": source,
        "workspace": workspace,
        "prompt": prompt,
        "negativePrompt": negative,
        "checkpoint": checkpoint,
        "motion_model": motion_model,
        "steps": steps,
        "cfg": cfg,
        "sampler": sampler_name,
        "scheduler": scheduler,
        "width": width,
        "height": height,
        "seed": seed,
        "frames": frames,
        "fps": fps,
        "type": "video"
    }
    
    if chat_id is not None:
        metadata["chat_id"] = chat_id
    if character_id is not None:
        metadata["character_id"] = character_id
    if story_id is not None:
        metadata["story_id"] = story_id
    if chapter_id is not None:
        metadata["chapter_id"] = chapter_id
    if parent_job_id is not None:
        metadata["parent_job_id"] = parent_job_id
    if extra_metadata:
        metadata.update(extra_metadata)

    return workflow, metadata
