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
from provider_core.sse import iter_sse_data, parse_sse_json


# The backend's `_check_provider_health` (services/load_balancer.py) counts any
# provider that answers within a couple of seconds, so the probe has to be
# tighter than that or a dead endpoint is still counted as a usable target.
# Each engine keeps its own copy and they are kept in step by hand — the drift
# `provider_core/http_client.py` should eventually own.
HEALTH_PROBE_TIMEOUT = float(os.getenv("GOOGLE_HEALTH_PROBE_TIMEOUT", "1.5"))


# The Gemini API accepts the key as an `x-goog-api-key` header, which is what
# Google's own API-key guidance recommends; the `?key=` query form is the
# fallback they document for clients that cannot set headers. The key used to be
# in the query string, and a query string reaches proxy logs, httpx exception
# text (`raise_for_status` embeds the URL) and — because both error paths put
# `str(e)` into a TaskEvent(message=...) that is streamed to the backend and
# persisted on the job — the job record. See GOOGLE_API_KEY docs.
GOOGLE_API_KEY_HEADER = "x-goog-api-key"
GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def redact_api_key(text: str, secret: str) -> str:
    """Replace the key with a marker anywhere it appears in `text`.

    Defence in depth for the paths where a key could still reach a message: a
    reverse proxy echoing the request line back, or a deployment that predates
    the header change. `TaskEvent(message=...)` is persisted on the job, so
    anything that ends up in a message ends up in the database.
    """
    if not secret:
        return text
    return text.replace(secret, "***REDACTED***")


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
        """Probe the Gemini `GET /v1beta/models` instead of asserting health.

        This returned a hardcoded `{"status": "healthy"}` without touching the
        network, so a provider with no `GOOGLE_API_KEY` — or one pointed at a
        dead network — was counted by the backend's `_check_provider_health`
        (`services/load_balancer.py`) as a usable target and dispatched paid
        LLM jobs at it. Every one failed, and every one was marked
        `retryable=True`, so the balancer re-dispatched across the whole pool.

        `GET /models` is free and is the same endpoint `list_models` already
        calls. The key goes in the `x-goog-api-key` **header**, not the query
        string: a query string reaches proxy logs and httpx exception text, and
        this module's failure path puts `str(e)` into a TaskEvent that is
        streamed to the backend and persisted on the job. That is the exact leak
        `redact_api_key` exists to contain, and the reason the header form is
        used here too.
        """
        if not self.api_key:
            return llm_unhealthy(
                "google", self.provider_id, "no API key configured (GOOGLE_API_KEY)"
            )
        client = await get_http_client().get_client()
        try:
            response = await client.get(
                f"{GOOGLE_API_BASE}/models",
                headers={GOOGLE_API_KEY_HEADER: self.api_key},
                timeout=HEALTH_PROBE_TIMEOUT,
            )
        except Exception as exc:
            # Never let the raw exception text through: httpx embeds the URL,
            # and a URL that carried the key would be persisted on the job.
            return llm_unhealthy(
                "google",
                self.provider_id,
                f"GET /models failed: {type(exc).__name__}",
                retryable=True,
            )
        if response.status_code >= 400:
            return llm_unhealthy(
                "google",
                self.provider_id,
                f"GET /models returned HTTP {response.status_code}",
                retryable=retryable_for_status(response.status_code),
            )
        return llm_healthy("google", self.provider_id)

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

                url = f"{GOOGLE_API_BASE}/models/{model_id}:streamGenerateContent?alt=sse"

                headers = {
                    "Content-Type": "application/json",
                    GOOGLE_API_KEY_HEADER: self.api_key,
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

                    async def _cancelled() -> str:
                        return TaskEvent(
                            event="cancelled",
                            job_id=job_id,
                            outputs=[{"role": "assistant", "content": full_content, "cancelled": True}],
                        ).to_ndjson()

                    # Shared framing + cancellation probe (`provider_core/sse.py`).
                    async for data_str in iter_sse_data(
                        response,
                        job_id=job_id,
                        job_tracker=self.job_tracker,
                        on_cancelled=_cancelled,
                    ):
                        data = parse_sse_json(data_str)
                        if data is None:
                            continue
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
                message = redact_api_key(str(e), self.api_key)
                self.logger.error(f"Error during inference: {message}")
                yield TaskEvent(event="failed", job_id=job_id, message=message, retryable=retryable_for_exception(e)).to_ndjson()
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
            "Add the model through Google instead.",
            code=501,
            provider=self.provider_id,
        )

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        # An empty list on every failure, and never a fabricated one.
        #
        # This returned five hardcoded model ids whenever the call failed — or
        # succeeded with nothing in it. `backend_v2/api/routes/world_vault/
        # llm_config.py` reads `data.get("files")` and falls back to
        # `[{"id": "default"}]` only *when the list comes back empty*, so the
        # fabricated list suppressed the backend's own honest fallback: a revoked
        # Google key produced five selectable model ids, every one of which
        # failed on the next turn. The two engines that returned `[]` behaved
        # better than the two that invented an answer, so all four agree on `[]`.
        #
        # A missing key is included. "No key" and "could not reach the API" are
        # the same thing to the caller — nothing can be served either way — and
        # promising five models that cannot answer is the same defect as a
        # revoked key.
        if not self.api_key:
            return files_response(
                [],
                message="GOOGLE_API_KEY not set; no models to list",
                provider=self.provider_id,
            )
        try:
            client = await get_http_client().get_client()
            resp = await client.get(
                f"{GOOGLE_API_BASE}/models",
                headers={GOOGLE_API_KEY_HEADER: self.api_key},
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
            # An empty successful response stays empty — including the case where
            # the account has models but none support `generateContent`. It used to
            # be replaced by the fallback list, which is indistinguishable from a
            # revoked key at the caller's end; see the note on this method.
            return files_response(
                [{"path": m, "name": m} for m in sorted(models)],
                provider=self.provider_id,
            )
        except Exception as e:
            self.logger.warning(
                "Failed to list models from Google: %s", redact_api_key(str(e), self.api_key)
            )
            return files_response(
                [],
                message=(
                    "Failed to list models from Google: "
                    f"{redact_api_key(str(e), self.api_key)}"
                ),
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
