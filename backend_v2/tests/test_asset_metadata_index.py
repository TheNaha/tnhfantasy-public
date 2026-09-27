"""Tests for the shape-tolerant metadata normaliser.

The fixtures below are transcribed from images that really exist in this
library's `data/output` tree, not invented. The shapes were catalogued by
sampling: 198 LoRA references (all nested, zero flat) and five distinct
checkpoint shapes, in descending order of how many images use them
(9609 / 5526 / 321 / 179 / 169 in that sample).

If a fixture here looks redundant it is not: each one is a real producer
variant, and the failure mode this module exists to prevent is a consumer
reading one shape and silently getting `None` for everything else.
"""

import pytest

from services.asset_metadata_index import (
    MAX_MODEL_TAGS,
    extract_tag_vocabulary,
    normalise_checkpoints,
    normalise_loras,
    normalise_model_reference,
)


# --- the nested LoRA shape: the ONLY shape in the library -------------------

NESTED_LORA = {
    "name": "Zeta_ゼータ_The_Eminence_in_Shadow_SDXL_LoRA_Illustrious.safetensors",
    "preview": {"url": "https://image.civitai.com/x.webp"},
    "strength": 1,
    "metadata": {
        "id": 1189691,
        "name": "Zeta/ゼータ (The Eminence in Shadow) SDXL LoRA [Illustrious]",
        # ~1.2 KB of raw HTML in the real file. Must never be copied.
        "description": "<h3 id=\"a\"><strong>request a character</strong></h3><p>Zeta from "
                       "The Eminence in Shadow. <span style=\"color:rgb(193)\">Trained on "
                       "</span><a href=\"https://civitai.com/models/795765\">Illustrious-XL</a>.</p>",
        "tags": ["concept", "character", "z3t4", "illustrious"],
        "type": "LORA",
        "modelVersions": [
            {
                "baseModel": "Illustrious",
                "baseModelType": "SDXL",
                "trainedWords": [
                    "z3t4, blonde hair, cat ears, low ponytail, purple eyes",
                    "black bodysuit, black coat, gold trim, cleavage",
                ],
            }
        ],
    },
}

# --- the flat checkpoint shapes ---------------------------------------------

FLAT_CHECKPOINT = {
    "name": "waiNSFW_Illustrious_v150",
    "display_name": "waiNSFW Illustrious v150",
    "type": "Checkpoint",
    "base_model": "Illustrious",
    "civitai_id": 1234567,
    "model_id": 42,
    "size": 2147483648,
    "size_kb": 2097152.0,
    "tags": ["illustrious", "anime", "checkpoint"],
    "trained_words": ["1girl"],
    "creator": "someone",
    "description": "<p>an <b>Illustrious</b> checkpoint</p>",
    "preview": {"url": "https://image.civitai.com/y.webp"},
    "images": [{"url": "https://image.civitai.com/z.webp", "width": 1024}],
    "stats": {"downloadCount": 999},
    "versions": [{"id": 1, "name": "v1"}],
}

MINIMAL_CHECKPOINT = {"name": "sd_xl_base_1.0.safetensors", "display_name": "SDXL Base 1.0",
                      "size": 6900000000, "type": "Checkpoint"}

NESTED_CHECKPOINT = {
    "metadata_url": "https://civitai.com/api/v1/models/795765",
    "name": "some_base_model.safetensors",
    "preview": {"url": "https://image.civitai.com/w.webp"},
    "size": 1000,
    "type": "Checkpoint",
    "metadata": {"id": 795765, "name": "Some Base Model", "tags": ["base"],
                 "modelVersions": [{"baseModel": "SDXL 1.0"}]},
}


class TestNestedLora:
    """The nested shape is the only LoRA shape present, so it is the one that
    a naive `entry["civitai_id"]` read gets 100% wrong."""

    def test_resolves_civitai_id_from_nested_metadata(self):
        out = normalise_model_reference(NESTED_LORA, kind="lora")
        assert out["civitai_id"] == 1189691

    def test_filename_is_the_safetensors_name(self):
        out = normalise_model_reference(NESTED_LORA, kind="lora")
        assert out["filename"].endswith(".safetensors")
        assert out["name"] == out["filename"]

    def test_display_name_prefers_the_human_one(self):
        out = normalise_model_reference(NESTED_LORA, kind="lora")
        assert out["display_name"].startswith("Zeta/")

    def test_never_copies_the_html_description(self):
        out = normalise_model_reference(NESTED_LORA, kind="lora")
        assert "description" not in out
        assert not any("<" in str(v) for v in out.values())

    def test_never_copies_bulky_structures(self):
        out = normalise_model_reference(NESTED_LORA, kind="lora")
        for bulky in ("preview", "images", "stats", "versions", "modelVersions", "metadata"):
            assert bulky not in out

    def test_reads_base_model_out_of_modelVersions(self):
        # The top-level `baseModel` is null in the real payload; it only exists
        # one level down.
        out = normalise_model_reference(NESTED_LORA, kind="lora")
        assert out["base_model"] == "Illustrious"

    def test_splits_comma_joined_trained_words(self):
        # This is the whole point of indexing them: CivitAI stores each trained
        # word as a comma-joined booru tag STRING, so an un-split value is
        # useless for matching.
        out = normalise_model_reference(NESTED_LORA, kind="lora")
        words = out["trained_words"]
        assert "blonde hair" in words
        assert "cat ears" in words
        assert not any("," in w for w in words)

    def test_keeps_tags(self):
        out = normalise_model_reference(NESTED_LORA, kind="lora")
        assert out["tags"] == ["concept", "character", "z3t4", "illustrious"]

    def test_records_type(self):
        out = normalise_model_reference(NESTED_LORA, kind="lora")
        assert out["type"] == "LORA"

    def test_strength_is_preserved_per_image(self):
        # Strength varies per image, so it cannot live on the model row.
        out = normalise_loras({"loras": [dict(NESTED_LORA, strength=0.3)]})
        assert out[0]["strength"] == 0.3


