from services.llm_workflow import build_llm_workflow, sampler_overrides


def test_build_llm_workflow_chat_reply():
    workflow, metadata = build_llm_workflow(
        messages=[{"role": "user", "content": "hi"}],
        type_="chat_reply",
        chat_id="chat-1",
        character_id="char-1",
        model="llm-local",
    )
    assert workflow["type"] == "chat_reply"
    assert workflow["chat_id"] == "chat-1"
    assert workflow["model"] == "llm-local"
    assert metadata["workspace"] == "chat"
    assert metadata["chat_id"] == "chat-1"
    assert metadata["type"] == "chat_reply"


def test_build_llm_workflow_story_continue():
    workflow, metadata = build_llm_workflow(
        messages=[{"role": "user", "content": "continue"}],
        type_="story_continue",
        story_id="story-1",
        chapter_id="chapter-1",
        model="llm-local",
        workspace="story",
    )
    assert workflow["type"] == "story_continue"
    assert workflow["story_id"] == "story-1"
    assert metadata["story_id"] == "story-1"
    assert metadata["workspace"] == "story"


def test_build_llm_workflow_narrator_with_source():
    workflow, metadata = build_llm_workflow(
        messages=[{"role": "user", "content": "narrate"}],
        type_="narrator",
        chat_id="chat-1",
        source="narrator",
        parent_job_id="parent-1",
    )
    assert workflow["type"] == "narrator"
    assert metadata["source"] == "narrator"
    assert metadata["parent_job_id"] == "parent-1"


def test_build_llm_workflow_extra_metadata():
    workflow, metadata = build_llm_workflow(
        messages=[],
        type_="chat_reply",
        chat_id="chat-1",
        extra_metadata={"agentic": True, "orchestrator_depth": 0},
    )
    assert metadata["agentic"] is True
    assert metadata["orchestrator_depth"] == 0


class _Entity:
    temperature = 0.35
    top_p = None
    max_output_tokens = 512
    frequency_penalty = None
    presence_penalty = 0.2


def test_sampler_overrides_extracts_only_set_fields():
    overrides = sampler_overrides(_Entity())
    assert overrides == {
        "temperature": 0.35,
        "max_output_tokens": 512,
        "presence_penalty": 0.2,
    }


def test_sampler_overrides_handles_none_entity():
    assert sampler_overrides(None) == {}


def test_build_llm_workflow_includes_samplers():
    workflow, _ = build_llm_workflow(
        messages=[],
        type_="chat_reply",
        chat_id="chat-1",
        samplers=sampler_overrides(_Entity()),
    )
    assert workflow["temperature"] == 0.35
    assert workflow["max_output_tokens"] == 512
    assert workflow["presence_penalty"] == 0.2
    assert "top_p" not in workflow
    assert "frequency_penalty" not in workflow
