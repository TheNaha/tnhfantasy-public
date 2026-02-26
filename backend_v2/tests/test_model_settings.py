"""Tests for infrastructure/model_settings.py"""
import pytest
from infrastructure.model_settings import (
    BASE_MODEL_DEFAULTS,
    SAMPLER_MAP,
    parse_recommended_settings,
    detect_base_model,
    get_base_model_defaults,
    get_model_settings,
    get_settings_summary,
)


class TestParseRecommendedSettings:
    def test_empty_description(self):
        result = parse_recommended_settings("")
        assert result == {}

    def test_none_description(self):
        result = parse_recommended_settings(None)
        assert result == {}

    def test_steps_single(self):
        result = parse_recommended_settings("Steps: 25")
        assert result["steps"] == 25

    def test_steps_range_takes_higher(self):
        result = parse_recommended_settings("Steps: 15-30")
        assert result["steps"] == 30

    def test_cfg_single(self):
        result = parse_recommended_settings("CFG scale: 7")
        assert result["cfg"] == 7.0

    def test_cfg_range_takes_higher(self):
        result = parse_recommended_settings("CFG: 5-7")
        assert result["cfg"] == 7.0

    def test_sampler_euler_a(self):
        result = parse_recommended_settings("Sampler: Euler a")
        assert result.get("sampler") == "euler_ancestral"

    def test_sampler_dpmpp_2m(self):
        result = parse_recommended_settings("Sampler: DPM++ 2M Karras")
        assert result.get("sampler") == "dpmpp_2m"

    def test_clip_skip(self):
        result = parse_recommended_settings("Clip skip: 2")
        assert result["clip_skip"] == 2

    def test_resolution(self):
        result = parse_recommended_settings("size: 1024x768")
        assert result["width"] == 1024
        assert result["height"] == 768

    def test_html_tags_stripped(self):
        result = parse_recommended_settings("<p>Steps: 20</p>")
        assert result["steps"] == 20

    def test_combined_settings(self):
        desc = "Steps: 25, CFG scale: 7.0, Sampler: Euler a, Clip skip: 2"
        result = parse_recommended_settings(desc)
        assert result["steps"] == 25
        assert result["cfg"] == 7.0
        assert result["sampler"] == "euler_ancestral"
        assert result["clip_skip"] == 2

    def test_no_settings_in_description(self):
        result = parse_recommended_settings("This is a great model for landscapes.")
        assert result == {}

    def test_ddim_sampler(self):
        result = parse_recommended_settings("Sampler: DDIM")
        assert result.get("sampler") == "ddim"

    def test_heun_sampler(self):
        result = parse_recommended_settings("Sampler: Heun")
        assert result.get("sampler") == "heun"

    def test_steps_case_insensitive(self):
        result = parse_recommended_settings("STEPS: 30")
        assert result["steps"] == 30

    def test_cfg_no_scale_word(self):
        result = parse_recommended_settings("CFG: 6.5")
        assert result["cfg"] == 6.5

    def test_steps_with_nbsp(self):
        result = parse_recommended_settings("Steps:&nbsp;20")
        assert result["steps"] == 20


class TestDetectBaseModel:
    def test_none_metadata(self):
        assert detect_base_model(None) is None

    def test_non_dict_metadata(self):
        assert detect_base_model("not_a_dict") is None

    def test_direct_base_model_field(self):
        assert detect_base_model({"baseModel": "SDXL"}) == "SDXL"

    def test_from_model_versions(self):
        meta = {"modelVersions": [{"baseModel": "SD 1.5"}]}
        assert detect_base_model(meta) == "SD 1.5"

    def test_name_flux(self):
        assert detect_base_model({"name": "MyFluxModel"}) == "FLUX"

    def test_name_sd3(self):
        assert detect_base_model({"name": "sd3-checkpoint"}) == "SD 3"

    def test_name_pony(self):
        assert detect_base_model({"name": "PonyXL"}) == "Pony"

    def test_name_illustrious(self):
        assert detect_base_model({"name": "illustrious-xl"}) == "Illustrious"

    def test_name_sdxl(self):
        assert detect_base_model({"name": "mymodel-sdxl"}) == "SDXL"

    def test_name_sd15(self):
        assert detect_base_model({"name": "sd1.5-model"}) == "SD 1.5"

    def test_empty_metadata(self):
        assert detect_base_model({}) is None

    def test_name_illu_prefix(self):
        assert detect_base_model({"name": "ill-portrait"}) == "Illustrious"

    def test_illu_variant(self):
        assert detect_base_model({"name": "illumodel"}) == "Illustrious"


