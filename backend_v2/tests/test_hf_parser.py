"""Tests for infrastructure/parsers/hf_parser.py"""
from infrastructure.parsers.hf_parser import (
    extract_description,
    extract_preview_images,
    generate_hf_id,
    get_download_url,
    infer_base_model,
    infer_model_type,
    normalize_hf_to_civitai,
    parse_hf_url,
)


class TestInferModelType:
    def test_lora_tag(self):
        assert infer_model_type(["lora", "diffusers"]) == "LORA"

    def test_locon_tag(self):
        assert infer_model_type(["locon"]) == "LORA"

    def test_dora_tag(self):
        assert infer_model_type(["dora"]) == "LORA"

    def test_controlnet_tag(self):
        assert infer_model_type(["controlnet"]) == "Controlnet"

    def test_controlnet_pipeline(self):
        assert infer_model_type([], pipeline_tag="controlnet") == "Controlnet"

    def test_vae_tag(self):
        assert infer_model_type(["vae"]) == "VAE"

    def test_textual_inversion_tag(self):
        assert infer_model_type(["textual-inversion"]) == "TextualInversion"

    def test_embedding_tag(self):
        assert infer_model_type(["embedding"]) == "TextualInversion"

    def test_upscaler_tag(self):
        assert infer_model_type(["upscaler"]) == "Upscaler"

    def test_real_esrgan_tag(self):
        assert infer_model_type(["real-esrgan"]) == "Upscaler"

    def test_hypernetwork_tag(self):
        assert infer_model_type(["hypernetwork"]) == "Hypernetwork"

    def test_motion_tag(self):
        assert infer_model_type(["motion"]) == "MotionModule"

    def test_animatediff_tag(self):
        assert infer_model_type(["animatediff"]) == "MotionModule"

    def test_pose_tag(self):
        assert infer_model_type(["pose"]) == "Poses"

    def test_poses_tag(self):
        assert infer_model_type(["poses"]) == "Poses"

    def test_diffusers_tag_checkpoint(self):
        assert infer_model_type(["diffusers"]) == "Checkpoint"

    def test_text_to_image_pipeline(self):
        assert infer_model_type([], pipeline_tag="text-to-image") == "Checkpoint"

    def test_image_to_image_pipeline(self):
        assert infer_model_type([], pipeline_tag="image-to-image") == "Checkpoint"

    def test_empty_tags_default(self):
        assert infer_model_type([]) == "Checkpoint"

    def test_case_insensitive(self):
        assert infer_model_type(["LORA"]) == "LORA"
        assert infer_model_type(["VAE"]) == "VAE"


class TestInferBaseModel:
    def test_sdxl_tag(self):
        assert infer_base_model(["sdxl"]) == "SDXL 1.0"

    def test_sdxl_in_card(self):
        assert infer_base_model([], card_content="built on SDXL") == "SDXL 1.0"

    def test_sd3_tag(self):
        assert infer_base_model(["sd3"]) == "SD 3"

    def test_stable_diffusion_3_tag(self):
        assert infer_base_model(["stable-diffusion-3"]) == "SD 3"

    def test_sd3_card(self):
        assert infer_base_model([], card_content="stable diffusion 3 model") == "SD 3"

    def test_pony_tag(self):
        assert infer_base_model(["pony"]) == "Pony"

    def test_pony_card(self):
        assert infer_base_model([], card_content="based on pony diffusion") == "Pony"

    def test_sd2_tag(self):
        assert infer_base_model(["sd2"]) == "SD 2.1"

    def test_stable_diffusion_2_tag(self):
        assert infer_base_model(["stable-diffusion-2"]) == "SD 2.1"

    def test_sd15_tag(self):
        assert infer_base_model(["sd15"]) == "SD 1.5"

    def test_sd15_card(self):
        assert infer_base_model([], card_content="stable diffusion 1.5 finetuned") == "SD 1.5"

    def test_sd15_card_shorthand(self):
        assert infer_base_model([], card_content="based on sd 1.5") == "SD 1.5"

    def test_stable_diffusion_in_card(self):
        assert infer_base_model([], card_content="stable-diffusion checkpoint") == "SD 1.5"

    def test_default_sd15(self):
        assert infer_base_model([]) == "SD 1.5"

    def test_sd_1_5_tag(self):
        assert infer_base_model(["sd-1-5"]) == "SD 1.5"

    def test_stable_diffusion_v1_5_tag(self):
        assert infer_base_model(["stable-diffusion-v1-5"]) == "SD 1.5"


