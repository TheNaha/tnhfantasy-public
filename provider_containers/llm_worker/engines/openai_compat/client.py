import os
import json
import logging
from typing import Dict, Any, Optional

from fastapi.responses import StreamingResponse

from provider_core.base import ProviderClient
from provider_core.models import InferenceRequest, ProviderRuntimeConfig
from provider_core.utils import build_status_response, build_error_response

class OpenAICompatProviderClient(ProviderClient):
    """
    Provider Client for LLM generation via OpenAI-compatible endpoints (OpenRouter, Ollama, vLLM).
    """

    def __init__(self, runtime_config: ProviderRuntimeConfig):
        super().__init__(runtime_config)
        self.logger = logging.getLogger("provider_core.engines.openai_compat")
        
        # Load engine-specific configuration
        self.api_base = os.environ.get("OPENAI_API_BASE", "http://localhost:11434/v1")
        self.api_key = os.environ.get("OPENAI_API_KEY", "")

    async def get_status(self) -> Dict[str, Any]:
        """Return the status and capabilities of this engine."""
        return {
            "provider_id": self.runtime_config.provider_id,
            "type": "openai_compat",
            "api_base": self.api_base,
            "containerized": True
        }

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        """
        Execute an LLM generation workflow.
        In Phase 5, this will translate SSE streams from OpenAI format into TaskEvents.
        """
        async def stream():
            yield json.dumps(build_error_response("Not implemented yet", retryable=False, code=501)) + "\n"
            
        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        """Setup models for the LLM worker if necessary."""
        return build_status_response("success", "Setup complete", provider=self.runtime_config.provider_id)
