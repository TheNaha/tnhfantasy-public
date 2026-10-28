"""What a provider can actually do.

The Enhancements panel used to hardcode the provider's node vocabulary in
Python - `FreeU_V2`, `PerturbedAttentionGuidance`, `FaceDetailer`,
`UltralyticsDetectorProvider`, `UpscaleModelLoader` - and emitted them
into the graph whatever the provider had installed.

So the panel offered a FreeU toggle to a provider with no FreeU node, and
the request failed at dispatch with "node type not found", long after the
user had picked the enhancement. The panel could not know, because it
never asked.

This module derives the answer from the provider's OWN node graph - the
`object_info` the backend already fetches, caches and digests for the
Advanced Generator's node palette. The digest keeps each input's
specification, and a combination input's specification keeps its option
list, so the digest already says both "does this provider have the node
class" and "which files does it have for this input".

Nothing here is a guess: a node is supported because the provider's graph
contains it, and a model list is the provider's own list of files.
"""

from typing import Any

# The node classes the guided path can emit, grouped by what they are for.
#
# The VALUES are the class names the provider may use. Several spellings
# exist for some of them, because ComfyUI custom node packs renamed theirs
# between versions and the providers run different versions.
ENHANCEMENT_NODE_CLASSES: dict[str, tuple[str, ...]] = {
    "freeu": ("FreeU_V2", "FreeU"),
    "pag": ("PerturbedAttentionGuidance",),
    "adetailer": ("FaceDetailer",),
    "detector": ("UltralyticsDetectorProvider",),
    "upscale_model": ("UpscaleModelLoader",),
    # The builder emits `LatentUpscaleBy` (core/workflow_builder.py:318). The
    # probe looked for `LatentUpscale`, which is a DIFFERENT node - the
    # one that takes an explicit upscale model rather than a multiplier. So
    # the key was never True for any provider, and the panel's "latent
    # upscale" support was reported as unsupported everywhere.
    "latent_upscale": ("LatentUpscaleBy", "LatentUpscale"),
    "controlnet": ("ControlNetApply", "ControlNetApplyAdvanced"),
    # The IPAdapter chain the builder emits: `IPAdapterModelLoader`,
    # `CLIPVisionLoader` and `IPAdapterApply`. There was no key for it at
    # all, so the IPAdapter section was offered to every provider and the
    # request failed at dispatch on a provider without the pack.
    "ipadapter": ("IPAdapterApply", "IPAdapterModelLoader"),
    "grow_mask": ("GrowMask",),
    "feather_mask": ("FeatherMask",),
    "canny": ("CannyEdgePreprocessor",),
    "depth": ("MiDaS-DepthMapPreprocessor", "Zoe-DepthMapPreprocessor", "DepthAnythingPreprocessor", "DepthPreprocessor"),
    "openpose": ("OpenposePreprocessor", "DWPreprocessor"),
    "tiled_vae": ("VAEDecodeTiled", "VAEDecode"),
    # The KSampler node carries the sampler_name and scheduler combo inputs.
    # Its presence alone doesn't tell us which samplers/schedulers the
    # provider supports — for that we read the input option lists below.
    "ksampler": ("KSampler", "KSampler (Efficient)", "KSamplerAdvanced"),
}

# Node class + input name for the sampler and scheduler combo inputs on
# KSampler-like nodes. Used to derive which sampler/scheduler names the
# provider actually advertises.
_SAMPLER_SCHEDULER_INPUTS: dict[str, tuple[str, str]] = {
    "sampler": ("KSampler", "sampler_name"),
    "scheduler": ("KSampler", "scheduler"),
}

# The inputs whose option list is a list of FILE NAMES.
_MODEL_INPUTS: dict[str, tuple[str, ...]] = {
    "upscale_model": ("UpscaleModelLoader",),
    "detector": ("UltralyticsDetectorProvider",),
    "checkpoint": ("CheckpointLoaderSimple", "CheckpointLoader"),
    "lora": ("LoraLoader",),
}

# The input name that holds the file list, per node class.
_MODEL_INPUT_NAMES: dict[str, str] = {
    "UpscaleModelLoader": "model_name",
    "UltralyticsDetectorProvider": "model_name",
    "CheckpointLoaderSimple": "ckpt_name",
    "CheckpointLoader": "ckpt_name",
    "LoraLoader": "lora_name",
}


def _node_class_type(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    return str(node.get("class_type") or node.get("type") or "")


def _iter_nodes(graph: dict):
    """Yield `(class_type, node)` for every node in a graph.

    Three shapes are in play, and they are told apart by their structure:

      * the object_info form - `{ClassType: {"input": {...}, ...}}`, which is
        what the provider itself publishes and what the backend's digest
        keeps. The CLASS TYPE IS THE KEY;
      * the compiled form - `{"3": {"class_type": ..., "inputs": {...}}}`,
        which is what the builder produces, where the key is a node id;
      * the editor form - `{"nodes": [{"id": ..., "type": ...}]}`.
    """
    if not isinstance(graph, dict):
        return
    nodes = graph.get("nodes")
    if isinstance(nodes, dict):
        for node_id, node in nodes.items():
            if isinstance(node, dict):
                yield str(node_id), node
        return
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict) and node.get("id") is not None:
                yield str(node["id"]), node
        return
    for key, node in graph.items():
        if not isinstance(node, dict):
            continue
        if "class_type" in node:
            # The compiled form: the key is a node id.
            yield str(node["class_type"]), node
        else:
            # The object_info form: the key IS the class type.
            yield str(key), node


