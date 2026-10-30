"""Derive a job's display metadata from a compiled ComfyUI graph.

The guided path gets its metadata from the options the user filled in: the
frontend builds a `metadata` object next to the `options` it sends, and the
backend stores it on the job.

The graph path sent `metadata: {}`. So a job built from the Advanced
Generator had no prompt, no seed, no dimensions and no model name, and the
consequences were all in the gallery:

  * the card said "Unknown Model";
  * "Reuse parameters" restored nothing, because there was nothing to
    restore;
  * the PNG sidecar carried none of the allowlisted keys, so the image
    lost its provenance on disk.

So the backend derives the metadata from the graph. The mapping is the
same one the frontend already does in reverse
(`frontend_v2/src/utils/reuseParameters.js`), and it lives here so the two
sides cannot drift and so it can be tested.
"""

from collections.abc import Sequence
from typing import Any

# The KSampler family, shared with graph parsing so "metadata from the
# graph" and "sampler extraction" can never disagree about which node
# classes carry seed/steps/sampler inputs.
from core.workflow_parser import KSAMPLER_NODE_CLASSES


def _iter_nodes(workflow: dict):
    """Yield `(node_id, node)` for every node in a graph.

    The compiled form is `{"<id>": {"class_type": ..., "inputs": {...}}}`.
    The editor form is `{"nodes": [{"id": ..., "type": ..., ...}]}`, which a
    hand-written Raw JSON graph may use, so it is handled too.
    """
    if not isinstance(workflow, dict):
        return

    nodes = workflow.get("nodes")
    if isinstance(nodes, dict):
        for node_id, node in nodes.items():
            if isinstance(node, dict):
                yield str(node_id), node
        return

    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            if node_id is None:
                continue
            yield str(node_id), node
        return

    for node_id, node in workflow.items():
        if isinstance(node, dict) and "class_type" in node:
            yield str(node_id), node


def _class_type(node: dict) -> str:
    return str(node.get("class_type") or node.get("type") or "")


def _inputs(node: dict) -> dict:
    inputs = node.get("inputs")
    return inputs if isinstance(inputs, dict) else {}


def _linked_node_id(value: Any) -> str | None:
    """The node id a link points at.

    In the compiled form a link is `[node_id, output_index]`.
    """
    if isinstance(value, (list, tuple)) and value:
        first = value[0]
        if isinstance(first, str):
            return first
    if isinstance(value, str):
        return value
    return None


def _as_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _first_node(nodes: dict, class_types: Sequence[str]):
    for node_id, node in nodes.items():
        if _class_type(node) in class_types:
            return node_id, node
    return None, None


def _all_nodes(nodes: dict, class_types: Sequence[str]):
    return [
        (node_id, node)
        for node_id, node in nodes.items()
        if _class_type(node) in class_types
    ]