class TestExtractPreviewImages:
    def test_empty_card(self):
        assert extract_preview_images("") == []

    def test_none_card(self):
        assert extract_preview_images(None) == []

    def test_markdown_image(self):
        card = "![preview](https://example.com/image.png)"
        images = extract_preview_images(card)
        assert len(images) == 1
        assert images[0]["url"] == "https://example.com/image.png"

    def test_skips_badge(self):
        card = "![badge](https://img.shields.io/badge/test)"
        images = extract_preview_images(card)
        assert len(images) == 0

    def test_skips_relative_urls(self):
        card = "![preview](/local/image.png)"
        images = extract_preview_images(card)
        assert len(images) == 0

    def test_skips_non_http(self):
        card = "![preview](ftp://example.com/img.png)"
        images = extract_preview_images(card)
        assert len(images) == 0

    def test_html_img_tag(self):
        card = '<img src="https://example.com/preview.jpg" />'
        images = extract_preview_images(card)
        assert len(images) >= 1

    def test_limits_to_10_images(self):
        card = "\n".join(
            [f"![img{i}](https://example.com/img{i}.png)" for i in range(20)]
        )
        images = extract_preview_images(card)
        assert len(images) <= 10

    def test_image_structure(self):
        card = "![alt text](https://example.com/img.png)"
        images = extract_preview_images(card)
        assert images[0]["type"] == "image"

    def test_skips_shield_badge(self):
        card = "![shield](https://img.shields.io/shield/test)"
        images = extract_preview_images(card)
        assert len(images) == 0


class TestExtractDescription:
    def test_empty_card(self):
        result = extract_description("")
        assert result == "No description available."

    def test_none_card(self):
        result = extract_description(None)
        assert result == "No description available."

    def test_extracts_first_substantial_paragraph(self):
        card = "# Header\n\nThis is a detailed description of the model that is longer than 50 characters total."
        result = extract_description(card)
        assert "description" in result.lower() or len(result) > 0

    def test_removes_yaml_frontmatter(self):
        card = "---\nlicense: creativeml-openrail-m\n---\n\nThis is a fine model that does great things."
        result = extract_description(card)
        assert "license" not in result

    def test_limits_to_500_chars(self):
        card = "A" * 600
        result = extract_description(card)
        assert len(result) <= 503  # 500 + "..."

    def test_skips_list_items(self):
        card = "- Item one\n- Item two\n\nThis is a real paragraph that is long enough to be selected."
        result = extract_description(card)
        assert not result.startswith("-")

    def test_skips_markdown_headers(self):
        card = "# Title\n\nSome content that is really long and informative."
        result = extract_description(card)
        assert not result.startswith("#")

    def test_fallback_to_first_paragraph(self):
        card = "Short."
        result = extract_description(card)
        assert result == "Short."


class TestGenerateHfId:
    def test_returns_int(self):
        assert isinstance(generate_hf_id("user/model"), int)

    def test_consistent_for_same_input(self):
        assert generate_hf_id("user/model") == generate_hf_id("user/model")

    def test_different_for_different_inputs(self):
        assert generate_hf_id("user/model1") != generate_hf_id("user/model2")

    def test_reasonable_size(self):
        hf_id = generate_hf_id("user/model")
        assert hf_id < 10**9


