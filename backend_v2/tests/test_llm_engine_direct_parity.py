"""Direct LLM provider model remapping and parity tests.

Tests that direct providers (openai_compat, ollama, anthropic, google)
properly normalize model names from placeholders ('rp', 'util', 'default')
and local GGUF IDs (e.g. 'artemis_31b_q4') to their configured external models.
Also tests that canonical 'preview' events pass through translate_legacy_image_update.
"""

from services.engines.base import CANONICAL_EVENT_KINDS, translate_legacy_image_update
from services.engines.llm_engine import (
    resolve_direct_llm_target_model,
    OpenAICompatLLMEngine,
    AnthropicLLMEngine,
    GoogleLLMEngine,
)


class TestDirectLLMModelRemapping:
    def test_explicit_api_model_preserved(self):
        result = resolve_direct_llm_target_model(
            "gpt-4o",
            default_model="gpt-3.5-turbo",
            default_rp_model="claude-3-5-sonnet-latest",
            default_util_model="gpt-4o-mini",
        )
        assert result == "gpt-4o"

        result_anthropic = resolve_direct_llm_target_model(
            "claude-3-haiku-20240307",
            default_model="claude-3-5-sonnet-latest",
            default_rp_model="claude-3-5-sonnet-latest",
            default_util_model="claude-3-5-haiku-latest",
        )
        assert result_anthropic == "claude-3-haiku-20240307"

    def test_role_placeholders_remapped(self):
        # 'rp' or 'default' or None -> default_rp_model
        assert resolve_direct_llm_target_model(
            "rp",
            default_model="default-fallback",
            default_rp_model="claude-3-5-sonnet-latest",
            default_util_model="claude-3-5-haiku-latest",
            role="rp",
        ) == "claude-3-5-sonnet-latest"

        assert resolve_direct_llm_target_model(
            None,
            default_model="default-fallback",
            default_rp_model="claude-3-5-sonnet-latest",
            default_util_model="claude-3-5-haiku-latest",
            role="rp",
        ) == "claude-3-5-sonnet-latest"

        assert resolve_direct_llm_target_model(
            "default",
            default_model="default-fallback",
            default_rp_model="claude-3-5-sonnet-latest",
            default_util_model="claude-3-5-haiku-latest",
        ) == "claude-3-5-sonnet-latest"

        # 'util' or 'decisions' -> default_util_model
        assert resolve_direct_llm_target_model(
            "util",
            default_model="default-fallback",
            default_rp_model="claude-3-5-sonnet-latest",
            default_util_model="claude-3-5-haiku-latest",
            role="util",
        ) == "claude-3-5-haiku-latest"

        assert resolve_direct_llm_target_model(
            "decisions",
            default_model="default-fallback",
            default_rp_model="claude-3-5-sonnet-latest",
            default_util_model="claude-3-5-haiku-latest",
            role="decisions",
        ) == "claude-3-5-haiku-latest"

    def test_internal_gguf_models_remapped_to_direct_models(self):
        # Artemis GGUF -> RP direct model
        assert resolve_direct_llm_target_model(
            "artemis_31b_q4",
            default_model="default-fallback",
            default_rp_model="gpt-4o",
            default_util_model="gpt-4o-mini",
            role="rp",
        ) == "gpt-4o"

        # Sompoa GGUF -> RP direct model
        assert resolve_direct_llm_target_model(
            "sompoa_26b_a4b",
            default_model="default-fallback",
            default_rp_model="claude-3-5-sonnet-latest",
            default_util_model="claude-3-5-haiku-latest",
        ) == "claude-3-5-sonnet-latest"

        # Gemma3 util GGUF -> Util direct model
        assert resolve_direct_llm_target_model(
            "gemma3_12b_heretic_util",
            default_model="default-fallback",
            default_rp_model="claude-3-5-sonnet-latest",
            default_util_model="claude-3-5-haiku-latest",
            role="util",
        ) == "claude-3-5-haiku-latest"

        # Arbitrary .gguf filename -> remaps safely
        assert resolve_direct_llm_target_model(
            "my_custom_model.gguf",
            default_model="gemini-2.0-flash",
            default_rp_model="gemini-2.0-pro",
            default_util_model="gemini-2.0-flash",
        ) == "gemini-2.0-pro"

    def test_direct_engines_init_store_rp_and_util_models(self):
        anthropic = AnthropicLLMEngine(
            provider_id="ant-1",
            api_key="sk-test",
            default_model="claude-3-5-sonnet-latest",
            default_rp_model="claude-3-5-sonnet-latest",
            default_util_model="claude-3-5-haiku-latest",
        )
        assert anthropic.default_rp_model == "claude-3-5-sonnet-latest"
        assert anthropic.default_util_model == "claude-3-5-haiku-latest"

        google = GoogleLLMEngine(
            provider_id="goog-1",
            api_key="aiza-test",
            default_model="gemini-2.0-flash",
            default_rp_model="gemini-2.0-pro",
            default_util_model="gemini-2.0-flash",
        )
        assert google.default_rp_model == "gemini-2.0-pro"
        assert google.default_util_model == "gemini-2.0-flash"

        openai = OpenAICompatLLMEngine(
            provider_id="oai-1",
            api_base="https://api.openai.com/v1",
            api_key="sk-test",
            default_model="gpt-4o",
            default_rp_model="gpt-4o",
            default_util_model="gpt-4o-mini",
        )
        assert openai.default_rp_model == "gpt-4o"
        assert openai.default_util_model == "gpt-4o-mini"


class TestPreviewEventPassThrough:
    def test_preview_in_canonical_kinds(self):
        assert "preview" in CANONICAL_EVENT_KINDS

    def test_translate_legacy_image_update_preserves_preview(self):
        raw_preview = {
            "event": "preview",
            "preview": "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
            "step": 5,
            "total": 20,
        }
        translated = translate_legacy_image_update(raw_preview, job_id="test-job-123")
        assert translated is not None
        assert translated["event"] == "preview"
        assert translated["job_id"] == "test-job-123"
        assert translated["preview"] == "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
        assert translated["step"] == 5
        assert translated["total"] == 20
