from typing import Any

# Per-entity LLM sampling override keys (Chat/Story columns; None = inherit global).
SAMPLER_KEYS = (
    "temperature",
    "top_p",
    "max_output_tokens",
    "frequency_penalty",
    "presence_penalty",
)


def sampler_overrides(entity) -> dict[str, Any]:
    """Extract non-None sampling overrides from a Chat/Story entity."""
    return {
        key: getattr(entity, key)
        for key in SAMPLER_KEYS
        if getattr(entity, key, None) is not None
    }


def build_llm_workflow(
    *,
    messages: list[dict[str, Any]],
    type_: str,
    chat_id: str | None = None,
    story_id: str | None = None,
    chapter_id: str | None = None,
    character_id: str | None = None,
    character_system_prompt: str | None = None,
    model: str | None = None,
    workspace: str = "chat",
    source: str | None = None,
    parent_job_id: str | None = None,
    samplers: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a standardized LLM job workflow + metadata pair.

    Returns:
        (workflow, metadata)
    """
    workflow: dict[str, Any] = {
        "messages": messages,
        "type": type_,
        "model": model,
    }
    if samplers:
        workflow.update(samplers)
    if chat_id is not None:
        workflow["chat_id"] = chat_id
    if story_id is not None:
        workflow["story_id"] = story_id
    if chapter_id is not None:
        workflow["chapter_id"] = chapter_id
    if character_system_prompt is not None:
        workflow["character_system_prompt"] = character_system_prompt

    metadata: dict[str, Any] = {
        "chat_id": chat_id,
        "character_id": character_id,
        "workspace": workspace,
        "type": type_,
    }
    if story_id is not None:
        metadata["story_id"] = story_id
    if chapter_id is not None:
        metadata["chapter_id"] = chapter_id
    if source is not None:
        metadata["source"] = source
    if parent_job_id is not None:
        metadata["parent_job_id"] = parent_job_id
    if extra_metadata:
        metadata.update(extra_metadata)

    return workflow, metadata


def build_chat_llm_workflow(
    messages: list[dict[str, Any]],
    *,
    chat_id: str,
    character_id: str | None = None,
    system_prompt: str | None = None,
    model: str | None = None,
    type_: str = "chat_reply",
    workspace: str = "chat",
    source: str | None = None,
    samplers: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build an LLM workflow for a chat reply with pre-filled common metadata.

    Pre-fills chat_id, character_id, workspace, and type so callers don't have
    to repeat them on every route.
    """
    metadata: dict[str, Any] = {
        "chat_id": chat_id,
        "character_id": character_id,
        "workspace": workspace,
        "type": type_,
    }
    if source is not None:
        metadata["source"] = source
    if extra_metadata:
        metadata.update(extra_metadata)

    return build_llm_workflow(
        messages=messages,
        type_=type_,
        chat_id=chat_id,
        character_id=character_id,
        character_system_prompt=system_prompt,
        model=model,
        workspace=workspace,
        source=source,
        samplers=samplers,
        extra_metadata=metadata,
    )

