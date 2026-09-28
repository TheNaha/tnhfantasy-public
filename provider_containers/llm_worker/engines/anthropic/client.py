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
    UploadFileRequest, ValidateModelsRequest, TaskEvent
)
from provider_core.responses import failed, files_response, llm_healthy, llm_unhealthy, ok, retryable_for_exception, retryable_for_status


# The backend's `_check_provider_health` (services/load_balancer.py) counts any
# provider that answers within a couple of seconds, so the probe has to be
# tighter than that or a dead endpoint is still counted as a usable target.
# Each engine keeps its own copy and they are kept in step by hand — the drift
# `provider_core/http_client.py` should eventually own.
HEALTH_PROBE_TIMEOUT = float(os.getenv("ANTHROPIC_HEALTH_PROBE_TIMEOUT", "1.5"))



def _parse_json(value: Any) -> Any:
    """Best-effort parse of a JSON string; returns raw value on failure."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def translate_tools(tools: Any) -> list[dict[str, Any]]:
    """Translate OpenAI-style tool definitions into Anthropic tool format."""
    if not tools:
        return []
    result = []
    for tool in tools:
        fn = tool.get("function", {}) if isinstance(tool, dict) else {}
        result.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", "") or "",
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return result


def translate_messages(raw_messages: Any) -> tuple[list[dict[str, Any]], str]:
    """Translate OpenAI-style messages into Anthropic message format.

    Handles assistant messages carrying ``tool_calls`` (converted to
    ``tool_use`` content blocks) and ``role == "tool"`` results (converted to
    ``tool_result`` blocks on a user turn).
    """
    system_prompt = ""
    messages: list[dict[str, Any]] = []
    for m in raw_messages:
        if m.get("role") == "system":
            content = m.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            system_prompt += block.get("text", "") + "\n"
            elif isinstance(content, str):
                system_prompt += content + "\n"
            continue

        if m.get("role") == "assistant":
            content = m.get("content", "")
            tool_calls = m.get("tool_calls")
            if tool_calls:
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in tool_calls:
                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": _parse_json(fn.get("arguments")),
                    })
                messages.append({"role": "assistant", "content": blocks})
            else:
                messages.append({"role": "assistant", "content": content})
            continue

        if m.get("role") == "tool":
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id", ""),
                    "content": m.get("content", ""),
                }],
            })
            continue

        messages.append(m)
    return messages, system_prompt


class AnthropicProviderClient(BaseProviderClient):
    """
    Provider Client for LLM generation via Anthropic endpoints (Claude).
    """

    def __init__(self, provider_id: str, runtime_config: Dict[str, Any]):
        super().__init__(provider_id=provider_id, runtime_config=runtime_config)
        self.logger = logging.getLogger("provider_core.engines.anthropic")
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    async def get_health(self) -> Dict[str, Any]:
        """Probe Anthropic's free `GET /v1/models` instead of asserting health.

        This returned a hardcoded `{"status": "healthy"}` without touching the
        network. The backend's `_check_provider_health`
        (`services/load_balancer.py`) requires HTTP 200, so a provider with no
        `ANTHROPIC_API_KEY`, or a dead network, counted as a usable target and
        received paid LLM jobs that all failed. Because every error in this file
        was also marked `retryable=True`, the balancer then re-dispatched across
        every other provider.

        `/v1/models` is free — it is not a completion — and is the same endpoint
        `list_models` already calls, so health and capability can never disagree.
        401/403 means the key is wrong and will stay wrong; 5xx means Anthropic
        is having a moment. `retryable_for_status` draws that line.
        """
        if not self.api_key:
            return llm_unhealthy(
                "anthropic",
                self.provider_id,
                "no API key configured (ANTHROPIC_API_KEY)",
            )
        client = await get_http_client().get_client()
        try:
            response = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                timeout=HEALTH_PROBE_TIMEOUT,
            )
        except Exception as exc:
            return llm_unhealthy(
                "anthropic", self.provider_id, f"GET /v1/models failed: {exc}", retryable=True
            )
        if response.status_code >= 400:
            return llm_unhealthy(
                "anthropic",
                self.provider_id,
                f"GET /v1/models returned HTTP {response.status_code}",
                retryable=retryable_for_status(response.status_code),
            )
        return llm_healthy("anthropic", self.provider_id)

    async def get_info(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "anthropic",
            "containerized": True,
        }

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        job_id = request.job_id

        async def stream():
            try:
                if job_id:
                    await self.job_tracker.start_job(job_id)

                # Unified InferenceRequest: LLM jobs carry `messages`/`tools`/`model`
                # at the top level. Support both shapes.
                workflow = request.workflow or {}
                raw_messages = request.messages or workflow.get("messages", [])
                tools = request.tools or workflow.get("tools")

                messages, system_prompt = translate_messages(raw_messages)

                model_id = (request.model or workflow.get("model") or "claude-3-haiku-20240307")

                payload = {
                    "model": model_id,
                    "messages": messages,
                    "stream": True,
                    "max_tokens": request.max_output_tokens or 4096,
                }
                if tools:
                    payload["tools"] = translate_tools(tools)
                if request.temperature is not None:
                    payload["temperature"] = request.temperature
                # Anthropic supports top_p but NOT frequency/presence penalties.
                if request.top_p is not None:
                    payload["top_p"] = request.top_p
                if system_prompt:
                    payload["system"] = system_prompt.strip()

                headers = {
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }

                timeout = request.timeout_seconds or 120.0
                client = await get_http_client().get_client()

                async with client.stream(
                    "POST",
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                ) as response:
                    response.raise_for_status()

                    full_content = ""
                    tool_blocks: dict[int, dict[str, str]] = {}

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or line.startswith("event:"):
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
                                type_ = data.get("type")

                                if type_ == "content_block_start":
                                    content_block = data.get("content_block") or {}
                                    if content_block.get("type") == "tool_use":
                                        index = data.get("index", 0)
                                        tool_blocks[index] = {
                                            "id": content_block.get("id", ""),
                                            "name": content_block.get("name", ""),
                                            "input_json": "",
                                        }
                                elif type_ == "content_block_delta":
                                    delta = data.get("delta", {}) or {}
                                    if delta.get("type") == "input_json_delta":
                                        index = data.get("index", 0)
                                        entry = tool_blocks.setdefault(
                                            index, {"id": "", "name": "", "input_json": ""}
                                        )
                                        entry["input_json"] += delta.get("partial_json", "")
                                    else:
                                        text = delta.get("text", "")
                                        if text:
                                            full_content += text
                                            yield TaskEvent(
                                                event="delta",
                                                job_id=job_id,
                                                text=text,
                                            ).to_ndjson()
                            except json.JSONDecodeError:
                                pass

                output = {"role": "assistant", "content": full_content}
                if tool_blocks:
                    output["tool_calls"] = [
                        {
                            "id": block["id"],
                            "type": "function",
                            "function": {"name": block["name"], "arguments": block["input_json"]},
                        }
                        for block in (tool_blocks[i] for i in sorted(tool_blocks))
                    ]

                yield TaskEvent(
                    event="completed",
                    job_id=job_id,
                    outputs=[output],
                ).to_ndjson()

            except asyncio.CancelledError:
                yield TaskEvent(
                    event="cancelled",
                    job_id=job_id,
                    outputs=[{"role": "assistant", "content": "", "cancelled": True}],
                ).to_ndjson()
            except Exception as e:
                self.logger.error(f"Error during inference: {str(e)}")
                yield TaskEvent(event="failed", job_id=job_id, message=str(e), retryable=retryable_for_exception(e)).to_ndjson()
            finally:
                if job_id:
                    await self.job_tracker.end_job(job_id)

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        return ok("Setup complete", provider=self.provider_id)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        """501, not a success: see the openai_compat twin.

        A hosted model cannot be fetched through this worker, so `ok("Not
        applicable")` reported a download that never happened. `direct_url`
        answers the identical situation the same way.
        """
        return failed(
            "LLM workers do not manage model files directly. "
            "Add the model through Anthropic instead.",
            code=501,
            provider=self.provider_id,
        )

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        fallback = [
            "claude-sonnet-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-haiku-20240307",
            "claude-3-opus-20240229",
        ]
        if not self.api_key:
            return files_response(
                [{"path": m, "name": m} for m in fallback],
                message="ANTHROPIC_API_KEY not set; returning the known model list",
                provider=self.provider_id,
            )
        try:
            client = await get_http_client().get_client()
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            if not models:
                models = fallback
            return files_response(
                [{"path": m, "name": m} for m in sorted(models)],
                provider=self.provider_id,
            )
        except Exception as e:
            self.logger.warning(f"Failed to list models from Anthropic: {e}")
            return files_response(
                [{"path": m, "name": m} for m in fallback],
                message="Failed to list models from Anthropic; returning the known model list",
                provider=self.provider_id,
            )

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        return failed("Model deletion not applicable for LLM workers.", code=404, provider=self.provider_id)

    async def get_file(self, path: str):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not supported")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        return failed("Not supported", code=404, provider=self.provider_id)

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        return failed("Not supported", code=404, provider=self.provider_id)

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return ok("Not applicable", provider=self.provider_id)

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        return ok("Not applicable", provider=self.provider_id)

    async def validate_all_models(self) -> Dict[str, Any]:
        return ok("Not applicable", provider=self.provider_id)

    async def get_object_info(self) -> Dict[str, Any]:
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
        return ok("Not applicable", provider=self.provider_id)
