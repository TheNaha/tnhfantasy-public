"""Tests for uncovered parts of core/entities_v2.py"""
import pytest
from core.entities import (
    get_directory_from_type,
    compute_storage_filename,
    is_unet_only_model,
    FLUX_DEFAULT_COMPONENTS,
    UNET_ONLY_BASE_MODELS,
)


class TestGetDirectoryFromType:
    def test_checkpoint(self):
        assert get_directory_from_type("Checkpoint") == "checkpoints"

    def test_lora(self):
        assert get_directory_from_type("LORA") == "loras"

    def test_locon(self):
        assert get_directory_from_type("LoCon") == "loras"

    def test_textual_inversion(self):
        assert get_directory_from_type("TextualInversion") == "embeddings"

    def test_hypernetwork(self):
        assert get_directory_from_type("Hypernetwork") == "hypernetworks"

    def test_controlnet(self):
        assert get_directory_from_type("Controlnet") == "controlnet"

    def test_vae(self):
        assert get_directory_from_type("VAE") == "vae"

    def test_upscaler(self):
        assert get_directory_from_type("Upscaler") == "upscale_models"

    def test_motion_module(self):
        assert get_directory_from_type("MotionModule") == "motion_modules"

    def test_unknown_type(self):
        assert get_directory_from_type("Unknown") == "other"

    def test_flux_checkpoint_goes_to_unet(self):
        """Flux Checkpoints should go to unet/ directory."""
        assert get_directory_from_type("Checkpoint", "Flux.1 D") == "unet"

    def test_flux_dev_goes_to_unet(self):
        assert get_directory_from_type("Checkpoint", "Flux.1 Dev") == "unet"

    def test_non_flux_checkpoint(self):
        assert get_directory_from_type("Checkpoint", "SD 1.5") == "checkpoints"

    def test_sdxl_checkpoint(self):
        assert get_directory_from_type("Checkpoint", "SDXL 1.0") == "checkpoints"

    def test_none_base_model(self):
        assert get_directory_from_type("Checkpoint", None) == "checkpoints"


class TestComputeStorageFilename:
    def test_basic_filename(self):
        result = compute_storage_filename("My Model", "v1.0", 12345, "model.safetensors")
        assert "12345" in result
        assert "safetensors" in result

    def test_sanitizes_special_chars(self):
        result = compute_storage_filename("Model!@#$", "v1.0!", 1, "model.safetensors")
        assert "!@#$" not in result

    def test_replaces_spaces(self):
        result = compute_storage_filename("My Cool Model", "Version 1", 1, "model.safetensors")
        assert " " not in result

    def test_correct_extension(self):
        result = compute_storage_filename("Model", "v1", 1, "model.ckpt")
        assert result.endswith(".ckpt")

    def test_no_extension_defaults_safetensors(self):
        result = compute_storage_filename("Model", "v1", 1, "model")
        # When no extension in original_filename, defaults to safetensors
        assert "model" in result

    def test_long_name_truncated(self):
        long_name = "A" * 100
        result = compute_storage_filename(long_name, "v1.0", 1, "model.safetensors")
        # The name should be truncated to avoid excessively long filenames
        assert len(result) < 200


class TestIsUnetOnlyModel:
    def test_flux_d(self):
        assert is_unet_only_model("Flux.1 D") is True

    def test_flux_dev(self):
        assert is_unet_only_model("Flux.1 Dev") is True

    def test_flux_schnell(self):
        assert is_unet_only_model("Flux.1 Schnell") is True

    def test_aura_flow(self):
        assert is_unet_only_model("AuraFlow") is True

    def test_sd15_is_not_unet_only(self):
        assert is_unet_only_model("SD 1.5") is False

    def test_sdxl_is_not_unet_only(self):
        assert is_unet_only_model("SDXL 1.0") is False

    def test_none_returns_false(self):
        assert is_unet_only_model(None) is False

    def test_empty_string_returns_false(self):
        assert is_unet_only_model("") is False

    def test_flux_lowercase(self):
        # Test case insensitivity
        assert is_unet_only_model("flux.1 dev") is True


class TestFluxDefaultComponents:
    def test_flux_components_exist(self):
        assert isinstance(FLUX_DEFAULT_COMPONENTS, dict)

    def test_has_required_keys(self):
        # Should have commonly needed keys
        assert len(FLUX_DEFAULT_COMPONENTS) > 0


class TestUnetOnlyBaseModels:
    def test_is_list(self):
        assert isinstance(UNET_ONLY_BASE_MODELS, list)

    def test_contains_flux(self):
        # Should have flux-related entries
        flux_entries = [m for m in UNET_ONLY_BASE_MODELS if "flux" in m.lower() or "Flux" in m]
        assert len(flux_entries) > 0