def _combo_options(node: dict, input_name: str) -> list[str]:
    """The option list of a combination input.

    In a ComfyUI node definition the input is `[type, {default: ...}]`, and
    for a combination the type IS the list of options. The backend's
    `node_schema_digest` keeps that list, so the digest is enough.
    """
    inputs = node.get("input")
    if not isinstance(inputs, dict):
        return []
    for section in ("required", "optional"):
        body = inputs.get(section)
        if not isinstance(body, dict):
            continue
        spec = body.get(input_name)
        if not isinstance(spec, (list, tuple)) or not spec:
            continue
        head = spec[0]
        if isinstance(head, list):
            return [str(option) for option in head]
    return []


def derive_capabilities(graph: dict, provider_id: str | None = None) -> dict[str, Any]:
    """What the provider can do, from its node graph.

    `known` is False when the graph could not be read. The panel then says
    "unknown" rather than "unsupported" - a provider that is down must not
    be read as a provider that cannot do FreeU.
    """
    if not isinstance(graph, dict) or not graph:
        return {
            "provider_id": provider_id,
            "known": False,
            "nodes": {key: None for key in ENHANCEMENT_NODE_CLASSES},
            "models": {},
            "reason": "The provider's node definitions are not available.",
        }

    nodes_by_class: dict[str, dict] = {}
    for class_type, node in _iter_nodes(graph):
        if class_type and class_type not in nodes_by_class:
            nodes_by_class[class_type] = node

    supported: dict[str, bool] = {}
    resolved_class: dict[str, str | None] = {}
    for key, class_names in ENHANCEMENT_NODE_CLASSES.items():
        found = next((name for name in class_names if name in nodes_by_class), None)
        supported[key] = found is not None
        resolved_class[key] = found

    models: dict[str, list[str]] = {}
    for key, class_names in _MODEL_INPUTS.items():
        for class_name in class_names:
            node = nodes_by_class.get(class_name)
            if node is None:
                continue
            input_name = _MODEL_INPUT_NAMES.get(class_name)
            if not input_name:
                continue
            options = _combo_options(node, input_name)
            if options:
                models[key] = options
            break

    # Sampler / scheduler combo options from the KSampler node.
    samplers: list[str] = []
    schedulers: list[str] = []
    for key, (class_name, input_name) in _SAMPLER_SCHEDULER_INPUTS.items():
        node = nodes_by_class.get(class_name)
        if node is None:
            continue
        options = _combo_options(node, input_name)
        if not options:
            continue
        if key == "sampler":
            samplers = options
        elif key == "scheduler":
            schedulers = options

    return {
        "provider_id": provider_id,
        "known": True,
        "nodes": supported,
        "node_classes": resolved_class,
        "models": models,
        "samplers": samplers,
        "schedulers": schedulers,
    }


def supports(capabilities: dict[str, Any] | None, key: str) -> bool | None:
    """Whether the provider supports a capability.

    None means "not known" - the provider's graph was not available. The
    caller has to treat that differently from "no": a provider that is
    down is not a provider that cannot do FreeU.
    """
    if not capabilities or not capabilities.get("known"):
        return None
    value = capabilities.get("nodes", {}).get(key)
    return None if value is None else bool(value)


def model_list(capabilities: dict[str, Any] | None, key: str) -> list[str] | None:
    """The provider's own list of files for a model input, if it has one."""
    if not capabilities or not capabilities.get("known"):
        return None
    return capabilities.get("models", {}).get(key)


def sampler_list(capabilities: dict[str, Any] | None) -> list[str] | None:
    """The sampler names the provider's KSampler node advertises.

    None when the provider's graph is not known (provider down / not yet
    probed). Callers must treat None differently from an empty list: an
    empty list means the provider has no sampler info; None means "we
    don't know yet".
    """
    if not capabilities or not capabilities.get("known"):
        return None
    return capabilities.get("samplers")


def scheduler_list(capabilities: dict[str, Any] | None) -> list[str] | None:
    """The scheduler names the provider's KSampler node advertises.

    None when the provider's graph is not known. See `sampler_list`.
    """
    if not capabilities or not capabilities.get("known"):
        return None
    return capabilities.get("schedulers")


def provider_supports_sampler(
    capabilities: dict[str, Any] | None, sampler_name: str
) -> bool | None:
    """Whether the provider supports a sampler name.

    True if advertised, False if not advertised, None if unknown.
    """
    options = sampler_list(capabilities)
    if options is None:
        return None
    return sampler_name in options


def provider_supports_scheduler(
    capabilities: dict[str, Any] | None, scheduler_name: str
) -> bool | None:
    """Whether the provider supports a scheduler name.

    True if advertised, False if not advertised, None if unknown.
    """
    options = scheduler_list(capabilities)
    if options is None:
        return None
    return scheduler_name in options
