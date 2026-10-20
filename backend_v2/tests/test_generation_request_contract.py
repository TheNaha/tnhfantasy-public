"""The generation request has two kinds, and both get the same treatment.

`POST /api/generate` accepts either a parameter dict (the backend compiles
the ComfyUI graph) or a compiled graph (the client compiled it). The kind
used to be inferred from the shape of the body, which was wrong for a
hand-written graph with a node keyed `prompt` or `mode`, and it is now
explicit.

The two kinds used to get DIFFERENT treatment, and the differences were
all things the graph path was missing:

  * prompt shortcuts were expanded only for the guided path, so a graph
    reached the provider with its shortcuts unexpanded;
  * embedding references were checked only for the guided path, so a graph
    naming an embedding that does not exist reached the provider and
    failed there;
  * the graph path sent `metadata: {}`, so the gallery had no prompt, no
    seed, no dimensions and no model name for it.
"""

import pytest

from core.exceptions import ValidationError


def _graph(**overrides):
    """A minimal compiled ComfyUI graph, in the API node-map form.

    It has no checkpoint loader on purpose: a loader makes the request
    require a model, and the request then fails validation because no
    provider in the test environment has one installed. The loader-derived
    fields are covered by the unit tests of `derive_metadata_from_workflow`
    instead.
    """
    nodes = {
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "a cat"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "blurry"},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 768, "height": 1024, "batch_size": 2},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 12345,
                "steps": 28,
                "cfg": 6.5,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
    }
    nodes.update(overrides)
    return nodes


class TestTheRequestKind:
    def test_an_explicit_graph_kind_is_honoured(self, client):
        response = client.post(
            "/api/generate", json={"kind": "graph", "workflow": _graph()}
        )
        assert response.status_code == 200, response.text

    def test_a_graph_with_a_node_keyed_prompt_is_not_read_as_options(self, client):
        """The inference this replaces.

        The old rule was "an object with a `prompt` or a `mode` key is
        options". A hand-written ComfyUI graph whose nodes are keyed
        `prompt` or `mode` - which is exactly what the Raw JSON editor
        invites - was routed to `options` and rejected by the option
        schema.
        """
        graph = {
            "nodes": {
                "prompt": {"class_type": "KSampler", "inputs": {"steps": 20}},
            }
        }
        response = client.post("/api/generate", json={"kind": "graph", "workflow": graph})
        assert response.status_code == 200, response.text

    def test_an_explicit_guided_kind_compiles_the_options(self, client):
        response = client.post(
            "/api/generate",
            json={"kind": "guided", "options": {"prompt": "a cat", "width": 512, "height": 512}},
        )
        assert response.status_code == 200, response.text

    def test_omitting_the_kind_still_works(self, client, sample_workflow):
        """Existing clients do not send it."""
        response = client.post("/api/generate", json={"workflow": sample_workflow})
        assert response.status_code == 200, response.text

    def test_a_guided_request_without_options_is_rejected(self, client):
        response = client.post("/api/generate", json={"kind": "guided"})
        assert response.status_code == 400
        assert response.json()["field"] == "options"

    def test_a_graph_request_without_a_workflow_is_rejected(self, client):
        response = client.post("/api/generate", json={"kind": "graph"})
        assert response.status_code == 400
        assert response.json()["field"] == "workflow"

    def test_neither_kind_nor_a_body_is_rejected(self, client):
        response = client.post("/api/generate", json={})
        assert response.status_code == 400
        assert response.json()["field"] == "workflow"


class TestTheGraphGetsTheSamePromptTreatment:
    def test_the_shortcuts_are_expanded(self, client, monkeypatch):
        monkeypatch.setattr(
            "core.workflow_postprocess.expand_prompt_shortcuts",
            lambda text: text.replace("cat", "a majestic cat"),
        )

        graph = _graph()
        graph["2"]["inputs"]["text"] = "cat"

        response = client.post("/api/generate", json={"kind": "graph", "workflow": graph})
        assert response.status_code == 200, response.text
        # The job runs the graph that was sent, with the expansion applied.
        # The graph is expanded server-side, so the job's copy is what to
        # look at - the client's object went out over the wire unchanged.
        job_graph = response.json()["workflow"]
        assert "a majestic cat" in job_graph["2"]["inputs"]["text"]

    def test_a_missing_embedding_is_rejected_before_the_provider_sees_it(self, client):
        """A missing embedding is a request that cannot succeed.

        The guided path has always raised here. The graph path did not, so
        the failure surfaced at the provider, long after the request that
        caused it, with nothing in the request to explain it.
        """
        graph = _graph()
        graph["2"]["inputs"]["text"] = "embedding:definitely_not_installed"

        response = client.post("/api/generate", json={"kind": "graph", "workflow": graph})
        assert response.status_code == 400
        assert "Embedding file" in response.text