class TestNormalizeHfToCivitai:
    def test_basic_structure(self):
        hf_data = {
            "id": "user/model",
            "author": "user",
            "tags": ["diffusers"],
            "pipeline_tag": "text-to-image",
            "downloads": 100,
            "likes": 50,
        }
        result = normalize_hf_to_civitai(hf_data)
        assert "id" in result
        assert "name" in result
        assert "type" in result
        assert "modelVersions" in result
        assert result["_source"] == "huggingface"

    def test_model_name_from_repo(self):
        hf_data = {"id": "user/my-model", "tags": []}
        result = normalize_hf_to_civitai(hf_data)
        assert "My Model" in result["name"]

    def test_stats_from_hf(self):
        hf_data = {"id": "user/model", "tags": [], "downloads": 500, "likes": 100}
        result = normalize_hf_to_civitai(hf_data)
        assert result["stats"]["downloadCount"] == 500
        assert result["stats"]["favoriteCount"] == 100

    def test_model_versions_structure(self):
        hf_data = {"id": "user/model", "tags": []}
        result = normalize_hf_to_civitai(hf_data)
        assert len(result["modelVersions"]) == 1
        version = result["modelVersions"][0]
        assert "files" in version
        assert "baseModel" in version

    def test_with_files_data_finds_safetensors(self):
        hf_data = {"id": "user/model", "tags": []}
        files_data = [
            {"path": "config.json", "size": 1000},
            {"path": "model.safetensors", "size": 2048000000},
        ]
        result = normalize_hf_to_civitai(hf_data, files_data)
        assert result["modelVersions"][0]["files"][0]["name"] == "model.safetensors"

    def test_nsfw_false_by_default(self):
        hf_data = {"id": "user/model", "tags": []}
        result = normalize_hf_to_civitai(hf_data)
        assert result["nsfw"] is False

    def test_filters_technical_tags(self):
        hf_data = {"id": "user/model", "tags": ["diffusers", "safetensors", "anime", "pytorch"]}
        result = normalize_hf_to_civitai(hf_data)
        assert "diffusers" not in result["tags"]
        assert "anime" in result["tags"]

    def test_creator_from_author(self):
        hf_data = {"id": "myuser/model", "author": "myuser", "tags": []}
        result = normalize_hf_to_civitai(hf_data)
        assert result["creator"]["username"] == "myuser"

    def test_repo_id_key(self):
        hf_data = {"id": "user/model", "tags": []}
        result = normalize_hf_to_civitai(hf_data)
        assert result["_repo_id"] == "user/model"

    def test_checkpoint_fallback_file(self):
        hf_data = {"id": "user/model", "tags": ["diffusers"]}
        result = normalize_hf_to_civitai(hf_data)
        assert result["modelVersions"][0]["files"][0]["name"] == "model.safetensors"

    def test_lora_fallback_file(self):
        hf_data = {"id": "user/model", "tags": ["lora"]}
        result = normalize_hf_to_civitai(hf_data)
        assert "lora" in result["modelVersions"][0]["files"][0]["name"].lower()

    def test_model_id_from_modelId_field(self):
        hf_data = {"modelId": "user/model2", "tags": []}
        result = normalize_hf_to_civitai(hf_data)
        assert result["_repo_id"] == "user/model2"


class TestParseHfUrl:
    def test_resolve_url(self):
        url = "https://huggingface.co/user/model/resolve/main/file.safetensors"
        result = parse_hf_url(url)
        assert result is not None
        assert result["repo_id"] == "user/model"
        assert result["branch"] == "main"
        assert result["file_path"] == "file.safetensors"

    def test_blob_url(self):
        url = "https://huggingface.co/user/model/blob/main/file.ckpt"
        result = parse_hf_url(url)
        assert result is not None
        assert result["repo_id"] == "user/model"
        assert result["file_path"] == "file.ckpt"

    def test_simple_repo_url(self):
        url = "https://huggingface.co/user/model"
        result = parse_hf_url(url)
        assert result is not None
        assert result["repo_id"] == "user/model"
        assert result["file_path"] is None
        assert result["branch"] == "main"

    def test_invalid_url_returns_none(self):
        result = parse_hf_url("https://civitai.com/model/123")
        assert result is None

    def test_empty_string(self):
        result = parse_hf_url("")
        assert result is None


class TestGetDownloadUrl:
    def test_basic_url(self):
        url = get_download_url("user/model", "model.safetensors")
        assert url == "https://huggingface.co/user/model/resolve/main/model.safetensors"

    def test_custom_branch(self):
        url = get_download_url("user/model", "model.ckpt", branch="dev")
        assert url == "https://huggingface.co/user/model/resolve/dev/model.ckpt"

    def test_nested_file_path(self):
        url = get_download_url("user/model", "subdir/file.safetensors")
        assert "subdir/file.safetensors" in url


