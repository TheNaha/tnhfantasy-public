"""The scene-graph spec — what the Illustrator may author about an image.

The Illustrator used to produce prompt TEXT, which was fed into a fixed
workflow: it could say what the scene looked like and nothing else. The
sampler, the resolution, the steps, the LoRA and the hires pass were all
fixed.

It may now author those as a SPEC. The spec is a closed vocabulary, not a
ComfyUI graph, and the backend renders it. These tests pin the two things
that make that safe:

* the numbers are bounded BEFORE the job is created, because ComfyUI's own
  validation happens at dispatch — after the job has been billed; and
* a model name that is not installed is dropped rather than passed through,
  for the same reason.
"""

from __future__ import annotations


from core.scene_graph import (
    SceneGraphSpec,
    apply_scene_spec_limits,
    parse_scene_spec,
    scene_spec_cost,
    scene_spec_to_options,
    validate_scene_spec,
)
from core.workflow_limits import (
    MAX_SCENE_BATCH,
    MAX_SCENE_PIXELS,
    MAX_SCENE_STEPS,
)


class TestSpecParsing:
    def test_plain_json_parses(self):
        spec = parse_scene_spec('{"prompt": "a courier", "sampler": {"steps": 30}}')
        assert spec is not None
        assert spec.prompt == "a courier"
        assert spec.sampler.steps == 30

    def test_a_fenced_block_parses(self):
        raw = '```json\n{"prompt": "a courier", "sampler": {"steps": 30}}\n```'
        spec = parse_scene_spec(raw)
        assert spec is not None
        assert spec.sampler.steps == 30

    def test_prose_is_not_a_spec(self):
        assert parse_scene_spec("A lone courier on a burning bridge.") is None

    def test_empty_is_not_a_spec(self):
        assert parse_scene_spec("") is None
        assert parse_scene_spec("   ") is None

    def test_a_partial_spec_is_usable(self):
        """Every field has a default, so a partial answer is a usable answer."""
        spec = parse_scene_spec('{"prompt": "a courier"}')
        assert spec is not None
        assert spec.composition.width == 1024
        assert spec.sampler.steps == 20


class TestLimits:
    def test_an_absurd_resolution_is_clamped(self):
        spec = SceneGraphSpec.model_validate({
            "prompt": "x",
            "composition": {"width": 16384, "height": 16384},
        })
        issues = validate_scene_spec(spec)
        assert any(i.field == "composition.width" for i in issues)

        limited = apply_scene_spec_limits(spec)
        assert limited.composition.width <= 2048
        assert limited.composition.height <= 2048

    def test_an_absurd_step_count_is_clamped(self):
        spec = SceneGraphSpec.model_validate({
            "prompt": "x",
            "sampler": {"steps": 10000},
        })
        assert any(i.field == "sampler.steps" for i in validate_scene_spec(spec))
        assert apply_scene_spec_limits(spec).sampler.steps == MAX_SCENE_STEPS

    def test_the_pixel_budget_is_respected(self):
        spec = SceneGraphSpec.model_validate({
            "prompt": "x",
            "composition": {"width": 2048, "height": 2048, "batch_size": 8},
        })
        limited = apply_scene_spec_limits(spec)
        assert limited.composition.width * limited.composition.height * limited.composition.batch_size <= MAX_SCENE_PIXELS
        assert limited.composition.batch_size <= MAX_SCENE_BATCH

    def test_an_unknown_sampler_is_dropped_not_passed_through(self):
        """ComfyUI rejects the whole job for an unknown sampler name.

        That rejection happens at dispatch, which is after the job was
        billed, so the name is dropped here instead.
        """
        spec = SceneGraphSpec.model_validate({
            "prompt": "x",
            "sampler": {"name": "not_a_sampler", "scheduler": "not_a_scheduler"},
        })
        issues = validate_scene_spec(spec)
        assert any(i.field == "sampler.name" for i in issues)
        assert any(i.field == "sampler.scheduler" for i in issues)

        limited = apply_scene_spec_limits(spec)
        assert limited.sampler.name == "euler"
        assert limited.sampler.scheduler == "normal"

    def test_a_dimension_is_rounded_to_a_multiple_of_eight(self):
        """ComfyUI truncates a dimension that is not a multiple of 8."""
        spec = SceneGraphSpec.model_validate({
            "prompt": "x",
            "composition": {"width": 833, "height": 1217},
        })
        limited = apply_scene_spec_limits(spec)
        assert limited.composition.width % 8 == 0
        assert limited.composition.height % 8 == 0

    def test_the_batch_is_capped(self):
        spec = SceneGraphSpec.model_validate({
            "prompt": "x",
            "composition": {"batch_size": 64},
        })
        assert apply_scene_spec_limits(spec).composition.batch_size <= MAX_SCENE_BATCH


