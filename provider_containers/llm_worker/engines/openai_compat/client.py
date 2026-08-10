import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional

from fastapi.responses import StreamingResponse

from provider_core.base_client import BaseProviderClient
from provider_core.http_client import get_http_client
from provider_core.models import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest,
    build_status_response, build_error_response, TaskEvent
)


class OpenAICompatProviderClient(BaseProviderClient):
    """
    Provider Client for LLM generation via OpenAI-compatible endpoints (OpenRouter, Ollama, vLLM).
    Implements the BaseProviderClient abstract interface.
    """

    def __init__(self, provider_id: str, runtime_config: Dict[str, Any]):
        super().__init__(provider_id=provider_id, runtime_config=runtime_config)
        self.logger = logging.getLogger("provider_core.engines.openai_compat")

        # Load engine-specific configuration
        self.api_base = os.environ.get("OPENAI_API_BASE", "http://localhost:11434/v1")
        self.api_key = os.environ.get("OPENAI_API_KEY", "")

    # =========================================================================
    # HEALTH & INFO
    # =========================================================================

    async def get_health(self) -> Dict[str, Any]:
        """Return health status of this LLM worker."""
        return {
            "status": "healthy",
            "provider_id": self.provider_id,
            "engine": "openai_compat",
            "api_base": self.api_base,
        }

    async def get_info(self) -> Dict[str, Any]:
        """Return static info about this worker."""
        return {
            "provider_id": self.provider_id,
            "type": "openai_compat",
            "api_base": self.api_base,
            "containerized": True,
        }

    # =========================================================================
    # INFERENCE (CORE FUNCTIONALITY)
    # =========================================================================

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        """
        Execute an LLM generation workflow.
        Translates SSE streams from OpenAI format into unified TaskEvents (NDJSON).
        """
        job_id = request.job_id

        async def stream():
            try:
                if job_id:
                    await self.job_tracker.start_job(job_id)

                # Unified InferenceRequest: LLM jobs carry `messages`/`tools`/`model`
                # at the top level (image jobs use `workflow`). Support both.
                workflow = request.workflow or {}
                messages = request.messages or workflow.get("messages", [])
                tools = request.tools or workflow.get("tools")
                model_id = (request.model or workflow.get("model") or os.environ.get("LLM_MODEL", "default-model"))

                payload = {
                    "model": model_id,
                    "messages": messages,
                    "stream": True,
                }
                if tools:
                    payload["tools"] = tools
                if request.temperature is not None:
                    payload["temperature"] = request.temperature

                headers = {"Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"

                timeout = request.timeout_seconds or 120.0
                client = await get_http_client().get_client()

                async with client.stream(
                    "POST",
                    f"{self.api_base}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                ) as response:
                    response.raise_for_status()

                    full_content = ""
                    tool_calls = []

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or line == "data: [DONE]":
                            continue

                        if job_id and await self.job_tracker.is_cancelled(job_id):
                            yield TaskEvent(
                                event="cancelled",
                                job_id=job_id,
                                outputs=[{"role": "assistant", "content": full_content, "cancelled": True}],
                            ).to_ndjson()
                            return

                        if line.startswith("data: "):
                            data_str = line[6:]
                            try:
                                data = json.loads(data_str)
                                choices = data.get("choices", [])
                                if not choices:
                                    continue

                                delta = choices[0].get("delta", {})
                                content = delta.get("content")
                                delta_tool_calls = delta.get("tool_calls")

                                if content:
                                    full_content += content
                                    yield TaskEvent(
                                        event="delta",
                                        job_id=job_id,
                                        text=content,
                                    ).to_ndjson()

                                if delta_tool_calls:
                                    for tc in delta_tool_calls:
                                        index = tc.get("index", 0)
                                        while len(tool_calls) <= index:
                                            tool_calls.append({
                                                "id": "",
                                                "type": "function",
                                                "function": {"name": "", "arguments": ""},
                                            })
                                        if tc.get("id"):
                                            tool_calls[index]["id"] = tc["id"]
                                        if tc.get("type"):
                                            tool_calls[index]["type"] = tc["type"]
                                        if tc.get("function"):
                                            if tc["function"].get("name"):
                                                tool_calls[index]["function"]["name"] = tc["function"]["name"]
                                            if tc["function"].get("arguments"):
                                                tool_calls[index]["function"]["arguments"] += tc["function"]["arguments"]

                            except json.JSONDecodeError:
                                self.logger.error(f"Failed to decode JSON: {data_str}")

                    output = {"role": "assistant", "content": full_content}
                    if tool_calls:
                        output["tool_calls"] = tool_calls

                    yield TaskEvent(
                        event="completed",
                        job_id=job_id,
                        outputs=[output],
                    ).to_ndjson()

            except Exception as e:
                self.logger.error(f"Error during inference: {str(e)}")
                yield TaskEvent(event="failed", job_id=job_id, message=str(e), retryable=True).to_ndjson()
            finally:
                if job_id:
                    await self.job_tracker.end_job(job_id)

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    # =========================================================================
    # MODEL MANAGEMENT (stubs - LLM workers don't manage model files)
    # =========================================================================

    async def setup_models(self) -> Dict[str, Any]:
        """LLM workers don't manage weights locally; no-op."""
        return build_status_response("success", "Setup complete", provider=self.provider_id)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        """LLM workers delegate model management to the upstream API."""
        return build_status_response("success", "LLM workers do not manage model files directly.", provider=self.provider_id)

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        """List available models from the upstream OpenAI-compatible API."""
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            client = await get_http_client().get_client()
            response = await client.get(f"{self.api_base}/models", headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            model_ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
            return {"files": [{"path": m, "name": m} for m in model_ids]}
        except Exception as e:
            self.logger.warning(f"Failed to list models from upstream: {e}")
            return {"files": []}

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        """LLM workers do not delete upstream models."""
        return build_error_response("LLM workers do not delete upstream models.", retryable=False, code=404)

    async def get_file(self, path: str):
        """Not supported for LLM workers."""
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File access not supported for LLM workers.")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        """Not supported for LLM workers."""
        return build_error_response("File deletion not supported for LLM workers.", retryable=False, code=404)

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        """Not supported for LLM workers."""
        return build_error_response("File upload not supported for LLM workers.", retryable=False, code=404)

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Not applicable for openai_compat engine."""
        return build_status_response("success", "Deployment not managed by openai_compat engine.", provider=self.provider_id)

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        """Not applicable for LLM workers."""
        return build_status_response("success", "Model validation not applicable for LLM workers.", provider=self.provider_id)

    async def validate_all_models(self) -> Dict[str, Any]:
        """Not applicable for LLM workers."""
        return build_status_response("success", "Model validation not applicable for LLM workers.", provider=self.provider_id)

    async def get_object_info(self) -> Dict[str, Any]:
        """Return object/node info — not applicable for LLM workers."""
        return {"object_info": {}}

    
    async def get_storage_stats(self) -> Dict[str, Any]:
        """LLM workers don't store model files locally — cheap response, no upstream calls."""
        return {
            "provider_id": self.provider_id,
            "total": 0,
            "by_directory": {},
            "message": "LLM workers do not manage local model files.",
        }

    async def run_reconciliation(self, quick_sync: bool = False) -> Dict[str, Any]:
        """LLM workers have no file system to reconcile."""
        return build_status_response("success", "No reconciliation needed for LLM workers.", provider=self.provider_id)
