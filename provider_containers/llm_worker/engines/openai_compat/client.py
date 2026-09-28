import os
import json
import logging
from typing import Dict, Any, Optional

from fastapi.responses import StreamingResponse

from provider_core.base_client import BaseProviderClient
from provider_core.http_client import get_http_client
from provider_core.models import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest, TaskEvent
)
from provider_core.responses import (
    failed,
    files_response,
    llm_healthy,
    llm_unhealthy,
    ok,
    retryable_for_exception,
    retryable_for_status,
)


# The backend's `_check_provider_health` (services/load_balancer.py) counts any
# provider that answers within a couple of seconds, so the probe has to be
# tighter than that or a dead endpoint is still counted as a usable target.
# Sibling engines each define their own copy of this constant and keep them in
# step by hand — the drift `provider_core/http_client.py` should eventually own.
HEALTH_PROBE_TIMEOUT = float(os.getenv("OPENAI_COMPAT_HEALTH_PROBE_TIMEOUT", "1.5"))


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
        """Probe the OpenAI-compatible endpoint instead of asserting health.

        This returned a hardcoded `{"status": "healthy"}` without touching the
        network, and the backend's `_check_provider_health`
        (`services/load_balancer.py`) requires HTTP 200, so it counted this
        provider as a usable target and dispatched paid LLM jobs at it. With no
        `OPENAI_API_KEY`, or a dead `OPENAI_API_BASE` (the default is
        `http://localhost:11434/v1`), every job failed.

        `GET /models` is free — it is not a completion — and every
        OpenAI-compatible server implements it (vLLM, Ollama, llama.cpp,
        LM Studio, OpenRouter, Together). It is the same endpoint
        `list_models` already calls, so a probe here can never be a
        configuration that works for one and not the other.

        The response shape comes from `llm_healthy` / `llm_unhealthy` in
        `provider_core/responses.py`, which the other three LLM engines use too:
        each engine grew its own shape when the fix was applied piecemeal, and
        `openai_compat` came to differ from its three siblings for no visible
        reason.
        """
        if not self.api_key:
            return llm_unhealthy(
                "openai_compat",
                self.provider_id,
                "no API key configured (OPENAI_API_KEY)",
                api_base=self.api_base,
            )
        client = await get_http_client().get_client()
        try:
            response = await client.get(
                f"{self.api_base}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=HEALTH_PROBE_TIMEOUT,
            )
        except Exception as exc:
            # A refused or unanswered connection really can come back.
            return llm_unhealthy(
                "openai_compat",
                self.provider_id,
                f"GET /models failed: {exc}",
                retryable=True,
                api_base=self.api_base,
            )

        if response.status_code >= 400:
            return llm_unhealthy(
                "openai_compat",
                self.provider_id,
                f"GET /models returned HTTP {response.status_code}",
                # 401/403 is a key the endpoint will never accept; 5xx is a
                # server having a bad day. Only the second one is worth waiting
                # for, and only the second one is worth re-dispatching.
                retryable=retryable_for_status(response.status_code),
                api_base=self.api_base,
            )
        return llm_healthy("openai_compat", self.provider_id, api_base=self.api_base)

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
                if request.top_p is not None:
                    payload["top_p"] = request.top_p
                if request.max_output_tokens is not None:
                    payload["max_tokens"] = request.max_output_tokens
                if request.frequency_penalty is not None:
                    payload["frequency_penalty"] = request.frequency_penalty
                if request.presence_penalty is not None:
                    payload["presence_penalty"] = request.presence_penalty

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
                yield TaskEvent(event="failed", job_id=job_id, message=str(e), retryable=retryable_for_exception(e)).to_ndjson()
            finally:
                if job_id:
                    await self.job_tracker.end_job(job_id)

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    # =========================================================================
    # MODEL MANAGEMENT (stubs - LLM workers don't manage model files)
    # =========================================================================

    async def setup_models(self) -> Dict[str, Any]:
        """LLM workers don't manage weights locally; no-op."""
        return ok("Setup complete", provider=self.provider_id)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        """LLM workers delegate model management to the upstream API.

        501, not a success: this method cannot download anything, and answering
        `ok(...)` told the backend a download had happened when no bytes moved.
        `direct_url` answers the identical situation the same way.
        """
        return failed(
            "LLM workers do not manage model files directly. "
            "Add the model through your LLM provider instead.",
            code=501,
            provider=self.provider_id,
        )

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
            return files_response(
                [{"path": m, "name": m} for m in model_ids],
                provider=self.provider_id,
            )
        except Exception as e:
            self.logger.warning(f"Failed to list models from upstream: {e}")
            return files_response(
                [],
                message=f"Failed to list models from upstream: {e}",
                provider=self.provider_id,
            )

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        """LLM workers do not delete upstream models."""
        return failed("LLM workers do not delete upstream models.", code=404, provider=self.provider_id)

    async def get_file(self, path: str):
        """Not supported for LLM workers."""
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File access not supported for LLM workers.")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        """Not supported for LLM workers."""
        return failed("File deletion not supported for LLM workers.", code=404, provider=self.provider_id)

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        """Not supported for LLM workers."""
        return failed("File upload not supported for LLM workers.", code=404, provider=self.provider_id)

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Not applicable for openai_compat engine."""
        return ok("Deployment not managed by openai_compat engine.", provider=self.provider_id)

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        """Not applicable for LLM workers."""
        return ok("Model validation not applicable for LLM workers.", provider=self.provider_id)

    async def validate_all_models(self) -> Dict[str, Any]:
        """Not applicable for LLM workers."""
        return ok("Model validation not applicable for LLM workers.", provider=self.provider_id)

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
        return ok("No reconciliation needed for LLM workers.", provider=self.provider_id)
