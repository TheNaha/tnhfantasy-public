"""
In-Process Compute Engines package.
"""

from services.engines.base import InProcessEngine
from services.engines.modal_engine import ModalEngine
from services.engines.beam_engine import BeamEngine
from services.engines.direct_comfy_engine import DirectComfyEngine
from services.engines.llm_engine import OpenAICompatLLMEngine, ModalVLLMEngine, AnthropicLLMEngine, GoogleLLMEngine
from services.engines.modal_tts_engine import ModalTTSEngine
from services.engines.engine_factory import (
    get_engine,
    can_create_engine,
    engine_supports_setup,
    register_engine,
    clear_engine_cache,
    invalidate_engine,
)

__all__ = [
    "InProcessEngine",
    "ModalEngine",
    "BeamEngine",
    "DirectComfyEngine",
    "OpenAICompatLLMEngine",
    "AnthropicLLMEngine",
    "GoogleLLMEngine",
    "ModalVLLMEngine",
    "ModalTTSEngine",
    "get_engine",
    "can_create_engine",
    "engine_supports_setup",
    "register_engine",
    "clear_engine_cache",
    "invalidate_engine",
]
