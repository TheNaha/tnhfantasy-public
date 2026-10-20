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

from typing import Any


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


def _first_node(nodes: dict, class_types: list[str]):
    for node_id, node in nodes.items():
        if _class_type(node) in class_types:
            return node_id, node
    return None, None


def _all_nodes(nodes: dict, class_types: list[str]):
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

    _sampler_id, sampler_node = _first_node(nodes, ["KSampler", "KSamplerAdvanced"])
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

    # The enhancements. Each one is present in the graph as a node, and
    # absent from the graph as its absence, so the flags can be derived
    # exactly rather than guessed.
    if _all_nodes(nodes, ["FreeU_V2", "FreeU"]):
        metadata["enableFreeU"] = True
    if _all_nodes(nodes, ["PerturbedAttentionGuidance"]):
        metadata["enablePAG"] = True
    if _all_nodes(nodes, ["LatentUpscale"]):
        metadata["enableLatentUpscale"] = True
        metadata["hiresFix"] = True

    _upscale_id, upscale_node = _first_node(nodes, ["UpscaleModelLoader"])
    if upscale_node is not None:
        upscale_model = _inputs(upscale_node).get("model_name")
        if isinstance(upscale_model, str) and upscale_model:
            metadata["hiresFix"] = True
            metadata["hiresUpscaler"] = upscale_model

    if _all_nodes(nodes, ["FaceDetailer"]):
        metadata["adetailer"] = True
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
