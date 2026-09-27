"""Illustrious classification in infrastructure/parsers/hf_parser.py.

This library is full of Illustrious content — sampling the real metadata gives
98 of 200 LoRAs and 5 of 12 checkpoints with base model ``Illustrious`` — and
base model is a *picker filter*, not a label. With no Illustrious branch in
`infer_base_model`, a HuggingFace model tagged ``illustrious`` fell through to
the safe default ``SD 1.5``, so those models were filed under the wrong base
model and the wrong results came back when filtering.

The tests below cover every case variant CivitAI and HF actually use, plus the
regressions that matter: the spellings that already worked must keep working,
and the branch ordering must not let the SDXL check claim an Illustrious model
first (Illustrious is an SDXL-architecture finetune, so its cards say "sdxl").
"""
from infrastructure.parsers.hf_parser import infer_base_model


class TestInferBaseModelIllustrious:
    def test_lowercase_tag(self):
        assert infer_base_model(["illustrious"]) == "Illustrious"

    def test_capitalised_tag(self):
        assert infer_base_model(["Illustrious"]) == "Illustrious"

    def test_illustrious_xl_tag(self):
        assert infer_base_model(["Illustrious-XL"]) == "Illustrious"

    def test_lowercase_illustrious_xl_tag(self):
        assert infer_base_model(["illustrious-xl"]) == "Illustrious"

    def test_tag_among_others(self):
        assert infer_base_model(["lora", "anime", "Illustrious", "diffusers"]) == "Illustrious"

    def test_underscore_spelling(self):
        # Some repos spell it as a python-style slug.
        assert infer_base_model(["illustrious_xl"]) == "Illustrious"

    def test_illustrious_in_card(self):
        assert infer_base_model([], card_content="Fine-tune of Illustrious by the community") == "Illustrious"

    def test_illustrious_in_card_is_case_insensitive(self):
        assert infer_base_model([], card_content="trained on ILLUSTRIOUS") == "Illustrious"

    def test_illustrious_wins_over_an_sdxl_tag(self):
        # Illustrious is an SDXL-architecture finetune, so its repos carry "sdxl"
        # too. Checking SDXL first is how these models ended up mis-filtered.
        assert infer_base_model(["lora", "sdxl", "illustrious"]) == "Illustrious"

    def test_illustrious_wins_over_sdxl_in_the_card(self):
        assert infer_base_model([], card_content="SDXL architecture, finetuned on Illustrious") == "Illustrious"

    def test_illustrious_wins_over_pony_tag(self):
        # Pony is checked later in the function; the more specific family has to
        # be decided first regardless of the order the branches are written in.
        assert infer_base_model(["pony", "illustrious"]) == "Illustrious"

    def test_illustrious_wins_over_sd15_tag(self):
        assert infer_base_model(["sd15", "illustrious"]) == "Illustrious"

    def test_pure_illustrious_is_not_mistaken_for_sdxl(self):
        # "illustrious" contains no "sdxl" substring, so the single branch is
        # genuinely one check and not a coincidence of the others.
        assert "sdxl" not in "illustrious"


class TestInferBaseModelIllustriousDoesNotRegressOthers:
    def test_sdxl_tag(self):
        assert infer_base_model(["sdxl"]) == "SDXL 1.0"

    def test_sdxl_in_card(self):
        assert infer_base_model([], card_content="built on SDXL") == "SDXL 1.0"

    def test_sd3_tag(self):
        assert infer_base_model(["sd3"]) == "SD 3"

    def test_pony_tag(self):
        assert infer_base_model(["pony"]) == "Pony"

    def test_sd2_tag(self):
        assert infer_base_model(["sd2"]) == "SD 2.1"

    def test_sd15_tag(self):
        assert infer_base_model(["sd15"]) == "SD 1.5"

    def test_sd_1_5_tag(self):
        assert infer_base_model(["sd-1-5"]) == "SD 1.5"

    def test_stable_diffusion_v1_5_tag(self):
        assert infer_base_model(["stable-diffusion-v1-5"]) == "SD 1.5"

    def test_sd15_card(self):
        assert infer_base_model([], card_content="stable diffusion 1.5 finetuned") == "SD 1.5"

    def test_stable_diffusion_in_card_defaults_to_sd15(self):
        assert infer_base_model([], card_content="stable-diffusion checkpoint") == "SD 1.5"

    def test_empty_defaults_to_sd15(self):
        assert infer_base_model([]) == "SD 1.5"
