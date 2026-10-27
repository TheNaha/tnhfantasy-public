"""The post-processing every generation gets, whichever way it was built.

There are two ways to ask for an image:

  * **guided** - the client sends a parameter dict and the backend compiles a
    ComfyUI graph (`core.workflow_builder.WorkflowBuilder`).
  * **graph** - the client compiled the graph itself and sends it whole
    (the Advanced Generator).

The guided path expanded the prompt shortcuts and checked that every
referenced embedding file exists before the text reached ComfyUI. The graph
path did neither: the client had compiled the graph, so the text went out
with its shortcuts unexpanded and with embedding references that might not
exist at all. A missing embedding surfaces as a provider-side failure long
after the request that caused it, with nothing in the request to explain it.

So both paths get the same treatment, and this module is the shared
implementation of it.

It lives outside `workflow_builder` because `workflow_builder` imports it,
and a shared module that imports the module that uses it is a cycle.
"""

import os
import re

from core.exceptions import ValidationError

#: File extensions recognised for embedding files in `models/embeddings/`.
_EMBEDDING_EXTENSIONS = (".safetensors", ".pt", ".bin", ".ckpt")


def _resolve_embeddings_dir() -> str:
    """Return the absolute path to `models/embeddings/`.

    Uses `settings.input_dir` (default `data/input`) and resolves `models/`
    as a sibling directory, mirroring how ComfyUI lays out its model tree.
    """
    from config import settings

    data_dir = os.path.dirname(os.path.abspath(settings.input_dir))
    return os.path.join(data_dir, "models", "embeddings")


def embedding_file_exists(name: str) -> bool:
    """Check whether an embedding file exists for `name`.

    Tries the name verbatim first, then appends each known extension.
    Checks the local filesystem first (if models/embeddings/ is present),
    and falls back to checking registered models in the database catalog
    (for serverless or remote providers where weights live on worker volumes).
    """
    candidates = [name]
    base_name = os.path.basename(name)
    if not os.path.splitext(name)[1]:
        candidates = [name + ext for ext in _EMBEDDING_EXTENSIONS] + [name]
        if base_name != name:
            candidates += [base_name + ext for ext in _EMBEDDING_EXTENSIONS] + [base_name]
    elif base_name != name:
        candidates.append(base_name)

    embeddings_dir = _resolve_embeddings_dir()
    if os.path.isdir(embeddings_dir):
        for cand in candidates:
            if os.path.isfile(os.path.join(embeddings_dir, cand)):
                return True

    # Fallback to DB catalog for remote/cloud providers where models are not mounted locally
    try:
        from api.deps import get_session_sync
        from sqlmodel import select
        from core.entities import ModelFile, ModelV2, ModelVersion

        with get_session_sync() as session:
            stmt = (
                select(ModelFile.id)
                .join(ModelVersion, ModelVersion.id == ModelFile.version_id)
                .join(ModelV2, ModelV2.id == ModelVersion.model_id)
                .where(ModelV2.directory.in_(["embeddings", "models/embeddings"]))
                .where(
                    (ModelFile.storage_filename.in_(candidates))
                    | (ModelFile.original_filename.in_(candidates))
                    | (ModelV2.name.in_(candidates))
                )
            )
            if session.exec(stmt).first():
                return True
    except Exception:
        pass

    return False


def extract_embedding_names(text: str) -> list[str]:
    """Extract `embedding:NAME` tokens from a prompt string.

    Supports bare syntax (`embedding:name`), optional weights (`(embedding:name:1.1)`),
    subdirectories, and file extensions. Returns a list of embedding names.
    """
    return re.findall(
        r"embedding:([a-zA-Z0-9_\-./]+?)(?::[0-9.]+(?=[)\s,]|$)|(?=[)\s,]|$))",
        text,
    )


def expand_prompt_shortcuts(text: str) -> str:
    """Expand configured prompt shortcut tokens in `text`.

    Shortcut names are matched on word boundaries, longest-first, so
    `lazypos_v2` takes precedence over `lazypos`. Unmatched text passes
    through unchanged.

    Tokens preceded by `embedding:` (e.g. `embedding:lazypos` or
    `(embedding:lazyneg:1.1)`) are preserved untouched so textual inversion
    files are not corrupted by text shortcut substitutions.
    """
    from config import get_config

    shortcuts = (get_config().get("generator", {}) or {}).get("prompt_shortcuts", {})
    if not shortcuts:
        return text

    # Fixed-width negative lookbehinds prevent rewriting tokens that are part
    # of an embedding declaration (`embedding:NAME` or `embedding: NAME`).
    pattern = re.compile(
        r"(?<!embedding:)(?<!embedding:\s)\b("
        + "|".join(re.escape(name) for name in sorted(shortcuts, key=len, reverse=True))
        + r")\b"
    )
    return pattern.sub(lambda m: shortcuts[m.group(0)], text)


def postprocess_prompt_text(text: str, *, field: str = "prompt", seed: int | None = None) -> str:
    """Expand wildcards, shortcuts in one prompt string and check its embeddings.

    Raises `ValidationError` when an embedding file is missing - the same
    error the guided path has always raised, and for the same reason: a
    missing embedding is a request that cannot succeed, and the user should
    hear about it now rather than through a provider error later.
    """
    from services.wildcard_service import WildcardService

    wildcard_expanded = WildcardService.expand_wildcards(text, seed=seed)
    expanded = expand_prompt_shortcuts(wildcard_expanded)

    embedding_names = extract_embedding_names(expanded)
    if embedding_names:
        missing = [n for n in embedding_names if not embedding_file_exists(n)]
        if missing:
            raise ValidationError(
                "Embedding file(s) not found in models/embeddings/: "
                + ", ".join(missing),
                field=field,
            )

    return expanded


def _iter_text_nodes(workflow: dict):
    """Yield `(node_id, node)` for every node in a compiled ComfyUI graph.

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

    # The compiled form: the mapping IS the nodes.
    for node_id, node in workflow.items():
        if isinstance(node, dict) and "class_type" in node:
            yield str(node_id), node


def _node_class_type(node: dict) -> str:
    return str(node.get("class_type") or node.get("type") or "")


def postprocess_graph(workflow: dict) -> list[str]:
    """Apply the prompt post-processing to every text input of a graph.

    Every `CLIPTextEncode` node's `text` input is expanded and checked.
    The graph is modified in place, because the client sent it whole and
    there is nothing to hand back - the job runs the graph that was sent.

    Returns a list of warnings. It is empty today; the graph path reports
    what it could not fix rather than changing the user's graph, and this
    is where that reporting happens.
    """
    warnings: list[str] = []
    if not isinstance(workflow, dict):
        return warnings

    for _node_id, node in _iter_text_nodes(workflow):
        if _node_class_type(node) != "CLIPTextEncode":
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        text = inputs.get("text")
        if not isinstance(text, str) or not text:
            continue
        inputs["text"] = postprocess_prompt_text(text)

    return warnings
