from typing import Any


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
    workspace: str = "roleplay",
    source: str | None = None,
    parent_job_id: str | None = None,
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