class TestRendering:
    def test_the_spec_becomes_generator_options(self):
        spec = SceneGraphSpec.model_validate({
            "prompt": "a courier",
            "negative_prompt": "blurry",
            "composition": {"width": 832, "height": 1216},
            "sampler": {"name": "dpmpp_2m", "scheduler": "karras", "steps": 28, "cfg": 6.5, "seed": 42},
        })
        options = scene_spec_to_options(spec, checkpoint="model.safetensors")
        assert options.prompt == "a courier"
        assert options.negativePrompt == "blurry"
        assert options.width == 832
        assert options.height == 1216
        assert options.sampler == "dpmpp_2m"
        assert options.scheduler == "karras"
        assert options.steps == 28
        assert options.cfg == 6.5
        assert options.seed == 42
        assert options.checkpoint == "model.safetensors"

    def test_the_cost_grows_with_steps_and_pixels(self):
        small = SceneGraphSpec.model_validate({
            "prompt": "x",
            "composition": {"width": 512, "height": 512},
            "sampler": {"steps": 10},
        })
        big = SceneGraphSpec.model_validate({
            "prompt": "x",
            "composition": {"width": 1024, "height": 1024},
            "sampler": {"steps": 40},
        })
        assert scene_spec_cost(big) > scene_spec_cost(small)


class TestWorkflow:
    def test_the_rendered_workflow_is_the_stock_graph(self):
        """The spec changes the VALUES, not the node structure.

        A raw LLM-authored graph would need a node allow-list and a cost
        guard that do not exist. The spec is rendered by the same builder
        the stock image job uses, so the gallery metadata and the "reuse
        parameters" mapping keep working.
        """
        from core.workflow_builder import build_scene_job_workflow

        spec = SceneGraphSpec.model_validate({
            "prompt": "a courier",
            "composition": {"width": 832, "height": 1216},
            "sampler": {"name": "dpmpp_2m", "steps": 28, "seed": 7},
        })
        workflow, metadata = build_scene_job_workflow(
            spec,
            checkpoint="model.safetensors",
            source="scene_illustrate",
            chat_id="chat-1",
        )

        class_types = {node["class_type"] for node in workflow.values()}
        assert "CheckpointLoaderSimple" in class_types
        assert "KSampler" in class_types
        assert "SaveImage" in class_types

        # And the metadata the gallery reads is populated.
        assert metadata["prompt"] == "a courier"
        assert metadata["seed"] == 7
        assert metadata["steps"] == 28
        assert metadata["width"] == 832
        assert metadata["height"] == 1216
        assert metadata["checkpoint"] == "model.safetensors"
        assert metadata["scene_graph"] is True


class TestFallback:
    async def test_an_unparsable_answer_falls_back_to_the_prompt_path(
        self, session, monkeypatch
    ):
        """A model that answers with prose must still produce a picture.

        The difference between the two paths is whether the image is
        node-customised, not whether there is an image at all.
        """
        from services import world_integration_service as wIS

        called = {}

        async def _fake_scene_prompt(job_data):
            called["prompt"] = True

        monkeypatch.setattr(wIS, "_handle_scene_prompt", _fake_scene_prompt)

        await wIS._handle_scene_graph({
            "id": "job-1",
            "metadata": {"chat_id": "chat-1", "character_id": "char-1"},
            "outputs": [{"role": "assistant", "content": "A lone courier on a bridge."}],
        })

        assert called.get("prompt") is True, (
            "an unparsable scene-graph answer did not fall back to the text path"
        )
