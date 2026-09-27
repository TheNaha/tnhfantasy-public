# Tests for services/external_model_service.py HuggingFace normalisation.
#
# The HF normalisers used to build their payload with no `tags` key and a
# hardcoded `"type": "Checkpoint"`, while the project's own parser
# (infrastructure/parsers/hf_parser.py) reads exactly those tags to infer the
# type. So an HF LoRA was filed as a checkpoint, was unfindable by type, and
# lost the only metadata that says what it is.

import pytest

from services.external_model_service import ExternalModelService


# A realistic HuggingFace payload for a character LoRA: the format tags
# ("diffusers"/"safetensors") are what the search endpoint adds to every result,
# and "lora" is the only field saying what the repo is.
HF_LORA_PAYLOAD = {
    "id": "someuser/boob-tent-lora",
    "author": "someuser",
    "sha": "abc123",
    "description": "A LoRA for the character Boob Tent.",
    "downloads": 4321,
    "likes": 57,
    "pipeline_tag": "text-to-image",
    "tags": ["diffusers", "safetensors", "lora", "anime", "character", "illustrious", "pytorch"],
}


@pytest.fixture(name="service")
def service_fixture():
    return ExternalModelService()


# ── _normalize_huggingface_model_detail ─────────────────────────────────────

def test_detail_normalises_a_lora_as_a_lora_with_tags_intact(service):
    """The owner's actual complaint, at the parse-a-URL entry point."""
    result = service._normalize_huggingface_model_detail(
        "someuser/boob-tent-lora", HF_LORA_PAYLOAD
    )

    assert result["type"] == "LORA"
    assert "lora" in result["tags"]
    # The format tags are noise in a tag dropdown, but the descriptive ones are
    # the only record of what the model is for.
    assert "anime" in result["tags"]
    assert "character" in result["tags"]
    assert "illustrious" in result["tags"]
    assert "diffusers" not in result["tags"]
    assert "safetensors" not in result["tags"]
    assert "pytorch" not in result["tags"]
    # A LoRA directory is derived from the type, so this is what routes it to
    # models/loras instead of models/checkpoints.
    assert result["source"] == "huggingface"


def test_detail_no_longer_hardcodes_checkpoint_type(service):
    payload = dict(HF_LORA_PAYLOAD, tags=["diffusers", "safetensors", "controlnet", "pytorch"])
    assert service._normalize_huggingface_model_detail("u/c", payload)["type"] == "Controlnet"


def test_detail_types_by_tag_for_the_other_discovery_relevant_kinds(service):
    cases = {
        "vae": "VAE",
        "textual-inversion": "TextualInversion",
        "pose": "Poses",
        "upscaler": "Upscaler",
    }
    for tag, expected in cases.items():
        payload = dict(HF_LORA_PAYLOAD, tags=["diffusers", "safetensors", tag, "pytorch"])
        assert service._normalize_huggingface_model_detail("u/c", payload)["type"] == expected


def test_detail_defaults_to_checkpoint_when_tags_say_nothing_useful(service):
    """Unknown repos must still land somewhere selectable, not vanish."""
    payload = {"id": "u/c", "tags": ["diffusers", "safetensors", "pytorch"]}
    assert service._normalize_huggingface_model_detail("u/c", payload)["type"] == "Checkpoint"


def test_detail_carries_base_model_not_the_hardcoded_unknown(service):
    """`baseModel` was the literal "Unknown", and base model is a picker filter."""
    payload = dict(HF_LORA_PAYLOAD, tags=["diffusers", "safetensors", "lora", "pony", "pytorch"])
    result = service._normalize_huggingface_model_detail("someuser/boob-tent-lora", payload)
    assert result["modelVersions"][0]["baseModel"] == "Pony"


def test_detail_survives_a_payload_with_no_tags_key(service):
    result = service._normalize_huggingface_model_detail("u/c", {"id": "u/c"})
    assert result["tags"] == []
    assert result["type"] == "Checkpoint"
    assert result["description"] == ""


def test_detail_tolerates_a_non_list_tags_value(service):
    result = service._normalize_huggingface_model_detail("u/c", {"id": "u/c", "tags": "lora"})
    assert result["tags"] == []


# ── _normalize_huggingface_model (search results) ───────────────────────────

def test_search_normalises_a_lora_as_a_lora_with_tags_intact(service):
    result = service._normalize_huggingface_model(HF_LORA_PAYLOAD)

    assert result["type"] == "LORA"
    assert "lora" in result["tags"]
    assert "anime" in result["tags"]
    assert "illustrious" in result["tags"]
    assert "diffusers" not in result["tags"]


def test_search_normaliser_keeps_the_description_it_was_dropping(service):
    """The search-item normaliser had no `description` key at all."""
    result = service._normalize_huggingface_model(HF_LORA_PAYLOAD)
    assert result["description"] == "A LoRA for the character Boob Tent."


def test_search_normaliser_tags_are_deduped_and_trimmed(service):
    payload = {"id": "u/c", "tags": ["lora", "  anime  ", "lora", "", 7, "anime"]}
    assert service._normalize_huggingface_model(payload)["tags"] == ["lora", "anime"]


def test_search_normaliser_survives_a_payload_with_no_tags_key(service):
    result = service._normalize_huggingface_model({"id": "u/c"})
    assert result["tags"] == []
    assert result["type"] == "Checkpoint"
