"""Model and provider coherence (audit-2026-10-21 §3.16-§3.21, §3.1).

Five defects, each of which made a working feature silently do nothing:

  * the IPAdapter weights were not in the reconciled directory list, so the
    provider never listed them and the picker was always empty;
  * `latent_upscale` probed for `LatentUpscale` while the builder emits
    `LatentUpscaleBy` - two different nodes - so the capability was
    reported unsupported for every provider;
  * there was no capability gate for IPAdapter or ControlNet, so the
    builder emitted nodes a provider might not have and the job failed at
    dispatch with "node type not found";
  * a deleted model, a toggled version and a reconciler status write all
    changed the answer to "is this model available?" without invalidating
    the 30 s availability cache;
  * a self-hosted vLLM provider was re-labelled `modal_llm` and silently
    routed to a Modal llama.cpp app.
"""


from core.provider_capabilities import ENHANCEMENT_NODE_CLASSES, derive_capabilities
from core.workflow_builder import GeneratorOptions, WorkflowBuilder
from services.engines.base import MODEL_DIRECTORIES
from services.engines.registry import resolve_provider_type
from services.model_reconciliation import _DIRECTORY_TO_MODEL_TYPE


class TestModelDirectories:
    def test_the_ipadapter_weights_are_reconciled(self):
        """Without this the provider never lists IPAdapter weights, so the
        picker is empty and the feature is unreachable."""
        assert "models/ipadapter" in MODEL_DIRECTORIES

    def test_the_backend_and_the_agent_agree_on_the_list(self):
        """Two hand-maintained copies of the same list. They were identical
        when the drift was found; there is nothing keeping them that way."""
        from pathlib import Path

        agent_models = (
            Path(__file__).resolve().parents[2]
            / "remote_agent"
            / "provider_core"
            / "models.py"
        )
        source = agent_models.read_text(encoding="utf-8")
        start = source.index("MODEL_DIRECTORIES = [")
        end = source.index("]", start)
        agent_list = [
            line.strip().strip(",").strip('"')
            for line in source[start:end].splitlines()[1:]
            if line.strip().startswith('"')
        ]
        assert agent_list == MODEL_DIRECTORIES

    def test_every_type_mapped_directory_is_a_real_directory(self):
        canonical = {d[len("models/"):] for d in MODEL_DIRECTORIES}
        for directory in _DIRECTORY_TO_MODEL_TYPE:
            assert directory in canonical, directory

    def test_the_directories_that_were_missing_have_a_type(self):
        """`clip_vision`, `ultralytics/seg` and `ipadapter` were absent, so
        a model discovered there was typed "Other"."""
        for directory in ("clip_vision", "ultralytics/seg", "ipadapter"):
            assert directory in _DIRECTORY_TO_MODEL_TYPE, directory


