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
    model: str | None = None,
    workspace: str = "chat",
    source: str | None = None,
    parent_job_id: str | None = None,
    samplers: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
    background: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a standardized LLM job workflow + metadata pair.

    There is deliberately no `character_system_prompt` parameter. There used
    to be one, and it wrote `workflow["character_system_prompt"]` — a key
    that **no engine reads**. The LLM engines only ever read
    `workflow["messages"]` (`services/engines/llm_engine.py`), and the
    character card is already the first system message in `messages`, because
    `context_builder.build_chat_context_with_sections` puts it there.

    So the key was a duplicate of something already being sent, and it was
    the place the chain path put the character agent's variant template —
    which is why that variant was silently lost on every autonomous turn
    while the code looked like it was passing it. The parameter is gone
    rather than left as a no-op, so the next person cannot make the same
    mistake.

    Returns:
        (workflow, metadata)
    """
    workflow: dict[str, Any] = {
        "messages": messages,
        "type": type_,
        "model": model,
    }

    # A background job is rendered differently, or not at all. The frontend's
    # streaming reducer keys on `chat_id` and shows a reply bubble for anything
    # that carries one, so a background job that reuses the chat id — memory
    # extraction does — has to be marked, or it appears as a second phantom
    # "X is thinking…" under the reply it was derived from.
    if background:
        workflow["background"] = True

    # The ROLE's sampler is the base; a caller's samplers win on top.
    #
    # This is what makes two roles on one shared model behave differently. An
    # rp finetune asked for extraction at temperature 1.0 produces a different
    # memory set every run, so `util` is deliberately cold while `rp` is not —
    # and when both roles resolve to the SAME weights, this is the only thing
    # separating a prose reply from an extraction.
    #
    # The registry's per-model samplers were never applied at all before this —
    # `sampler_for` had no production caller — so the guard against Artemis's
    # reasoning eating `max_tokens` before any prose was inert, and the empty
    # reply it was written to prevent was avoided only by the accident of no
    # limit being sent at all.
    try:
        from services.llm_router import get_router

        role_sampler = get_router().registry.role_sampler(
            get_router().role_for_kind(type_)
        )
    except Exception:
        role_sampler = {}
    if role_sampler:
        workflow.update(role_sampler)
        if "max_tokens" in role_sampler and "max_output_tokens" not in role_sampler:
            workflow["max_output_tokens"] = role_sampler["max_tokens"]

    if samplers:
        workflow.update(samplers)
    if chat_id is not None:
        workflow["chat_id"] = chat_id
    if story_id is not None:
        workflow["story_id"] = story_id
    if chapter_id is not None:
        workflow["chapter_id"] = chapter_id

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
    if background:
        metadata["background"] = True

    return workflow, metadata


def build_chat_llm_workflow(
    messages: list[dict[str, Any]],
    *,
    chat_id: str,
    character_id: str | None = None,
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

    The character card is the first message in `messages` — put it there by
    `context_builder.build_context`, which is the single place the prompt is
    assembled. There is no separate "system prompt" argument, because a
    separate argument is a second source of truth for the same text, and the
    last one written was the one nothing read.
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
        model=model,
        workspace=workspace,
        source=source,
        samplers=samplers,
        extra_metadata=metadata,
    )

