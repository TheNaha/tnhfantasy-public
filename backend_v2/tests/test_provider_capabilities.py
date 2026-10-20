"""The builder must not emit a node the provider does not have.

The Enhancements panel used to hardcode the provider's node vocabulary in
Python - `FreeU_V2`, `PerturbedAttentionGuidance`, `FaceDetailer`,
`UltralyticsDetectorProvider`, `UpscaleModelLoader` - and emitted those
nodes whatever the provider had installed.

So the panel offered a FreeU toggle to a provider with no FreeU node, the
graph went out with a `FreeU_V2` node in it, and the job failed at
dispatch with "node type not found" - after the user had picked the
enhancement and waited.

"Not known" and "not supported" are different answers, and the difference
matters: a provider that is down is not a provider that cannot do FreeU.
"""

from core.provider_capabilities import derive_capabilities, model_list, supports
from core.workflow_builder import GeneratorOptions, WorkflowBuilder


def _digest(**nodes):
    """A node digest with the given node classes.

    Shaped like the backend's `node_schema_digest` output, which keeps each
    node's `input` sections and, for a combination input, its option list.
    """
    graph = {}
    for class_type, options in nodes.items():
        graph[class_type] = {
            "input": {
                "required": {
                    name: [["a", "b"], {"default": "a"}]
                    for name in options
                }
            },
            "name": class_type,
            "display_name": class_type,
            "category": "test",
        }
    return graph


FULL = _digest(
    FreeU_V2={},
    PerturbedAttentionGuidance={},
    FaceDetailer={},
    UltralyticsDetectorProvider={"model_name": None},
    UpscaleModelLoader={"model_name": None},
    LatentUpscale={},
)

BARE = _digest(CheckpointLoaderSimple={"ckpt_name": None})


def _options(**overrides):
    base = {
        "prompt": "a cat",
        "negativePrompt": "",
        "steps": 20,
        "cfg": 7.0,
        "sampler": "euler",
        "scheduler": "normal",
        "width": 512,
        "height": 512,
        "batchSize": 1,
        "checkpoint": "model.safetensors",
        "modelType": "sd15",
    }
    base.update(overrides)
    return GeneratorOptions(**base)


def _class_types(workflow):
    """The builder returns the node map directly."""
    return {node["class_type"] for node in workflow.values()}


class TestDeriveCapabilities:
    def test_a_provider_with_the_nodes_supports_them(self):
        capabilities = derive_capabilities(FULL, provider_id="p1")
        assert capabilities["known"] is True
        assert capabilities["nodes"]["freeu"] is True
        assert capabilities["nodes"]["pag"] is True
        assert capabilities["nodes"]["adetailer"] is True
        assert capabilities["nodes"]["detector"] is True
        assert capabilities["nodes"]["upscale_model"] is True

    def test_a_provider_without_the_nodes_does_not(self):
        capabilities = derive_capabilities(BARE, provider_id="p1")
        assert capabilities["known"] is True
        assert capabilities["nodes"]["freeu"] is False
        assert capabilities["nodes"]["adetailer"] is False

    def test_an_unreadable_graph_is_not_known(self):
        """Not known is NOT "no".

        A provider that is down, or has never been introspected, must not be
        read as a provider that cannot do FreeU.
        """
        capabilities = derive_capabilities({}, provider_id="p1")
        assert capabilities["known"] is False
        assert capabilities["nodes"]["freeu"] is None
        assert supports(capabilities, "freeu") is None

    def test_the_model_lists_come_from_the_provider(self):
        capabilities = derive_capabilities(FULL, provider_id="p1")
        # The digest's combination input keeps its option list.
        assert capabilities["models"]["upscale_model"] == ["a", "b"]
        assert model_list(capabilities, "upscale_model") == ["a", "b"]


class TestTheBuilderGatesOnTheCapabilities:
    def test_freeu_is_not_emitted_for_a_provider_without_it(self):
        capabilities = derive_capabilities(BARE)
        builder = WorkflowBuilder(capabilities=capabilities)
        workflow = builder.build(_options(enableFreeU=True))

        assert "FreeU_V2" not in _class_types(workflow)
        assert builder.warnings, "the skip was not explained"
        assert "FreeU" in builder.warnings[0]

    def test_freeu_is_emitted_for_a_provider_with_it(self):
        capabilities = derive_capabilities(FULL)
        builder = WorkflowBuilder(capabilities=capabilities)
        workflow = builder.build(_options(enableFreeU=True))

        assert "FreeU_V2" in _class_types(workflow)
        assert builder.warnings == []

    def test_pag_is_not_emitted_for_a_provider_without_it(self):
        capabilities = derive_capabilities(BARE)
        builder = WorkflowBuilder(capabilities=capabilities)
        workflow = builder.build(_options(enablePAG=True, pagScale=3.0))

        assert "PerturbedAttentionGuidance" not in _class_types(workflow)
        assert builder.warnings

    def test_adetailer_is_not_emitted_without_the_detailer_or_the_detector(self):
        # The detector alone is not enough: the detailer needs BOTH nodes.
        only_detector = derive_capabilities(
            _digest(UltralyticsDetectorProvider={"model_name": None})
        )
        builder = WorkflowBuilder(capabilities=only_detector)
        workflow = builder.build(_options(adetailer=True))

        assert "FaceDetailer" not in _class_types(workflow)
        assert builder.warnings

    def test_an_unknown_capability_changes_nothing(self):
        """A provider that could not be introspected behaves as it always did.

        The alternative would be to disable every enhancement whenever the
        provider is down.
        """
        builder = WorkflowBuilder(capabilities=derive_capabilities({}))
        workflow = builder.build(_options(enableFreeU=True))

        assert "FreeU_V2" in _class_types(workflow)
        assert builder.warnings == []

    def test_no_capabilities_at_all_changes_nothing(self):
        builder = WorkflowBuilder()
        workflow = builder.build(_options(enableFreeU=True))

        assert "FreeU_V2" in _class_types(workflow)
        assert builder.warnings == []

    def test_the_hires_upscaler_model_is_not_emitted_without_the_loader(self):
        capabilities = derive_capabilities(BARE)
        builder = WorkflowBuilder(capabilities=capabilities)
        workflow = builder.build(
            _options(hiresFix=True, hiresUpscaler="4x.pth", hiresUpscale=2.0)
        )

        assert "UpscaleModelLoader" not in _class_types(workflow)
        assert builder.warnings


class TestTheInpaintMaskedOption:
    def test_the_backend_honours_the_option_the_panel_offers(self):
        """The panel has always offered "Inpaint Masked Only".

        The backend declared the option, the frontend sent it, and the
        builder hardcoded `noise_mask: True` - so the control did nothing
        at all.
        """
        masked = WorkflowBuilder().build(_options(adetailer=True, adetailerInpaintMasked=True))
        whole = WorkflowBuilder().build(_options(adetailer=True, adetailerInpaintMasked=False))

        def noise_mask(workflow):
            for node in workflow.values():
                if node["class_type"] == "FaceDetailer":
                    return node["inputs"]["noise_mask"]
            return None

        assert noise_mask(masked) is True
        assert noise_mask(whole) is False
