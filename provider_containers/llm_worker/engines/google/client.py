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


def _parse_json(value: Any) -> Any:
    """Best-effort parse of a JSON string; returns raw value on failure."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def translate_tools(tools: Any) -> list[dict[str, Any]]:
    """Translate OpenAI-style tool definitions into Gemini tools format."""
    if not tools:
        return []
    declarations = []
    for tool in tools:
        fn = tool.get("function", {}) if isinstance(tool, dict) else {}
        declarations.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", "") or "",
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return [{"functionDeclarations": declarations}]


def translate_messages(raw_messages: Any) -> tuple[list[dict[str, Any]], str]:
    """Translate OpenAI-style messages into Gemini ``contents``.

    Assistant messages carrying ``tool_calls`` become ``functionCall`` parts;
    ``role == "tool"`` results become ``functionResponse`` parts on a user turn.
    Returns ``(contents, system_prompt)``.
    """
    system_prompt = ""
    contents: list[dict[str, Any]] = []
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
            continue

        if role == "assistant":
            content = m.get("content", "")
            parts = []
            if isinstance(content, str) and content:
                parts.append({"text": content})
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                        parts.append({"text": block["text"]})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                args = _parse_json(fn.get("arguments"))
                if not isinstance(args, dict):
                    args = {"value": args}
                parts.append({
                    "functionCall": {"name": fn.get("name", ""), "args": args},
                })
            contents.append({"role": "model", "parts": parts})
            continue

        if role == "tool":
            parsed = _parse_json(m.get("content", ""))
            response = parsed if isinstance(parsed, dict) else {"result": str(parsed)}
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {"name": m.get("name", ""), "response": response},
                }],
            })
            continue

        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        g_role = "model" if role == "assistant" else "user"
        contents.append({"role": g_role, "parts": [{"text": content}]})
    return contents, system_prompt


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
                tools = request.tools or workflow.get("tools")

                # Gemini format expects {"role": "user"|"model", "parts": [{"text": "..."}]}
                # system instructions are sent separately.
                contents, system_prompt = translate_messages(raw_messages)

                model_id = (request.model or workflow.get("model") or "gemini-1.5-flash")

                payload = {
                    "contents": contents,
                }
                if tools:
                    payload["tools"] = translate_tools(tools)

                generation_config: dict = {}
                if request.temperature is not None:
                    generation_config["temperature"] = request.temperature
                if request.top_p is not None:
                    generation_config["topP"] = request.top_p
                if request.max_output_tokens is not None:
                    generation_config["maxOutputTokens"] = request.max_output_tokens
                if request.frequency_penalty is not None:
                    generation_config["frequencyPenalty"] = request.frequency_penalty
                if request.presence_penalty is not None:
                    generation_config["presencePenalty"] = request.presence_penalty
                if generation_config:
                    payload["generationConfig"] = generation_config

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

                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                ) as response:
                    response.raise_for_status()

                    full_content = ""
                    tool_calls = []

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
                                    for part in content_parts or []:
                                        text = part.get("text", "")
                                        if text:
                                            full_content += text
                                            yield TaskEvent(
                                                event="delta",
                                                job_id=job_id,
                                                text=text,
                                            ).to_ndjson()
                                        function_call = part.get("functionCall")
                                        if function_call:
                                            name = function_call.get("name", "")
                                            tool_calls.append({
                                                "id": name,
                                                "type": "function",
                                                "function": {
                                                    "name": name,
                                                    "arguments": json.dumps(function_call.get("args") or {}),
                                                },
                                            })
                            except json.JSONDecodeError:
                                pass

                output = {"role": "assistant", "content": full_content}
                if tool_calls:
                    output["tool_calls"] = tool_calls

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
