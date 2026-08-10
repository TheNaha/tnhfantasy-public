"""Tests for DirectUrlProviderClient model listing / validation parity."""

import pytest

from image_worker.engines.direct_url.client import DirectUrlProviderClient

SAMPLE_OBJECT_INFO = {
    "CheckpointLoaderSimple": {
        "input": {
            "required": [["ckpt_name", [["model_a.safetensors", "model_b.safetensors"]]]],
            "optional": [],
        },
    },
    "LoraLoader": {
        "input": {
            "required": [["model_name", [["lora_x.safetensors"]]]],
            "optional": [],
        },
    },
    "VAELoader": {
        "input": {
            "required": [["vae_name", [["vae_y.safetensors"]]]],
            "optional": [],
        },
    },
    "KSampler": {
        "input": {
            "required": [["seed", ["INT", {}]]],
            "optional": [],
        },
    },
}


@pytest.mark.asyncio
async def test_iter_object_info_model_paths_all():
    client = DirectUrlProviderClient(runtime_config={})
    try:
        paths = client._iter_object_info_model_paths(SAMPLE_OBJECT_INFO)
        assert paths == [
            "checkpoints/model_a.safetensors",
            "checkpoints/model_b.safetensors",
            "loras/lora_x.safetensors",
            "vae/vae_y.safetensors",
        ]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_iter_object_info_model_paths_filtered():
    client = DirectUrlProviderClient(runtime_config={})
    try:
        paths = client._iter_object_info_model_paths(SAMPLE_OBJECT_INFO, directory="checkpoints")
        assert paths == [
            "checkpoints/model_a.safetensors",
            "checkpoints/model_b.safetensors",
        ]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_iter_object_info_ignores_non_model_inputs():
    client = DirectUrlProviderClient(runtime_config={})
    try:
        paths = client._iter_object_info_model_paths(SAMPLE_OBJECT_INFO, directory="vae")
        assert paths == ["vae/vae_y.safetensors"]
    finally:
        await client.close()
