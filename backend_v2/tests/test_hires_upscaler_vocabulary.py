"""One vocabulary for the hires upscaler.

There were three, and none of them matched each other:

  * the frontend offers `"Latent"` and the model basenames;
  * the backend's `GeneratorOptions.hiresUpscaler` is `"Latent"`,
    `"Pixel"` or a model name;
  * the scene spec's `hires_fix.upscaler` is `"latent"`, `"bilinear"` or
    `"nearest-exact"`.

The scene's was passed into the generator's untranslated, and the builder
branches on `"Latent"` and `"Pixel"` and treats everything else as a MODEL
NAME. So a scene with a hires fix asked the provider for a model called
"latent" - and the job failed on a file nobody had, for every one of the
scene's three values.
"""

from core.scene_graph import (
    SCENE_UPSCALER_TO_GENERATOR,
    SceneGraphSpec,
    hires_upscaler_for_generator,
)
from core.workflow_builder import WorkflowBuilder


def _spec_with_upscaler(upscaler: str) -> SceneGraphSpec:
    spec = SceneGraphSpec(prompt="a cat")
    spec.hires_fix.enabled = True
    spec.hires_fix.upscaler = upscaler
    return spec


class TestTheTranslation:
    def test_the_scene_values_map_onto_the_generators(self):
        assert hires_upscaler_for_generator("latent") == "Latent"
        assert hires_upscaler_for_generator("bilinear") == "Latent"
        assert hires_upscaler_for_generator("nearest-exact") == "Pixel"

    def test_a_model_name_passes_through(self):
        assert hires_upscaler_for_generator("4x-UltraSharp.pth") == "4x-UltraSharp.pth"

    def test_nothing_maps_onto_the_latent_upscaler(self):
        assert hires_upscaler_for_generator(None) == "Latent"
        assert hires_upscaler_for_generator("") == "Latent"

    def test_every_scene_value_is_mapped(self):
        from core.workflow_limits import SCENE_HIRES_UPSCALERS

        for value in SCENE_HIRES_UPSCALERS:
            assert value in SCENE_UPSCALER_TO_GENERATOR, (
                f"the scene's upscaler {value!r} has no translation, so it "
                f"would be read as a model name"
            )


class TestTheScenePath:
    def test_a_latent_scene_upscaler_builds_a_latent_node(self):
        from core.scene_graph import scene_spec_to_options

        spec = _spec_with_upscaler("latent")
        options = scene_spec_to_options(spec, checkpoint="model.safetensors")

        assert options.hiresUpscaler == "Latent"

    def test_a_nearest_exact_scene_upscaler_builds_a_pixel_node(self):
        from core.scene_graph import scene_spec_to_options

        spec = _spec_with_upscaler("nearest-exact")
        options = scene_spec_to_options(spec, checkpoint="model.safetensors")

        assert options.hiresUpscaler == "Pixel"

    def test_the_scene_path_never_asks_for_a_model_named_latent(self):
        """The failure this fixes.

        The builder's model branch emits an `UpscaleModelLoader` with the
        upscaler as the model name - so a scene upscaler of "latent" asked
        the provider for a model called "latent".
        """
        from core.scene_graph import scene_spec_to_options

        spec = _spec_with_upscaler("latent")
        options = scene_spec_to_options(spec, checkpoint="model.safetensors")

        workflow = WorkflowBuilder().build(options)
        class_types = {node["class_type"] for node in workflow.values()}

        assert "UpscaleModelLoader" not in class_types
        assert "LatentUpscaleBy" in class_types
