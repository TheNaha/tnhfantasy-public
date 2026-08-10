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


class AnthropicProviderClient(BaseProviderClient):
    """
    Provider Client for LLM generation via Anthropic endpoints (Claude).
    """

    def __init__(self, provider_id: str, runtime_config: Dict[str, Any]):
        super().__init__(provider_id=provider_id, runtime_config=runtime_config)
        self.logger = logging.getLogger("provider_core.engines.anthropic")
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    async def get_health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "provider_id": self.provider_id,
            "engine": "anthropic",
        }

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

                # Extract system prompt if any
                system_prompt = ""
                messages = []
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
                    else:
                        messages.append(m)

                model_id = (request.model or workflow.get("model") or "claude-3-haiku-20240307")

                payload = {
                    "model": model_id,
                    "messages": messages,
                    "stream": True,
                    "max_tokens": 4096,
                }
                if request.temperature is not None:
                    payload["temperature"] = request.temperature
                if system_prompt:
                    payload["system"] = system_prompt.strip()

                headers = {
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }

                timeout = request.timeout_seconds or 120.0
                client = await get_http_client().get_client()

                async def check_cancel():
                    return job_id and await self.job_tracker.is_cancelled(job_id)

                async with client.stream(
                    "POST",
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                ) as response:
                    response.raise_for_status()

                    full_content = ""

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

                                if type_ == "content_block_delta":
                                    delta = data.get("delta", {})
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
                yield TaskEvent(event="failed", job_id=job_id, message=str(e), retryable=True).to_ndjson()
            finally:
                if job_id:
                    await self.job_tracker.end_job(job_id)

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        return build_status_response("success", "Setup complete", provider=self.provider_id)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        fallback = [
            "claude-sonnet-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-haiku-20240307",
            "claude-3-opus-20240229",
        ]
        if not self.api_key:
            return {"files": [{"path": m, "name": m} for m in fallback]}
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
            return {"files": [{"path": m, "name": m} for m in sorted(models)]}
        except Exception:
            return {"files": [{"path": m, "name": m} for m in fallback]}

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        return build_error_response("Model deletion not applicable for LLM workers.", retryable=False, code=404)

    async def get_file(self, path: str):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not supported")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        return build_error_response("Not supported", retryable=False, code=404)

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        return build_error_response("Not supported", retryable=False, code=404)

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)

    async def validate_all_models(self) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)

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
        return build_status_response("success", "Not applicable", provider=self.provider_id)
