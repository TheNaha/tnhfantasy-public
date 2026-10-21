"""The Flux/AuraFlow generation path (audit-2026-10-21 §1).

Every guided surface sends `checkpoint: null` for a UNET model, because a
UNET lives in `models/unet/` and there is no checkpoint to name. The option
model declared `checkpoint` as a bare `str` while its four siblings were
`str | None`, so every such request died in pydantic validation - before a
job was created, and before the Missing-Models dialog that would have
explained why.
"""

import pytest

from core.exceptions import ValidationError
from core.workflow_builder import GeneratorOptions, WorkflowBuilder


def _flux_options(**overrides):
    base = {
        "prompt": "a lighthouse in a storm",
        "checkpoint": None,
        "unet": "flux1-dev.safetensors",
        "clip": "clip_l.safetensors",
        "clip2": "t5xx_l_encoder_fp8.safetensors",
        "modelType": "flux",
    }
    base.update(overrides)
    return base


class TestUnetOptionsValidate:
    def test_a_null_checkpoint_is_accepted(self):
        """The client's UNET payload must validate."""
        options = GeneratorOptions(**_flux_options())
        assert options.checkpoint is None
        assert options.unet == "flux1-dev.safetensors"

    def test_the_whole_frontend_payload_validates(self):
        """The exact shape the frontend sends, field for field."""
        payload = {
            "mode": "t2i",
            "prompt": "a cat",
            "negativePrompt": "",
            "seed": 1,
            "steps": 20,
            "cfg": 7.0,
            "sampler": "euler",
            "scheduler": "normal",
            "loras": [],
            "controlnets": [],
            "ipAdapters": [],
            "clipSkip": 1,
            "enableFreeU": False,
            "enablePAG": False,
            "pagScale": 3.0,
            "enableLatentUpscale": False,
            "latentUpscaleMultiplier": 1.5,
            "adetailer": False,
            "adetailerModel": None,
            "adetailerPrompt": "",
            "adetailerSteps": 20,
            "adetailerDenoise": 0.4,
            "adetailerInpaintMasked": True,
            "checkpoint": None,
            "unet": "flux1-dev.safetensors",
            "clip": "clip_l.safetensors",
            "clip2": "t5xx_l_encoder_fp8.safetensors",
            "vae": "ae.safetensors",
            "modelType": "flux",
            "width": 1024,
            "height": 1024,
            "batchSize": 1,
        }
        options = GeneratorOptions(**payload)
        graph = WorkflowBuilder().build(options)
        classes = {node["class_type"] for node in graph.values()}
        assert "UNETLoader" in classes
        assert "CheckpointLoaderSimple" not in classes

    def test_a_checkpoint_model_still_validates_without_a_checkpoint(self):
        options = GeneratorOptions(prompt="x", checkpoint=None)
        assert options.checkpoint is None


class TestUnetBranchSelection:
    def test_a_unet_with_its_clip_loads_through_the_unet_loader(self):
        graph = WorkflowBuilder().build(GeneratorOptions(**_flux_options()))
        classes = {node["class_type"] for node in graph.values()}
        assert "UNETLoader" in classes
        assert "CheckpointLoaderSimple" not in classes
        assert "DualCLIPLoader" in classes

    def test_a_unet_without_a_clip_is_a_named_error_not_a_null_checkpoint(self):
        """It used to fall through to the checkpoint branch.

        The result was `CheckpointLoaderSimple{ckpt_name: null}` - a graph
        ComfyUI rejects with nothing pointing at the field that was wrong.
        """
        with pytest.raises(ValidationError) as excinfo:
            WorkflowBuilder().build(
                GeneratorOptions(**_flux_options(clip=None, clip2=None))
            )
        assert excinfo.value.field == "clip"
        assert "text encoder" in str(excinfo.value)

    def test_a_flux_unet_without_its_second_clip_is_a_named_error(self):
        with pytest.raises(ValidationError) as excinfo:
            WorkflowBuilder().build(
                GeneratorOptions(**_flux_options(clip2=None))
            )
        assert excinfo.value.field == "clip2"

    def test_a_checkpoint_model_still_uses_the_checkpoint_loader(self):
        graph = WorkflowBuilder().build(
            GeneratorOptions(prompt="x", checkpoint="sd15_model.safetensors")
        )
        classes = {node["class_type"] for node in graph.values()}
        assert "CheckpointLoaderSimple" in classes
        assert "UNETLoader" not in classes

    def test_a_missing_checkpoint_name_is_an_empty_string_not_none(self):
        """ComfyUI's enum wants a string; `None` is not one."""
        graph = WorkflowBuilder().build(GeneratorOptions(prompt="x"))
        loader = next(
            node for node in graph.values()
            if node["class_type"] == "CheckpointLoaderSimple"
        )
        assert loader["inputs"]["ckpt_name"] == ""
