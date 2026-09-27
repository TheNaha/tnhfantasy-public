"""Regression tests for `SaveImage.filename_prefix` in the image workflow.

`build_image_workflow(filename_prefix=...)` accepted the parameter and then
dropped it: there was no such field on `GeneratorOptions`, so
`build_core` always used `_generate_filename_prefix(mode)`. Six call sites
passed a meaningful value — `ChatIllustrate`, `StoryAgenticGen`, `AgenticGen` —
and every one of them produced a `T2I_<timestamp>` prefix instead, so the
origin of an image could not be read off its filename. The video path has
always honoured its own parameter; these tests pin that the two agree.
"""
from core.workflow_builder import (
    GeneratorOptions,
    WorkflowBuilder,
    build_image_job_workflow,
    build_image_workflow,
    build_video_job_workflow,
)


def _save_prefix(workflow: dict, class_type: str = "SaveImage") -> str:
    for node in workflow.values():
        if node.get("class_type") == class_type:
            return node["inputs"]["filename_prefix"]
    raise AssertionError(f"no {class_type} node in the workflow")


def _build(mode: str, **kwargs) -> dict:
    return WorkflowBuilder().build(
        GeneratorOptions(prompt="a lighthouse", mode=mode, inputImage="in.png", **kwargs)
    )


class TestImageFilenamePrefix:
    def test_an_explicit_prefix_is_used_verbatim(self):
        workflow = build_image_workflow(prompt="a lighthouse", filename_prefix="MY_CUSTOM_PREFIX")
        assert _save_prefix(workflow) == "MY_CUSTOM_PREFIX"

    def test_the_job_builder_forwards_it_too(self):
        workflow, _ = build_image_job_workflow(
            prompt="a lighthouse", filename_prefix="ChatIllustrate"
        )
        assert _save_prefix(workflow) == "ChatIllustrate"

    def test_omitting_it_still_derives_a_timestamped_prefix(self):
        """The default must not change. `None` means "derive", not "empty"."""
        workflow = build_image_workflow(prompt="a lighthouse")
        assert _save_prefix(workflow).startswith("T2I_")

    def test_the_derived_prefix_still_tracks_the_mode(self):
        for mode, expected in (
            ("t2i", "T2I_"),
            ("img2img", "Img2Img_"),
            ("inpaint", "Inpaint_"),
        ):
            assert _save_prefix(_build(mode)).startswith(expected), mode

    def test_an_explicit_prefix_overrides_the_mode_derived_one(self):
        workflow = _build("inpaint", filenamePrefix="StoryAgenticGen")
        assert _save_prefix(workflow) == "StoryAgenticGen"

    def test_image_and_video_agree_on_the_contract(self):
        """Both builders take the same parameter and both honour it. This is the
        asymmetry that let the image side rot unnoticed."""
        video, _ = build_video_job_workflow(
            prompt="a lighthouse", filename_prefix="ChatIllustrate"
        )
        assert _save_prefix(video, "VHS_VideoCombine") == "ChatIllustrate"

    def test_generator_options_carries_the_field(self):
        assert GeneratorOptions(prompt="x", filenamePrefix="P").filenamePrefix == "P"
        # And `None` is distinct from `""`, so an explicitly empty prefix is not
        # silently replaced by a derived one.
        assert GeneratorOptions(prompt="x").filenamePrefix is None