class TestCapabilityGates:
    def _capabilities(self, classes: list[str]) -> dict:
        graph = {name: {"input": {"required": {}}} for name in classes}
        return derive_capabilities(graph, provider_id="p")

    def test_latent_upscale_probes_the_node_the_builder_emits(self):
        """The builder emits `LatentUpscaleBy`. The probe looked for
        `LatentUpscale` - a different node, the one that takes an explicit
        upscale model - so the capability was False everywhere."""
        assert "LatentUpscaleBy" in ENHANCEMENT_NODE_CLASSES["latent_upscale"]
        caps = self._capabilities(["LatentUpscaleBy"])
        assert caps["nodes"]["latent_upscale"] is True

    def test_a_provider_without_latent_upscale_is_reported_as_unsupported(self):
        caps = self._capabilities(["CheckpointLoaderSimple"])
        assert caps["nodes"]["latent_upscale"] is False

    def test_there_is_an_ipadapter_capability(self):
        assert "ipadapter" in ENHANCEMENT_NODE_CLASSES
        caps = self._capabilities(["IPAdapterApply", "IPAdapterModelLoader"])
        assert caps["nodes"]["ipadapter"] is True

    def test_a_provider_without_the_ipadapter_pack_is_gated(self):
        caps = self._capabilities(["CheckpointLoaderSimple"])
        assert caps["nodes"]["ipadapter"] is False

    def test_the_builder_skips_ipadapters_the_provider_cannot_run(self):
        caps = self._capabilities(["CheckpointLoaderSimple"])
        options = GeneratorOptions(
            prompt="x",
            checkpoint="m.safetensors",
            ipAdapters=[{
                "model": "ipadapter.bin",
                "image": "ref.png",
                "clipVision": "clip_vision.safetensors",
                "weight": 0.6,
            }],
        )
        builder = WorkflowBuilder(capabilities=caps)
        graph = builder.build(options)
        classes = {node["class_type"] for node in graph.values()}
        assert "IPAdapterApply" not in classes
        assert any("IPAdapter" in w for w in builder.warnings)

    def test_the_builder_emits_ipadapters_the_provider_can_run(self):
        caps = self._capabilities(["IPAdapterApply", "IPAdapterModelLoader"])
        options = GeneratorOptions(
            prompt="x",
            checkpoint="m.safetensors",
            ipAdapters=[{
                "model": "ipadapter.bin",
                "image": "ref.png",
                "clipVision": "clip_vision.safetensors",
                "weight": 0.6,
            }],
        )
        graph = WorkflowBuilder(capabilities=caps).build(options)
        classes = {node["class_type"] for node in graph.values()}
        assert "IPAdapterApply" in classes

    def test_the_builder_skips_controlnets_the_provider_cannot_run(self):
        caps = self._capabilities(["CheckpointLoaderSimple"])
        options = GeneratorOptions(
            prompt="x",
            checkpoint="m.safetensors",
            controlnets=[{"name": "cn.pth", "image": "ref.png", "strength": 0.8}],
        )
        builder = WorkflowBuilder(capabilities=caps)
        graph = builder.build(options)
        classes = {node["class_type"] for node in graph.values()}
        assert "ControlNetApply" not in classes
        assert any("ControlNet" in w for w in builder.warnings)

    def test_an_unknown_capability_still_builds_everything(self):
        """A provider that is DOWN must not be read as a provider that cannot
        do ControlNet."""
        builder = WorkflowBuilder(capabilities=None)
        options = GeneratorOptions(
            prompt="x",
            checkpoint="m.safetensors",
            controlnets=[{"name": "cn.pth", "image": "ref.png", "strength": 0.8}],
        )
        graph = builder.build(options)
        classes = {node["class_type"] for node in graph.values()}
        assert "ControlNetApply" in classes
        assert not builder.warnings


class TestProviderRouting:
    def test_a_self_hosted_vllm_is_not_routed_to_modal(self):
        """`openai_compat` IS what a local vLLM says. The old rule re-labelled
        every one of them `modal_llm`, so the request went to a Modal
        llama.cpp app instead of the operator's own box."""
        assert resolve_provider_type("openai_compat", "selfhost-vllm") == "openai_compat"
        assert resolve_provider_type("openai_compat", "my-vllm-provider") == "openai_compat"
        assert resolve_provider_type("ollama", "local-vllm") == "ollama"

    def test_an_unknown_type_with_a_vllm_id_is_not_modal(self):
        assert resolve_provider_type("", "self-vllm") != "modal_llm"

    def test_the_legacy_mis_typed_modal_pod_still_resolves(self):
        """The rescue exists for a Modal vLLM pod whose row said
        `openai_compat` because the pod speaks the OpenAI API."""
        assert resolve_provider_type("openai_compat", "modal-vllm-legacy") == "modal_llm"

    def test_the_other_transports_are_unaffected(self):
        assert resolve_provider_type("beam_llm", "beam_llm") == "beam_llm"
        assert resolve_provider_type("remote_llm", "remote_llm") == "remote_llm"