class TestGetBaseModelDefaults:
    def test_sdxl(self):
        defaults = get_base_model_defaults("SDXL")
        assert defaults["steps"] == 30
        assert defaults["width"] == 1024

    def test_sd15(self):
        defaults = get_base_model_defaults("SD 1.5")
        assert defaults["steps"] == 25
        assert defaults["width"] == 512

    def test_pony(self):
        defaults = get_base_model_defaults("Pony")
        assert defaults["cfg"] == 6.0

    def test_flux(self):
        defaults = get_base_model_defaults("FLUX")
        assert defaults["steps"] == 20
        assert defaults["cfg"] == 1.0

    def test_sd3(self):
        defaults = get_base_model_defaults("SD 3")
        assert defaults["steps"] == 28

    def test_illustrious(self):
        defaults = get_base_model_defaults("Illustrious")
        assert defaults["clip_skip"] == 2

    def test_unknown_returns_empty(self):
        assert get_base_model_defaults("Unknown Model") == {}

    def test_none_returns_empty(self):
        assert get_base_model_defaults(None) == {}

    def test_empty_string_returns_empty(self):
        assert get_base_model_defaults("") == {}

    def test_returns_copy(self):
        d1 = get_base_model_defaults("SDXL")
        d2 = get_base_model_defaults("SDXL")
        d1["steps"] = 999
        assert d2["steps"] == 30

    def test_case_insensitive_sdxl(self):
        # Should match 'sdxl' in 'SDXL 1.0' etc.
        defaults = get_base_model_defaults("SDXL 1.0")
        assert defaults != {}

    def test_sd14(self):
        defaults = get_base_model_defaults("SD 1.4")
        assert defaults["width"] == 512
        assert defaults["height"] == 512


class TestGetModelSettings:
    def test_empty_metadata(self):
        result = get_model_settings({})
        assert result == {}

    def test_with_base_model_sets_source(self):
        meta = {"baseModel": "SDXL"}
        result = get_model_settings(meta)
        assert "_source" in result
        assert "baseModel:SDXL" in result["_source"]

    def test_description_overrides_defaults(self):
        meta = {
            "baseModel": "SDXL",
            "description": "Steps: 40"
        }
        result = get_model_settings(meta)
        assert result["steps"] == 40

    def test_no_base_model_no_description(self):
        meta = {"name": "random-model"}
        result = get_model_settings(meta)
        assert result == {}

    def test_description_parsed_sets_source(self):
        meta = {"baseModel": "SDXL", "description": "Steps: 35, CFG: 8"}
        result = get_model_settings(meta)
        assert result["_source"] == "parsed_description"

    def test_base_model_only_source(self):
        meta = {"baseModel": "Pony"}
        result = get_model_settings(meta)
        assert "baseModel:Pony" in result["_source"]

    def test_includes_base_model_key(self):
        meta = {"baseModel": "FLUX"}
        result = get_model_settings(meta)
        assert result.get("_baseModel") == "FLUX"


class TestGetSettingsSummary:
    def test_empty_settings(self):
        assert get_settings_summary({}) == "No settings"

    def test_with_steps(self):
        settings = {"steps": 25, "_baseModel": "SDXL"}
        summary = get_settings_summary(settings)
        assert "25 steps" in summary

    def test_with_cfg(self):
        settings = {"cfg": 7.0, "_baseModel": "SD 1.5"}
        summary = get_settings_summary(settings)
        assert "CFG 7.0" in summary

    def test_with_sampler(self):
        settings = {"sampler": "euler_ancestral", "_baseModel": "Pony"}
        summary = get_settings_summary(settings)
        assert "euler_ancestral" in summary

    def test_with_resolution(self):
        settings = {"width": 1024, "height": 1024, "_baseModel": "SDXL"}
        summary = get_settings_summary(settings)
        assert "1024x1024" in summary

    def test_base_model_in_summary(self):
        settings = {"steps": 20, "_baseModel": "FLUX"}
        summary = get_settings_summary(settings)
        assert "FLUX" in summary

    def test_no_base_model_uses_unknown(self):
        settings = {"steps": 20}
        summary = get_settings_summary(settings)
        assert "Unknown" in summary

    def test_full_settings(self):
        settings = {
            "steps": 30,
            "cfg": 7.0,
            "sampler": "dpmpp_2m",
            "width": 1024,
            "height": 1024,
            "_baseModel": "SDXL"
        }
        summary = get_settings_summary(settings)
        assert "SDXL" in summary
        assert "30 steps" in summary
        assert "CFG 7.0" in summary


class TestConstants:
    def test_sampler_map_has_euler_a(self):
        assert "euler a" in SAMPLER_MAP
        assert SAMPLER_MAP["euler a"] == "euler_ancestral"

    def test_sampler_map_has_dpmpp(self):
        assert "dpm++ 2m" in SAMPLER_MAP

    def test_base_model_defaults_keys(self):
        expected = {"SDXL", "SD 1.5", "SD 1.4", "Pony", "Illustrious", "FLUX", "SD 3"}
        assert set(BASE_MODEL_DEFAULTS.keys()) == expected

    def test_all_base_models_have_required_keys(self):
        required = {"steps", "cfg", "sampler", "scheduler", "width", "height", "clip_skip"}
        for name, defaults in BASE_MODEL_DEFAULTS.items():
            assert required.issubset(set(defaults.keys())), f"{name} missing keys"
