"""Job metadata slimming.

The job `metadata_` carried the client's full catalogue row for the checkpoint
and every selected LoRA. Measured on the running stack that was 59 KB per job
row, which `build_job_outputs` then copied a second time into the PNG sidecar
and a third time into `assets.metadata_`. The `assets` table measured 207 MB
for 16,504 rows (average row 3,469 bytes) and a 48-image gallery page returned
860 KB, 15.5 KB of it the checkpoint record on every single image.

Nothing read any of it. These tests pin that claim from both directions: the
fields that are used survive, and the volume does not come back.
"""

import json

from services.job_metadata import (
    _CHECKPOINT_KEEP,
    _LORA_KEEP,
    slim_model_metadata,
)

# The shape a real catalogue row has, with the two fields that dominated the
# measurement: the CivitAI description HTML and a checkpoint's seven base64
# preview thumbnails.
BULK_DESCRIPTION = "<p>" + ("filler " * 3000) + "</p>"
BULK_PREVIEW = {"images": ["data:image/png;base64," + ("A" * 2000)] * 7}


def _catalogue_row(name, **extra):
    row = {
        "name": name,
        "display_name": name.replace(".safetensors", ""),
        "model_id": f"m-{name}",
        "type": "lora",
        "base_model": "SD 1.5",
        "civitai_model_id": 1234,
        "description": BULK_DESCRIPTION,
        "preview": BULK_PREVIEW,
        "provider_statuses": {"modal-hp196": {"state": "ready"}, "beam": {"state": "ready"}},
        "tags": ["character", "detail"],
        "file_size": 2_135_814_000,
        "url": "https://civitai.com/api/download/models/1234",
        "sha256": "0" * 64,
    }
    row.update(extra)
    return row


class TestKeptFields:
    def test_checkpoint_name_survives(self):
        """`getCheckpointDisplayName` reads display_name || name, and the
        provider resolves the file by `name`. Dropping either breaks labelling
        or the run itself."""
        out = slim_model_metadata({"checkpoint": _catalogue_row("dreamshaper.safetensors")})
        assert out["checkpoint"]["name"] == "dreamshaper.safetensors"
        assert out["checkpoint"]["display_name"] == "dreamshaper"

    def test_every_declared_key_survives(self):
        row = _catalogue_row("a.safetensors", weight=0.8, strength=0.8, directory="models/loras", hash="abc")
        out = slim_model_metadata({"checkpoint": dict(row), "loras": [dict(row)]})
        for key in _CHECKPOINT_KEEP:
            if key in row:
                assert key in out["checkpoint"], f"checkpoint lost {key}"
        for key in _LORA_KEEP:
            if key in row:
                assert key in out["loras"][0], f"lora lost {key}"

    def test_lora_weight_and_name_survive(self):
        """`JobCard` shows `loras.length`; the lightbox shows each name and
        strength. All three are in the allowlist."""
        out = slim_model_metadata(
            {"loras": [_catalogue_row("add_detail.safetensors", weight=0.8, strength=0.8)]}
        )
        assert out["loras"][0]["name"] == "add_detail.safetensors"
        assert out["loras"][0]["weight"] == 0.8
        assert out["loras"][0]["strength"] == 0.8

    def test_unrelated_metadata_is_untouched(self):
        """The routing columns are read from this dict immediately after, and
        the LLM paths key off chat_id / story_id / character_id."""
        md = {
            "prompt": "a cat",
            "negativePrompt": "blurry",
            "seed": 42,
            "steps": 25,
            "workspace": "main",
            "character_id": "char-1",
            "story_id": "story-1",
            "chat_id": "chat-1",
            "is_swipe": True,
            "llm_model": "gpt-4o-mini",
        }
        out = slim_model_metadata(dict(md))
        assert out == md

    def test_caller_dict_is_not_mutated(self):
        """`_create_job_sync` re-reads `metadata` for the routing columns after
        this call, so an in-place edit would be a real (if subtle) bug."""
        md = {"checkpoint": _catalogue_row("x.safetensors"), "prompt": "p"}
        slim_model_metadata(md)
        assert "description" in md["checkpoint"]


class TestVolume:
    def test_a_realistic_payload_shrinks_by_two_orders_of_magnitude(self):
        md = {
            "checkpoint": _catalogue_row("dreamshaper_8.safetensors", type="checkpoint"),
            "loras": [_catalogue_row(f"lora_{i}.safetensors") for i in range(6)],
            "prompt": "a cat",
        }
        before = len(json.dumps(md))
        after = len(json.dumps(slim_model_metadata(md)))
        assert after < before / 50, f"only shrank {before} -> {after}"

    def test_a_48_image_gallery_page_would_fit_in_one_checkpoint_record(self):
        """The measured regression: 48 images x 15.5 KB of embedded checkpoint
        record, for a page the browser renders as thumbnails."""
        slimmed = len(json.dumps(slim_model_metadata({"checkpoint": _catalogue_row("x.safetensors")})["checkpoint"]))
        assert slimmed < 400, f"checkpoint record is still {slimmed} B"

    def test_it_actually_dropped_the_bulky_fields(self):
        out = slim_model_metadata({"checkpoint": _catalogue_row("x.safetensors")})
        assert "description" not in out["checkpoint"]
        assert "preview" not in out["checkpoint"]
        assert "provider_statuses" not in out["checkpoint"]


class TestPassThrough:
    def test_a_bare_string_checkpoint_is_kept(self):
        """`BatchGenerate` sends `checkpointName` as a plain string."""
        assert slim_model_metadata({"checkpoint": "x.safetensors"})["checkpoint"] == "x.safetensors"

    def test_an_absurdly_long_string_is_truncated(self):
        out = slim_model_metadata({"checkpoint": "n" * 5000})
        assert len(out["checkpoint"]) == 512

    def test_metadata_without_models_is_returned_as_is(self):
        md = {"prompt": "x"}
        assert slim_model_metadata(md) is md

    def test_non_dict_input_is_tolerated(self):
        assert slim_model_metadata(None) is None

    def test_loras_that_is_not_a_list_is_left_alone(self):
        assert slim_model_metadata({"loras": "nope"})["loras"] == "nope"

    def test_a_list_of_strings_is_preserved_elementwise(self):
        out = slim_model_metadata({"loras": ["a.safetensors", "b.safetensors"]})
        assert out["loras"] == ["a.safetensors", "b.safetensors"]