class TestTheGraphGetsMetadata:
    def test_the_gallery_metadata_is_derived_from_the_graph(self, client):
        response = client.post(
            "/api/generate", json={"kind": "graph", "workflow": _graph()}
        )
        assert response.status_code == 200, response.text
        metadata = response.json()["metadata"]

        assert metadata["prompt"] == "a cat"
        assert metadata["negativePrompt"] == "blurry"
        assert metadata["seed"] == 12345
        assert metadata["steps"] == 28
        assert metadata["cfg"] == 6.5
        assert metadata["sampler"] == "dpmpp_2m"
        assert metadata["scheduler"] == "karras"
        assert metadata["width"] == 768
        assert metadata["height"] == 1024
        assert metadata["batchSize"] == 2

    def test_the_client_metadata_wins_where_it_sent_one(self, client):
        response = client.post(
            "/api/generate",
            json={
                "kind": "graph",
                "workflow": _graph(),
                "metadata": {"prompt": "the client's prompt", "custom": "kept"},
            },
        )
        assert response.status_code == 200, response.text
        metadata = response.json()["metadata"]

        assert metadata["prompt"] == "the client's prompt"
        assert metadata["custom"] == "kept"
        # ...and the derived fields still fill in the rest.
        assert metadata["seed"] == 12345

    def test_a_graph_with_no_sampler_gets_no_seed(self, client):
        """Nothing is invented.

        The prompt is read THROUGH the sampler - the sampler's `positive`
        input names the text node. A graph with no sampler has no such
        link, so there is no prompt to read and no seed either. The
        frontend's own graph reader works the same way.
        """
        graph = {
            "nodes": {
                "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat"}},
            }
        }
        response = client.post("/api/generate", json={"kind": "graph", "workflow": graph})
        assert response.status_code == 200, response.text
        metadata = response.json()["metadata"]

        assert "seed" not in metadata
        assert "prompt" not in metadata

    def test_the_enhancement_flags_come_from_the_nodes_that_are_there(self, client):
        graph = _graph(
            **{
                "6": {"class_type": "FreeU_V2", "inputs": {}},
                "7": {"class_type": "LatentUpscale", "inputs": {}},
            }
        )
        response = client.post("/api/generate", json={"kind": "graph", "workflow": graph})
        assert response.status_code == 200, response.text
        metadata = response.json()["metadata"]

        assert metadata["enableFreeU"] is True
        assert metadata["enableLatentUpscale"] is True
        assert metadata["hiresFix"] is True
        # The ones that are not in the graph are absent, not False - a graph
        # without a FreeU node has no FreeU, and saying `False` would be a
        # claim about a graph we did not read.
        assert "enablePAG" not in metadata
        assert "adetailer" not in metadata


class TestThePreferredProvider:
    def test_the_request_can_pin_the_provider(self, client, tts_capable):
        response = client.post(
            "/api/generate",
            json={
                "kind": "graph",
                "workflow": _graph(),
                "preferred_provider_id": tts_capable.id,
            },
        )
        assert response.status_code == 200, response.text
        # The provider is pinned in the job's metadata, which is where the
        # load balancer reads it from - the `provider_id` column is filled
        # in when the worker is actually dispatched.
        assert response.json()["metadata"]["preferred_provider_id"] == tts_capable.id


class TestTheDerivedMetadataItself:
    """The derivation, on its own, so the model fields can be covered.

    The route tests above use a graph with no checkpoint loader, because a
    loader makes the request require a model and no provider in the test
    environment has one installed. The loader-derived fields are the
    backend's own business and are checked here.
    """

    def test_the_model_comes_from_the_loader(self):
        from core.workflow_metadata import derive_metadata_from_workflow

        metadata = derive_metadata_from_workflow(
            {
                "nodes": {
                    "1": {
                        "class_type": "CheckpointLoaderSimple",
                        "inputs": {"ckpt_name": "sd_xl_base.safetensors"},
                    },
                    "2": {"class_type": "VAELoader", "inputs": {"vae_name": "sdxl_vae.safetensors"}},
                    "3": {
                        "class_type": "LoraLoader",
                        "inputs": {"lora_name": "detail.safetensors", "strength_model": 0.7},
                    },
                }
            }
        )
        assert metadata["checkpoint"] == "sd_xl_base.safetensors"
        assert metadata["vae"] == "sdxl_vae.safetensors"
        assert metadata["loras"] == [{"name": "detail.safetensors", "strength": 0.7}]

    def test_a_unet_graph_reports_the_unet(self):
        from core.workflow_metadata import derive_metadata_from_workflow

        metadata = derive_metadata_from_workflow(
            {
                "nodes": {
                    "1": {
                        "class_type": "UNETLoader",
                        "inputs": {"unet_name": "flux1-dev.safetensors"},
                    },
                }
            }
        )
        assert metadata["checkpoint"] == "flux1-dev.safetensors"
        assert metadata["unet"] == "flux1-dev.safetensors"

    def test_a_dual_clip_loader_reports_both_clips(self):
        from core.workflow_metadata import derive_metadata_from_workflow

        metadata = derive_metadata_from_workflow(
            {
                "nodes": {
                    "1": {
                        "class_type": "DualCLIPLoader",
                        "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl.safetensors"},
                    },
                }
            }
        )
        assert metadata["clip"] == "clip_l.safetensors"
        assert metadata["clip2"] == "t5xxl.safetensors"

    def test_the_adetailer_model_comes_from_the_detector(self):
        from core.workflow_metadata import derive_metadata_from_workflow

        metadata = derive_metadata_from_workflow(
            {
                "nodes": {
                    "1": {"class_type": "FaceDetailer", "inputs": {}},
                    "2": {
                        "class_type": "UltralyticsDetectorProvider",
                        "inputs": {"model_name": "detection/bbox/face_yolov8n.pt"},
                    },
                }
            }
        )
        assert metadata["adetailer"] is True
        assert metadata["adetailerModel"] == "face_yolov8n.pt"