class TestInferBaseModelSpellings:
    """Base model is a picker FILTER, so a mis-classification does not degrade
    gracefully — it makes the model unfindable. Both families below have more
    than one spelling in the wild."""

    def test_sdxl_long_form_is_not_mistaken_for_sd15(self):
        # HuggingFace uses both `sdxl` and the full `stable-diffusion-xl`.
        # Matching only the shorthand sent every long-form SDXL model down the
        # fall-through and reported it as SD 1.5.
        from infrastructure.parsers.hf_parser import infer_base_model

        assert infer_base_model(["stable-diffusion-xl"]) == "SDXL 1.0"
        assert infer_base_model(["sdxl"]) == "SDXL 1.0"
        assert infer_base_model(["diffusers", "stable-diffusion-xl", "safetensors"]) == "SDXL 1.0"

    def test_illustrious_spellings_collapse_to_one_family(self):
        from infrastructure.parsers.hf_parser import infer_base_model

        for tags in (["illustrious"], ["Illustrious"], ["illustrious-xl"], ["Illustrious-XL"]):
            assert infer_base_model(tags) == "Illustrious"

    def test_illustrious_wins_over_sdxl(self):
        # Illustrious is an SDXL-architecture finetune whose repos also say
        # "sdxl", so ordering is what makes the common case work.
        from infrastructure.parsers.hf_parser import infer_base_model

        assert infer_base_model(["illustrious", "sdxl", "stable-diffusion-xl"]) == "Illustrious"

    def test_other_families_still_classify(self):
        from infrastructure.parsers.hf_parser import infer_base_model

        assert infer_base_model(["stable-diffusion-2-1-base"]) == "SD 2.1"
        assert infer_base_model(["stable-diffusion-3-medium"]) == "SD 3"
        assert infer_base_model(["pony"]) == "Pony"
        assert infer_base_model(["anything-v3"]) == "SD 1.5"


class TestDeclaredBaseModelWins:
    """HuggingFace returns the base model STRUCTURALLY. Inference used to run on
    free-form tags plus the model card's prose, and on this library's real
    payloads the tag array is empty on most entries that declare one — so a
    declared Illustrious or Pony LoRA was filed as SD 1.5 and the base-model
    filter hid it."""

    def test_declared_value_is_used_with_no_tags_at_all(self):
        from infrastructure.parsers.hf_parser import infer_base_model

        assert infer_base_model([], None, "Illustrious") == "Illustrious"
        assert infer_base_model([], None, "Pony") == "Pony"
        assert infer_base_model([], None, "SDXL 1.0") == "SDXL 1.0"
        assert infer_base_model([], None, "SD 1.5") == "SD 1.5"
        assert infer_base_model([], None, "Flux") == "Flux"

    def test_declared_value_beats_conflicting_tags(self):
        from infrastructure.parsers.hf_parser import infer_base_model

        # An Illustrious LoRA whose repo also carries the generic 'sdxl' tag
        # must still classify as Illustrious, not SDXL.
        assert infer_base_model(["sdxl", "diffusers"], None, "Illustrious") == "Illustrious"
        assert infer_base_model(["sdxl", "diffusers"], None, "Pony") == "Pony"

    def test_unrecognised_declared_value_falls_back_to_heuristics(self):
        from infrastructure.parsers.hf_parser import infer_base_model

        # An odd declared value must not swallow the tag evidence.
        assert infer_base_model(["illustrious"], None, "something-unknown") == "Illustrious"
        assert infer_base_model(["stable-diffusion-xl"], None, "weird") == "SDXL 1.0"

    def test_absent_declared_value_is_unchanged_behaviour(self):
        from infrastructure.parsers.hf_parser import infer_base_model

        assert infer_base_model(["illustrious"], None, None) == "Illustrious"
        assert infer_base_model([], None, None) == "SD 1.5"

    def test_empty_declared_value_is_ignored(self):
        from infrastructure.parsers.hf_parser import infer_base_model

        assert infer_base_model(["pony"], None, "   ") == "Pony"


class TestHfBaseModelExtraction:
    def test_reads_config_and_card_data(self):
        from services.external_model_service import _hf_base_model

        assert _hf_base_model({"config": {"base_model": "Illustrious"}}) == "Illustrious"
        assert _hf_base_model({"cardData": {"base_model": "Pony"}}) == "Pony"
        assert _hf_base_model({"baseModel": "SDXL 1.0"}) == "SDXL 1.0"
        assert _hf_base_model({"config": {}, "cardData": {}}) is None
        assert _hf_base_model({}) is None


class TestIllustriousFamilyAliases:
    """NoobAI is an Illustrious finetune. Without it, a NoobAI model falls into
    the SD 1.5 default and disappears from the base-model filter — measured on
    this library's payloads, it is a real declared value."""

    def test_noobai_maps_to_illustrious(self):
        from infrastructure.parsers.hf_parser import infer_base_model

        assert infer_base_model([], None, "NoobAI") == "Illustrious"
        assert infer_base_model(["noobai"], None, None) == "Illustrious"

    def test_variants_normalise_to_the_picker_vocabulary(self):
        from infrastructure.parsers.hf_parser import infer_base_model

        # The picker has one option per family, not per upstream spelling.
        assert infer_base_model([], None, "Flux.1 S") == "Flux"
        assert infer_base_model([], None, "Pony V7") == "Pony"
