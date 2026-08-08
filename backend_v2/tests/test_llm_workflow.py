from services.llm_workflow import build_llm_workflow


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
    assert metadata["workspace"] == "roleplay"
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