def derive_metadata_from_workflow(workflow: dict) -> dict[str, Any]:
    """The gallery's view of a job built from a graph.

    Only the keys the gallery and "Reuse parameters" read are produced, and
    only when the graph actually contains the node that implies them. A graph
    with no KSampler has no seed, and saying so is better than guessing.
    """
    metadata: dict[str, Any] = {"type": "t2i"}

    if not isinstance(workflow, dict):
        return metadata

    nodes = {node_id: node for node_id, node in _iter_nodes(workflow)}
    if not nodes:
        return metadata

    prompt: str | None = None
    negative_prompt: str | None = None
    seed = None
    steps = None
    cfg = None
    sampler = None
    scheduler = None
    width = None
    height = None
    batch_size = None

    _sampler_id, sampler_node = _first_node(nodes, KSAMPLER_NODE_CLASSES)
    if sampler_node is not None:
        sampler_inputs = _inputs(sampler_node)
        seed = _as_number(sampler_inputs.get("seed"))
        steps = _as_number(sampler_inputs.get("steps"))
        cfg = _as_number(sampler_inputs.get("cfg"))
        sampler = sampler_inputs.get("sampler_name")
        scheduler = sampler_inputs.get("scheduler")

        positive_id = _linked_node_id(sampler_inputs.get("positive"))
        negative_id = _linked_node_id(sampler_inputs.get("negative"))
        if positive_id and positive_id in nodes:
            text = _inputs(nodes[positive_id]).get("text")
            if isinstance(text, str):
                prompt = text
        if negative_id and negative_id in nodes:
            text = _inputs(nodes[negative_id]).get("text")
            if isinstance(text, str):
                negative_prompt = text

        latent_id = _linked_node_id(sampler_inputs.get("latent_image"))
        if latent_id and latent_id in nodes:
            latent_inputs = _inputs(nodes[latent_id])
            width = _as_number(latent_inputs.get("width"))
            height = _as_number(latent_inputs.get("height"))
            batch_size = _as_number(latent_inputs.get("batch_size"))

    if prompt is not None:
        metadata["prompt"] = prompt
    if negative_prompt is not None:
        metadata["negativePrompt"] = negative_prompt
    if seed is not None:
        metadata["seed"] = seed
    if steps is not None:
        metadata["steps"] = steps
    if cfg is not None:
        metadata["cfg"] = cfg
    if sampler:
        metadata["sampler"] = sampler
    if scheduler:
        metadata["scheduler"] = scheduler
    if width is not None:
        metadata["width"] = width
    if height is not None:
        metadata["height"] = height
    if batch_size is not None:
        metadata["batchSize"] = batch_size

    # The model. A UNETLoader means the graph runs a UNET, and the guided
    # path's `checkpoint` is the checkpoint - so the two are not the same
    # field, but the gallery shows one line for the model either way.
    _ckpt_id, checkpoint_node = _first_node(
        nodes, ["CheckpointLoaderSimple", "CheckpointLoader"]
    )
    if checkpoint_node is not None:
        checkpoint = _inputs(checkpoint_node).get("ckpt_name")
        if isinstance(checkpoint, str) and checkpoint:
            metadata["checkpoint"] = checkpoint
    else:
        _unet_id, unet_node = _first_node(nodes, ["UNETLoader"])
        if unet_node is not None:
            unet = _inputs(unet_node).get("unet_name")
            if isinstance(unet, str) and unet:
                metadata["checkpoint"] = unet
                metadata["unet"] = unet

    _vae_id, vae_node = _first_node(nodes, ["VAELoader"])
    if vae_node is not None:
        vae = _inputs(vae_node).get("vae_name")
        if isinstance(vae, str) and vae:
            metadata["vae"] = vae

    _dual_id, dual_node = _first_node(nodes, ["DualCLIPLoader"])
    if dual_node is not None:
        dual_inputs = _inputs(dual_node)
        clip = dual_inputs.get("clip_name1")
        clip2 = dual_inputs.get("clip_name2")
        if isinstance(clip, str) and clip:
            metadata["clip"] = clip
        if isinstance(clip2, str) and clip2:
            metadata["clip2"] = clip2
    else:
        _clip_id, clip_node = _first_node(nodes, ["CLIPLoader"])
        if clip_node is not None:
            clip = _inputs(clip_node).get("clip_name")
            if isinstance(clip, str) and clip:
                metadata["clip"] = clip

    loras = []
    for _node_id, lora_node in _all_nodes(nodes, ["LoraLoader"]):
        lora_inputs = _inputs(lora_node)
        name = lora_inputs.get("lora_name")
        if not isinstance(name, str) or not name:
            continue
        strength = _as_number(lora_inputs.get("strength_model"))
        loras.append({"name": name, "strength": strength if strength is not None else 1.0})
    if loras:
        metadata["loras"] = loras

    controlnets = []
    for _node_id, cn_node in _all_nodes(
        nodes, ["ControlNetApply", "ControlNetApplyAdvanced"]
    ):
        cn_inputs = _inputs(cn_node)
        loader_id = _linked_node_id(cn_inputs.get("control_net"))
        name = None
        if loader_id and loader_id in nodes:
            name = _inputs(nodes[loader_id]).get("control_net_name")
        strength = _as_number(cn_inputs.get("strength"))
        if isinstance(name, str) and name:
            controlnets.append(
                {
                    "name": name,
                    "image": "",
                    "strength": strength if strength is not None else 1.0,
                    "preprocessor": "None",
                }
            )
    if controlnets:
        metadata["controlnets"] = controlnets

    # IP-Adapter
    ip_adapters = []
    for _node_id, ip_node in _all_nodes(nodes, ["IPAdapterApply"]):
        ip_inputs = _inputs(ip_node)
        loader_id = _linked_node_id(ip_inputs.get("ipadapter"))
        model = None
        if loader_id and loader_id in nodes:
            model = _inputs(nodes[loader_id]).get("ipadapter_file")
        
        weight = _as_number(ip_inputs.get("weight"))
        stop_at = _as_number(ip_inputs.get("end_at"))
        
        clip_loader_id = _linked_node_id(ip_inputs.get("clip_vision"))
        clip_vision = None
        if clip_loader_id and clip_loader_id in nodes:
            clip_vision = _inputs(nodes[clip_loader_id]).get("clip_name")
            
        if isinstance(model, str) and model:
            ip_adapters.append({
                "model": model,
                "clipVision": clip_vision or "",
                "weight": weight if weight is not None else 1.0,
                "stopAt": stop_at if stop_at is not None else 1.0,
            })
    if ip_adapters:
        metadata["ipAdapters"] = ip_adapters

    # The enhancements. Each one is present in the graph as a node, and
    # absent from the graph as its absence, so the flags can be derived
    # exactly rather than guessed.
    if _all_nodes(nodes, ["FreeU_V2", "FreeU"]):
        metadata["enableFreeU"] = True
    pag_nodes = _all_nodes(nodes, ["PerturbedAttentionGuidance"])
    if pag_nodes:
        metadata["enablePAG"] = True
        pag_scale = _as_number(_inputs(pag_nodes[0][1]).get("scale"))
        if pag_scale is not None:
            metadata["pagScale"] = pag_scale
    if _all_nodes(nodes, ["LatentUpscale"]):
        metadata["enableLatentUpscale"] = True
        metadata["hiresFix"] = True

    latent_upscale_nodes = _all_nodes(nodes, ["LatentUpscaleBy"])
    if latent_upscale_nodes:
        metadata["hiresFix"] = True
        metadata["hiresUpscaler"] = "Latent"
        scale = _as_number(_inputs(latent_upscale_nodes[0][1]).get("scale_by"))
        if scale is not None:
            metadata["hiresUpscale"] = scale

    pixel_upscale_nodes = _all_nodes(nodes, ["ImageScaleBy"])
    if pixel_upscale_nodes:
        metadata["hiresFix"] = True
        metadata["hiresUpscaler"] = "Pixel"
        scale = _as_number(_inputs(pixel_upscale_nodes[0][1]).get("scale_by"))
        if scale is not None:
            metadata["hiresUpscale"] = scale

    _upscale_id, upscale_node = _first_node(nodes, ["UpscaleModelLoader"])
    if upscale_node is not None:
        upscale_model = _inputs(upscale_node).get("model_name")
        if isinstance(upscale_model, str) and upscale_model:
            metadata["hiresFix"] = True
            metadata["hiresUpscaler"] = upscale_model

    ksamplers = _all_nodes(nodes, KSAMPLER_NODE_CLASSES)
    if metadata.get("hiresFix") and len(ksamplers) > 1:
        hires_sampler_inputs = _inputs(ksamplers[-1][1])
        h_steps = _as_number(hires_sampler_inputs.get("steps"))
        h_denoise = _as_number(hires_sampler_inputs.get("denoise"))
        if h_steps is not None:
            metadata["hiresSteps"] = int(h_steps)
        if h_denoise is not None:
            metadata["hiresDenoise"] = h_denoise

    fd_nodes = _all_nodes(nodes, ["FaceDetailer"])
    if fd_nodes:
        metadata["adetailer"] = True
        fd_inputs = _inputs(fd_nodes[0][1])
        fd_steps = _as_number(fd_inputs.get("steps"))
        fd_denoise = _as_number(fd_inputs.get("denoise"))
        fd_prompt = fd_inputs.get("wildcard")
        fd_noise_mask = fd_inputs.get("noise_mask")
        if fd_steps is not None:
            metadata["adetailerSteps"] = int(fd_steps)
        if fd_denoise is not None:
            metadata["adetailerDenoise"] = fd_denoise
        if isinstance(fd_prompt, str) and fd_prompt:
            metadata["adetailerPrompt"] = fd_prompt
        if fd_noise_mask is not None:
            metadata["adetailerInpaintMasked"] = bool(fd_noise_mask)
        _bbox_id, bbox_node = _first_node(nodes, ["UltralyticsDetectorProvider"])
        if bbox_node is not None:
            detector = _inputs(bbox_node).get("model_name")
            if isinstance(detector, str) and detector:
                metadata["adetailerModel"] = detector.split("/")[-1]

    return metadata


def merge_metadata(*sources: dict[str, Any] | None) -> dict[str, Any]:
    """Merge metadata sources, later ones winning.

    Used to combine what the client sent with what the backend derived: the
    client's metadata is authoritative for the things only the client knows
    (the source image of an img2img, the model record's visual fields), and
    the derived metadata fills in the rest.
    """
    merged: dict[str, Any] = {}
    for source in sources:
        if isinstance(source, dict):
            merged.update(source)
    return merged
