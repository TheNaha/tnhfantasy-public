
from core.workflow_builder import GeneratorOptions, WorkflowBuilder


def test_img2img_adds_image_scale_when_dimensions_specified():
    builder = WorkflowBuilder()
    options = GeneratorOptions(
        prompt="A photo of a cyberpunk city",
        checkpoint="v1-5-pruned-emaonly.safetensors",
        mode="img2img",
        inputImage="test_input.png",
        width=768,
        height=512,
        batchSize=1,
    )
    workflow = builder.build(options)

    # Find ImageScale node
    scale_nodes = [n for n in workflow.values() if n.get("class_type") == "ImageScale"]
    assert len(scale_nodes) == 1
    scale_inputs = scale_nodes[0]["inputs"]
    assert scale_inputs["width"] == 768
    assert scale_inputs["height"] == 512
    assert scale_inputs["upscale_method"] == "lanczos"

    # Verify VAEEncode takes pixels from ImageScale
    scale_node_id = [k for k, v in workflow.items() if v.get("class_type") == "ImageScale"][0]
    vae_nodes = [n for n in workflow.values() if n.get("class_type") == "VAEEncode"]
    assert len(vae_nodes) == 1
    assert vae_nodes[0]["inputs"]["pixels"][0] == scale_node_id


def test_img2img_adds_repeat_latent_batch_when_batch_size_greater_than_one():
    builder = WorkflowBuilder()
    options = GeneratorOptions(
        prompt="A portrait of an adventurer",
        checkpoint="v1-5-pruned-emaonly.safetensors",
        mode="img2img",
        inputImage="test_input.png",
        batchSize=3,
    )
    workflow = builder.build(options)

    # Find RepeatLatentBatch node
    repeat_nodes = [n for n in workflow.values() if n.get("class_type") == "RepeatLatentBatch"]
    assert len(repeat_nodes) == 1
    assert repeat_nodes[0]["inputs"]["amount"] == 3

    # KSampler takes latent from RepeatLatentBatch
    repeat_node_id = [k for k, v in workflow.items() if v.get("class_type") == "RepeatLatentBatch"][0]
    ksampler = [n for n in workflow.values() if n.get("class_type") == "KSampler"][0]
    assert ksampler["inputs"]["latent_image"][0] == repeat_node_id


def test_inpaint_falls_back_to_native_grow_mask_when_unsupported():
    # Capabilities where grow_mask is unsupported
    capabilities = {
        "known": True,
        "nodes": {
            "grow_mask": False,
            "feather_mask": False,
        },
    }
    builder = WorkflowBuilder(capabilities=capabilities)
    options = GeneratorOptions(
        prompt="Inpaint background with flowers",
        checkpoint="v1-5-pruned-emaonly.safetensors",
        mode="inpaint",
        inputImage="source.png",
        maskImage="mask.png",
        growMask=8,
        maskBlur=4,
        batchSize=2,
    )
    workflow = builder.build(options)

    # GrowMask and FeatherMask should NOT be in workflow
    class_types = [n.get("class_type") for n in workflow.values()]
    assert "GrowMask" not in class_types
    assert "FeatherMask" not in class_types

    # VAEEncodeForInpaint should have grow_mask_by=8
    inpaint_node = [n for n in workflow.values() if n.get("class_type") == "VAEEncodeForInpaint"][0]
    assert inpaint_node["inputs"]["grow_mask_by"] == 8

    # RepeatLatentBatch should be present for batchSize=2
    repeat_nodes = [n for n in workflow.values() if n.get("class_type") == "RepeatLatentBatch"]
    assert len(repeat_nodes) == 1
    assert repeat_nodes[0]["inputs"]["amount"] == 2

    # FeatherMask unsupported warning should be recorded
    assert any("Mask blur" in w for w in builder.warnings)