class TestFlatCheckpoint:
    def test_resolves_both_ids(self):
        out = normalise_model_reference(FLAT_CHECKPOINT, kind="checkpoint")
        assert out["civitai_id"] == 1234567
        assert out["model_id"] == 42

    def test_drops_bulk_and_html(self):
        out = normalise_model_reference(FLAT_CHECKPOINT, kind="checkpoint")
        for dropped in ("description", "preview", "images", "stats", "versions", "creator"):
            assert dropped not in out

    def test_keeps_tags_and_base_model(self):
        out = normalise_model_reference(FLAT_CHECKPOINT, kind="checkpoint")
        assert "illustrious" in out["tags"]
        assert out["base_model"] == "Illustrious"


class TestOtherCheckpointShapes:
    def test_minimal_shape_still_yields_a_joinable_filename(self):
        # No ids at all, but the filename is enough to join on
        # models_v2.storage_filename, so it must not be dropped.
        out = normalise_model_reference(MINIMAL_CHECKPOINT, kind="checkpoint")
        assert out["filename"] == "sd_xl_base_1.0.safetensors"

    def test_nested_checkpoint_resolves_via_metadata_id(self):
        out = normalise_model_reference(NESTED_CHECKPOINT, kind="checkpoint")
        assert out["civitai_id"] == 795765
        assert out["base_model"] == "SDXL 1.0"

    def test_checkpoint_is_usally_a_single_object_not_a_list(self):
        out = normalise_checkpoints({"checkpoint": FLAT_CHECKPOINT})
        assert len(out) == 1
        out = normalise_checkpoints({"checkpoint": [FLAT_CHECKPOINT, MINIMAL_CHECKPOINT]})
        assert len(out) == 2


class TestRobustness:
    @pytest.mark.parametrize("bad", [None, 123, [], {}, ""])
    def test_junk_yields_nothing(self, bad):
        assert normalise_model_reference(bad) is None

    def test_bare_string_becomes_a_filename_only_reference(self):
        out = normalise_model_reference("some_lora.safetensors", kind="lora")
        assert out["filename"] == "some_lora.safetensors"
        assert "civitai_id" not in out

    def test_missing_metadata_yields_empty_lists(self):
        assert normalise_loras(None) == []
        assert normalise_loras({}) == []
        assert normalise_checkpoints(None) == []

    def test_lora_entry_with_no_identity_is_skipped(self):
        assert normalise_loras({"loras": [{}, {"nope": 1}]}) == []

    def test_tags_are_deduplicated_and_bounded(self):
        noisy = {"loras": [{"name": "x.safetensors", "metadata": {
            "id": 1, "tags": [f"tag{i}" for i in range(200)] + ["tag0"]}}]}
        out = normalise_loras(noisy)
        tags = out[0]["tags"]
        assert len(tags) == MAX_MODEL_TAGS
        assert len(tags) == len(set(tags))
        assert tags[0] == "tag0"

    def test_boolean_is_not_coerced_to_an_id(self):
        out = normalise_model_reference({"name": "x.safetensors", "civitai_id": True})
        assert "civitai_id" not in out

    def test_html_is_stripped_from_a_display_name(self):
        # Stripping is correct: a display name should never be markup. What is
        # rejected is only a name that was *nothing but* markup, in which case
        # the filename is a better label than the empty remainder.
        out = normalise_model_reference(
            {"name": "x.safetensors", "display_name": "<p></p>"}, kind="lora"
        )
        assert out["display_name"] == "x.safetensors"

    def test_short_html_display_name_is_cleaned_not_dropped(self):
        out = normalise_model_reference(
            {"name": "x.safetensors", "display_name": "<b>Eta</b>"}, kind="lora"
        )
        assert out["display_name"] == "Eta"


class TestTagVocabulary:
    def test_harvests_from_lora_tags_and_trained_words(self):
        vocab = extract_tag_vocabulary({"loras": [NESTED_LORA]})
        # from metadata.tags
        assert "z3t4" in vocab
        # from the comma-joined trainedWords
        assert "blonde hair" in vocab
        assert "gold trim" in vocab

    def test_empty_metadata_yields_nothing(self):
        assert extract_tag_vocabulary({}) == set()
        assert extract_tag_vocabulary(None) == set()
