from core.workflow_builder import (
    ControlNetOption,
    GeneratorOptions,
    WorkflowBuilder,
)


def test_workflow_builder_controlnet_canny():
    builder = WorkflowBuilder()
    opts = GeneratorOptions(
        prompt="1girl, outdoor",
        controlnets=[
            ControlNetOption(
                name="control_v11p_sd15_canny.pth",
                image="input_canny.png",
                preprocessor="Canny",
                strength=0.8,
            )
        ],
    )
    workflow = builder.build(opts)
    classes = [node["class_type"] for node in workflow.values()]

    assert "ControlNetLoader" in classes
    assert "CannyEdgePreprocessor" in classes
    assert "ControlNetApply" in classes


def test_workflow_builder_controlnet_depth_and_openpose():
    builder = WorkflowBuilder()
    opts = GeneratorOptions(
        prompt="1girl, walking in street",
        controlnets=[
            ControlNetOption(
                name="control_depth.pth",
                image="depth_ref.png",
                preprocessor="Depth",
                strength=0.75,
            ),
            ControlNetOption(
                name="control_openpose.pth",
                image="pose_ref.png",
                preprocessor="OpenPose",
                strength=0.9,
            ),
        ],
    )
    workflow = builder.build(opts)
    classes = [node["class_type"] for node in workflow.values()]

    assert "MiDaS-DepthMapPreprocessor" in classes
    assert "OpenposePreprocessor" in classes
    assert classes.count("ControlNetApply") == 2


def test_workflow_builder_inpaint_outpainting():
    builder = WorkflowBuilder()
    opts = GeneratorOptions(
        mode="inpaint",
        prompt="beautiful extended background",
        inputImage="scene.png",
        maskImage="mask.png",
        outpaintLeft=64,
        outpaintRight=64,
    )
    workflow = builder.build(opts)
    classes = [node["class_type"] for node in workflow.values()]

    assert "ImagePadForOutpaint" in classes
    assert "VAEEncodeForInpaint" in classes


def test_workflow_builder_tiled_vae_for_large_resolution():
    # Capabilities with tiled_vae supported and known=True
    capabilities = {"known": True, "nodes": {"tiled_vae": True}}
    builder = WorkflowBuilder(capabilities=capabilities)
    opts = GeneratorOptions(
        prompt="hyperdetailed 2K landscape",
        width=1536,
        height=1536,
    )
    workflow = builder.build(opts)
    classes = [node["class_type"] for node in workflow.values()]

    assert "VAEDecodeTiled" in classes
