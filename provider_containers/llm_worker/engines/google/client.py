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


class GoogleProviderClient(BaseProviderClient):
    """
    Provider Client for LLM generation via Google Gemini API.
    """

    def __init__(self, provider_id: str, runtime_config: Dict[str, Any]):
        super().__init__(provider_id=provider_id, runtime_config=runtime_config)
        self.logger = logging.getLogger("provider_core.engines.google")
        self.api_key = os.environ.get("GOOGLE_API_KEY", "")

    async def get_health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "provider_id": self.provider_id,
            "engine": "google",
        }

    async def get_info(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "google",
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

                # Gemini format expects {"role": "user"|"model", "parts": [{"text": "..."}]}
                # system instructions are sent separately.
                system_prompt = ""
                contents = []
                for m in raw_messages:
                    role = m.get("role")
                    if role == "system":
                        content = m.get("content", "")
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    system_prompt += block.get("text", "") + "\n"
                        elif isinstance(content, str):
                            system_prompt += content + "\n"
                    else:
                        content = m.get("content", "")
                        if isinstance(content, list):
                            content = " ".join(
                                b.get("text", "") for b in content
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                        g_role = "model" if role == "assistant" else "user"
                        contents.append({
                            "role": g_role,
                            "parts": [{"text": content}]
                        })

                model_id = (request.model or workflow.get("model") or "gemini-1.5-flash")

                payload = {
                    "contents": contents,
                }

                if system_prompt:
                    payload["systemInstruction"] = {
                        "role": "user",
                        "parts": [{"text": system_prompt.strip()}]
                    }

                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:streamGenerateContent?alt=sse&key={self.api_key}"

                headers = {
                    "Content-Type": "application/json"
                }

                timeout = request.timeout_seconds or 120.0
                client = await get_http_client().get_client()

                async def check_cancel():
                    return job_id and await self.job_tracker.is_cancelled(job_id)

                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                ) as response:
                    response.raise_for_status()

                    full_content = ""

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
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
                                candidates = data.get("candidates", [])
                                if candidates:
                                    content_parts = candidates[0].get("content", {}).get("parts", [])
                                    if content_parts:
                                        text = content_parts[0].get("text", "")
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
        fallback = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
        if not self.api_key:
            return {"files": [{"path": m, "name": m} for m in fallback]}
        try:
            client = await get_http_client().get_client()
            resp = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}",
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("models", []):
                name = m.get("name", "")
                if name.startswith("models/"):
                    name = name[7:]
                supported = m.get("supportedGenerationMethods", [])
                if "generateContent" in supported:
                    models.append(name)
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
