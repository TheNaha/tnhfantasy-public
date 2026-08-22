"""Regression tests for the AnimateDiff / video workflow builder.

The video workflow MUST return bare ComfyUI nodes (matching the image
builder), NOT a wrapped ``{"prompt": nodes, "type": "video"}`` shape.
The provider worker posts ``{"prompt": <workflow>}`` to ComfyUI, so a
nested wrapper would make ComfyUI reject the prompt (P1 bug).
"""
from core.workflow_builder import build_video_job_workflow


class TestVideoWorkflowShape:
    def test_video_workflow_is_bare_nodes(self):
        workflow, metadata = build_video_job_workflow(prompt="a hero", character_id="c1")
        # Must NOT be wrapped in a "prompt" key.
        assert "prompt" not in workflow or not isinstance(workflow.get("prompt"), dict)
        # Nodes are keyed by id and carry class_type.
        assert isinstance(workflow, dict)
        assert all("class_type" in node for node in workflow.values())
        # VHS_VideoCombine must be present for video output.
        assert any(
            node.get("class_type") == "VHS_VideoCombine" for node in workflow.values()
        )

    def test_video_metadata_carries_type_and_ids(self):
        workflow, metadata = build_video_job_workflow(
            prompt="a hero",
            character_id="c1",
            chat_id="chat1",
            story_id="story1",
        )
        assert metadata["type"] == "video"
        assert metadata["character_id"] == "c1"
        assert metadata["chat_id"] == "chat1"
        assert metadata["story_id"] == "story1"

    def test_video_workflow_node_count_is_meaningful(self):
        workflow, _ = build_video_job_workflow(prompt="x")
        # Bare nodes -> progress accounting (len(workflow)) is correct.
        assert len(workflow) >= 5
