"""
In-Process LLM Compute Engines.

Provides direct compute execution for LLM generation:
- OpenAICompatLLMEngine: Direct streaming client for OpenAI-compatible APIs (Ollama, OpenRouter, vLLM, LM Studio)
- AnthropicLLMEngine: Direct streaming client for Anthropic Messages API (Claude)
- GoogleLLMEngine: Direct streaming client for Google Gemini API
- ModalVLLMEngine: Serverless vLLM execution directly on Modal cloud
"""

import asyncio
import base64
import json
import os
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from infrastructure.logging import get_logger
from services.engines.base import (
    EngineAuthError,
    InProcessEngine,
    clamp_timeout,
    get_file_size_cap,
    get_upload_size_cap,
    is_auth_error,
    iter_sse_data,
    normalize_validation_result,
    parse_sse_json,
    retryable_for_exception,
    retryable_for_status,
)

logger = get_logger("llm_engine")

try:
    import modal
    HAS_MODAL = True
except ImportError:
    modal = None  # type: ignore
    HAS_MODAL = False


def _health_probe_timeout(env_name: str, default: float = 1.5) -> float:
    """Read a per-engine health-probe timeout env var with a default.

    Mirrors the old container clients (each read its own
    ``*_HEALTH_PROBE_TIMEOUT`` env var, default 1.5s). Read at call time so
    tests can monkeypatch the environment.
    """
    try:
        return float(os.getenv(env_name, str(default)))
    except (TypeError, ValueError):
        return default


def _is_modal_connection_error(exc: BaseException) -> bool:
    """True when ``exc`` is a Modal client connection error."""
    if HAS_MODAL and modal is not None:
        conn_err = getattr(getattr(modal, "exception", None), "ConnectionError", None)
        if isinstance(conn_err, type) and isinstance(exc, conn_err):
            return True
    return type(exc).__name__ == "ConnectionError" and "modal" in (type(exc).__module__ or "").lower()


def _parse_json_loose(value: Any) -> Any:
    """Best-effort parse of a JSON string; returns raw value on failure."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def translate_tools_anthropic(tools: Any) -> List[Dict[str, Any]]:
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


def translate_messages_anthropic(raw_messages: Any) -> tuple[List[Dict[str, Any]], str]:
    """Translate OpenAI-style messages into Anthropic message format.

    Assistant ``tool_calls`` become ``tool_use`` blocks; ``role == "tool"``
    results become ``tool_result`` blocks on a user turn. System turns are
    folded into a separate system prompt string.
    """
    system_prompt = ""
    messages: List[Dict[str, Any]] = []
    for m in raw_messages or []:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "system":
            content = m.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
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
                        "id": tc.get("id", "") if isinstance(tc, dict) else "",
                        "name": fn.get("name", ""),
                        "input": _parse_json_loose(fn.get("arguments")),
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


def translate_tools_google(tools: Any) -> List[Dict[str, Any]]:
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


def translate_messages_google(raw_messages: Any) -> tuple[List[Dict[str, Any]], str]:
    """Translate OpenAI-style messages into Gemini ``contents``.

    Assistant ``tool_calls`` become ``functionCall`` parts; ``role == "tool"``
    results become ``functionResponse`` parts. Returns ``(contents, system_prompt)``.
    """
    system_prompt = ""
    contents: List[Dict[str, Any]] = []
    for m in raw_messages or []:
        if not isinstance(m, dict):
            continue
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
            parts: List[Dict[str, Any]] = []
            if isinstance(content, str) and content:
                parts.append({"text": content})
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                        parts.append({"text": block["text"]})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                args = _parse_json_loose(fn.get("arguments"))
                if not isinstance(args, dict):
                    args = {"value": args}
                parts.append({
                    "functionCall": {"name": fn.get("name", ""), "args": args},
                })
            contents.append({"role": "model", "parts": parts})
            continue
        if role == "tool":
            parsed = _parse_json_loose(m.get("content", ""))
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


def redact_api_key(text: str, secret: str) -> str:
    """Replace the key with a marker anywhere it appears in ``text``.

    Gemini error paths put ``str(e)`` into TaskEvents persisted on the job;
    httpx embeds the URL in exception text, so a key that ever reached a URL
    would land in the database. Defence in depth alongside the header form.
    """
    if not secret:
        return text
    return text.replace(secret, "***REDACTED***")


class OpenAICompatLLMEngine(InProcessEngine):
    """In-process execution engine for OpenAI-compatible endpoints."""

    def __init__(
        self,
        provider_id: str,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: str = "default-model",
        base_url: Optional[str] = None,
    ):
        super().__init__(provider_id)
        endpoint = base_url or api_base or "http://localhost:11434/v1"
        self.api_base = endpoint.rstrip("/")
        self.base_url = self.api_base
        self.api_key = (api_key or "").strip()
        self.default_model = default_model
        self._http: Optional[httpx.AsyncClient] = None


    def get_http_client(self) -> httpx.AsyncClient:
        """Lazily initialize or retrieve the shared httpx.AsyncClient."""
        if self._http is None or self._http.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._http = httpx.AsyncClient(
                base_url=self.api_base,
                timeout=120.0,
                headers=headers,
            )
        return self._http

    async def close(self) -> None:
        """Close HTTP connections."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def get_info(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "openai_compat",
            "engine": "openai_compat",
            "api_base": self.api_base,
            "default_model": self.default_model,
        }

    async def check_health(self) -> Dict[str, Any]:
        """Probe GET /models on the OpenAI-compatible endpoint."""
        t0 = time.monotonic()
        if not self.api_key:
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 2),
                "engine": "openai_compat",
                "api_base": self.api_base,
                "error": "no API key configured (OPENAI_API_KEY)",
            }
        client = self.get_http_client()
        try:
            resp = await client.get(
                "/models",
                timeout=_health_probe_timeout(
                    "OPENAI_COMPAT_HEALTH_PROBE_TIMEOUT", _LLM_HEALTH_PROBE_TIMEOUT
                ),
            )
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            if resp.status_code == 200:
                return {
                    "status": "healthy",
                    "provider_id": self.provider_id,
                    "ready": True,
                    "latency_ms": latency_ms,
                    "engine": "openai_compat",
                    "api_base": self.api_base,
                }
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": latency_ms,
                "engine": "openai_compat",
                "error": f"HTTP {resp.status_code}",
                "retryable": resp.status_code in (408, 429) or resp.status_code >= 500,
            }
        except Exception as exc:
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            logger.warning("llm_health_probe_failed", provider_id=self.provider_id, error=str(exc))
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": latency_ms,
                "engine": "openai_compat",
                "error": str(exc),
                "retryable": True,
            }

    async def list_models(self, directory: str = "") -> List[Dict[str, Any]]:
        """List models available on the upstream endpoint."""
        client = self.get_http_client()
        try:
            resp = await client.get("/models", timeout=10.0)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                return [{"name": m.get("id"), "id": m.get("id"), "type": "llm"} for m in data if m.get("id")]
            return []
        except Exception as exc:
            logger.warning("llm_list_models_failed", provider_id=self.provider_id, error=str(exc))
            return []

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        raise NotImplementedError("File streaming is not applicable for API-based LLM endpoints")

    async def delete_file(self, path: str) -> bool:
        return False

    async def inference(
        self,
        workflow: Dict[str, Any],
        job_id: Optional[str] = None,
        use_snapshot: bool = True,
        timeout: float = 120.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream chat completions SSE from OpenAI-compatible endpoint, yielding canonical TaskEvents.
        """
        messages = workflow.get("messages") or []
        tools = workflow.get("tools")
        model = workflow.get("model") or self.default_model

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        for param in ("temperature", "top_p", "frequency_penalty", "presence_penalty"):
            if workflow.get(param) is not None:
                payload[param] = workflow[param]
        if workflow.get("max_output_tokens") is not None:
            payload["max_tokens"] = workflow["max_output_tokens"]

        timeout = clamp_timeout(timeout, default=120.0)
        client = self.get_http_client()
        logger.info("llm_inference_start", provider_id=self.provider_id, job_id=job_id, model=model)

        yield {"event": "started", "job_id": job_id, "provider_id": self.provider_id}

        full_content = ""
        tool_calls: List[Dict[str, Any]] = []

        try:
            async with client.stream(
                "POST",
                "/chat/completions",
                json=payload,
                timeout=timeout,
            ) as response:
                if response.status_code != 200:
                    err_text = await response.aread()
                    err_msg = f"LLM upstream returned {response.status_code}: {err_text.decode('utf-8', 'ignore')}"
                    logger.error("llm_inference_rejected", provider_id=self.provider_id, error=err_msg)
                    yield {"event": "failed", "job_id": job_id, "message": err_msg, "retryable": retryable_for_status(response.status_code)}
                    return

                async for data_str in iter_sse_data(response.aiter_lines()):
                    if job_id and job_id in self._cancelled_jobs:
                        self._cancelled_jobs.discard(job_id)
                        yield {
                            "event": "cancelled",
                            "job_id": job_id,
                            "message": "Job cancelled by user",
                            "outputs": [{
                                "role": "assistant",
                                "content": full_content,
                                "cancelled": True,
                            }],
                        }
                        return
                    data = parse_sse_json(data_str)
                    if data is None:
                        continue

                    choices = data.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    delta_tool_calls = delta.get("tool_calls")

                    if content:
                        full_content += content
                        yield {"event": "delta", "job_id": job_id, "text": content}

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

            output: Dict[str, Any] = {"role": "assistant", "content": full_content}
            if tool_calls:
                output["tool_calls"] = tool_calls

            yield {
                "event": "completed",
                "job_id": job_id,
                "outputs": [output],
            }

        except TimeoutError:
            logger.warning("llm_inference_timeout", provider_id=self.provider_id, job_id=job_id)
            yield {"event": "failed", "job_id": job_id, "message": f"LLM generation timed out after {int(timeout)}s", "retryable": True}
        except httpx.TimeoutException:
            logger.warning("llm_inference_timeout", provider_id=self.provider_id, job_id=job_id)
            yield {"event": "failed", "job_id": job_id, "message": f"LLM generation timed out after {int(timeout)}s", "retryable": True}
        except httpx.HTTPStatusError as exc:
            logger.exception("llm_inference_error", provider_id=self.provider_id, job_id=job_id, error=str(exc))
            yield {"event": "failed", "job_id": job_id, "message": f"LLM generation error: {exc}", "retryable": retryable_for_exception(exc)}
        except Exception as exc:
            logger.exception("llm_inference_error", provider_id=self.provider_id, job_id=job_id, error=str(exc))
            yield {"event": "failed", "job_id": job_id, "message": f"LLM generation error: {exc}", "retryable": retryable_for_exception(exc)}


class ModalVLLMEngine(InProcessEngine):
    """In-process execution engine for serverless vLLM on Modal cloud."""

    #: Owns the ``models/`` tree on the Modal volume, so the in-process
    #: reconciliation runner drives downloads/validation through it — same
    #: role as the legacy llm_worker modal client (download_model,
    #: validate_models, setup_models, run_reconciliation).
    manages_model_files = True

    #: The vLLM Modal app only stores one tree; the generic reconciler fans
    #: out over MODEL_DIRECTORIES, so non-models dirs answer [] below.
    _MODEL_DIRS = ("models",)

    _GET_FILE_TIMEOUT_SECONDS = float(os.getenv("MODAL_GET_FILE_TIMEOUT_SECONDS", "3600"))
    _RANGE_CHUNK_BYTES = 4 * 1024 * 1024

    def __init__(
        self,
        provider_id: str,
        token_id: str,
        token_secret: str,
        app_name: str = "vllm-modal-stack",
        cls_name: str = "VLLMEngine",
    ):
        super().__init__(provider_id)
        self.token_id = token_id.strip()
        self.token_secret = token_secret.strip()
        # MODAL_LLM_APP_NAME wins; MODAL_APP_NAME (the container-era variable)
        # is honoured as a fallback so existing hosts keep working.
        self.app_name = (
            app_name
            or os.getenv("MODAL_LLM_APP_NAME")
            or os.getenv("MODAL_APP_NAME")
            or "vllm-modal-stack"
        )
        self.cls_name = cls_name or os.getenv("MODAL_LLM_CLASS", "VLLMEngine")
        self._client: Optional[Any] = None
        self._lock = asyncio.Lock()


    async def get_client_async(self) -> Any:
        if not HAS_MODAL or modal is None:
            raise RuntimeError("modal package is required for ModalVLLMEngine")
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    if hasattr(modal.Client.from_credentials, "aio"):
                        self._client = await modal.Client.from_credentials.aio(
                            token_id=self.token_id,
                            token_secret=self.token_secret,
                        )
                    else:
                        self._client = modal.Client.from_credentials(
                            token_id=self.token_id,
                            token_secret=self.token_secret,
                        )
        return self._client

    async def close(self) -> None:
        """Release the cached Modal client."""
        self._client = None

    async def check_health(self) -> Dict[str, Any]:
        # Config-only parity with container llm modal/client.py:86-124 — a
        # probe bills GPU time (VISION #4), so health only verifies config.
        # Missing app/token reads unhealthy non-retryable (config fault).
        t0 = time.monotonic()
        missing: list[str] = []
        if not self.app_name:
            missing.append("MODAL_LLM_APP_NAME")
        if not (self.token_id and self.token_secret):
            missing.append("MODAL_TOKEN_ID/SECRET")
        latency_ms = round((time.monotonic() - t0) * 1000, 2)
        if missing:
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": latency_ms,
                "engine": "modal_vllm",
                "error": f"provider is not configured (missing: {', '.join(missing)})",
                "retryable": False,
            }
        return {
            "status": "healthy",
            "provider_id": self.provider_id,
            "ready": True,
            "latency_ms": latency_ms,
            "engine": "modal_vllm",
            "app_name": self.app_name,
        }

    async def get_info(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "modal_vllm",
            "engine": "modal_vllm",
            "app_name": self.app_name,
            "cls_name": self.cls_name,
        }

    async def list_models(self, directory: str = "") -> List[Dict[str, Any]]:
        """List models in a directory directly from the Modal volume.

        Raises on failure instead of returning []: reconciliation and the
        maintenance scan both catch per directory, and an empty success is
        exactly the clean-sweep misread the container probes fixed by
        raising on non-200. Directories outside the vLLM ``models/`` tree
        legitimately answer [] (the generic reconciler fans out over the
        image MODEL_DIRECTORIES).
        """
        if directory and directory not in self._MODEL_DIRS and not directory.startswith("models/"):
            return []
        if not HAS_MODAL or modal is None:
            raise RuntimeError("modal package is required for ModalVLLMEngine")
        try:
            client = await self.get_client_async()
            func = modal.Function.from_name(
                self.app_name, "list_models_with_metadata", client=client
            )
            res = await asyncio.wait_for(func.remote.aio(directory), timeout=3600.0)
            return res if isinstance(res, list) else []
        except EngineAuthError:
            raise
        except Exception as exc:
            logger.error(
                "modal_vllm_list_models_failed",
                provider_id=self.provider_id,
                error=str(exc),
            )
            if is_auth_error(exc):
                raise EngineAuthError(
                    f"Modal vLLM rejected credentials for /list-models ({directory!r}): {exc}",
                ) from exc
            raise RuntimeError(f"Modal vLLM list-models failed for {directory!r}: {exc}") from exc

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        """Stream a volume file in ranged slices via FileStorage.

        Mirrors the legacy llm modal client's ranged get_file and the image
        ModalEngine: existence is probed before streaming (missing raises
        FileNotFoundError), over-cap fails fast, whole stream deadline-bound.
        """
        if not HAS_MODAL or modal is None:
            raise RuntimeError("modal package is required for ModalVLLMEngine")
        client = await self.get_client_async()
        FileStorage = modal.Cls.from_name(self.app_name, "FileStorage", client=client)
        storage = FileStorage()
        total_size = await asyncio.wait_for(
            storage.file_size.remote.aio(path),
            timeout=self._GET_FILE_TIMEOUT_SECONDS,
        )
        if total_size is None or total_size < 0:
            raise FileNotFoundError(f"File not found on Modal volume: {path}")
        max_bytes = get_file_size_cap()
        if max_bytes and total_size > max_bytes:
            raise RuntimeError(f"File exceeds the {max_bytes} byte get-file limit: {path}")
        async with asyncio.timeout(self._GET_FILE_TIMEOUT_SECONDS):
            offset = 0
            while offset < total_size:
                chunk = await storage.read_file_range.remote.aio(path, offset, self._RANGE_CHUNK_BYTES)
                if not chunk:
                    break
                offset += len(chunk)
                yield chunk

    async def delete_file(self, path: str) -> bool:
        if not HAS_MODAL or modal is None:
            return False
        try:
            client = await self.get_client_async()
            FileStorage = modal.Cls.from_name(self.app_name, "FileStorage", client=client)
            storage = FileStorage()
            return bool(await storage.delete_file.remote.aio(path))
        except Exception as exc:
            logger.warning("modal_vllm_delete_failed", provider_id=self.provider_id, path=path, error=str(exc))
            return False

    def download_token_for_url(self, url: str) -> Optional[str]:
        lowered = (url or "").lower()
        if "huggingface.co" in lowered:
            return os.getenv("HF_TOKEN", "") or None
        if "civitai.com" in lowered or "civitai.red" in lowered:
            return os.getenv("CIVITAI_TOKEN", "") or None
        return None

    async def download_file(
        self,
        download_url: str,
        storage_path: str,
        token: Optional[str] = None,
        timeout: float = 3600.0,
        preview_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Download one model into the Modal volume, awaiting completion.

        Mirrors ModalEngine.download_file (awaited remote, error dict raises)
        instead of the container's spawn-and-report-queued: the in-process
        reconciler runs downloads under a semaphore in a background task, so
        awaiting keeps success/failure attribution exact.
        """
        if not HAS_MODAL or modal is None:
            raise RuntimeError("modal package is required for ModalVLLMEngine")
        client = await self.get_client_async()
        func = modal.Function.from_name(self.app_name, "download_model", client=client)
        result = await asyncio.wait_for(
            func.remote.aio(
                url=download_url,
                path=storage_path,
                token=token if token is not None else self.download_token_for_url(download_url),
                preview_url=preview_url,
                metadata=metadata,
            ),
            timeout=timeout,
        )
        if isinstance(result, dict) and result.get("status") == "error":
            raise RuntimeError(result.get("message", "Download failed"))
        return result if isinstance(result, dict) else {"status": "ok"}

    def _vllm_dirs(self, directories: Optional[List[str]]) -> List[str]:
        if not directories:
            return list(self._MODEL_DIRS)
        kept = [d for d in directories if d in self._MODEL_DIRS or d.startswith("models/")]
        return kept or list(self._MODEL_DIRS)

    async def validate_models(
        self, directories: List[str], delete_invalid: bool = False
    ) -> Dict[str, Any]:
        """Validate model integrity on the Modal volume (mirrors the worker)."""
        if not HAS_MODAL or modal is None:
            raise RuntimeError("modal package is required for ModalVLLMEngine")
        target = self._vllm_dirs(directories)
        client = await self.get_client_async()
        try:
            func = modal.Function.from_name(self.app_name, "validate_models", client=client)
            result = await asyncio.wait_for(
                func.remote.aio(target, delete_invalid),
                timeout=300.0,
            )
            return normalize_validation_result(result, target)
        except EngineAuthError:
            raise
        except Exception as exc:
            logger.error("modal_vllm_validate_failed", provider_id=self.provider_id, error=str(exc))
            if is_auth_error(exc):
                raise EngineAuthError(
                    f"Modal vLLM rejected credentials for /validate-models: {exc}",
                ) from exc
            raise

    async def validate_all_models(
        self,
        directories: Optional[List[str]] = None,
        delete_invalid: bool = False,
    ) -> Dict[str, Any]:
        """Single-call full-tree validation for reconciliation step 0."""
        return await self.validate_models(self._vllm_dirs(directories), delete_invalid)

    async def setup_models(self) -> bool:
        """Queue the Modal app's directory setup (mirrors the worker's spawn)."""
        if not HAS_MODAL or modal is None:
            return False
        try:
            client = await self.get_client_async()
            func = modal.Function.from_name(self.app_name, "setup_models", client=client)
            await func.spawn.aio()
            return True
        except Exception as exc:
            logger.error("modal_vllm_setup_failed", provider_id=self.provider_id, error=str(exc))
            return False

    async def upload_file(self, filename: str, content_base64: str, directory: str = "") -> bool:
        if not HAS_MODAL or modal is None:
            return False
        try:
            content = base64.b64decode(content_base64)
            cap = get_upload_size_cap()
            if cap and len(content) > cap:
                logger.warning(
                    "modal_vllm_upload_over_cap",
                    provider_id=self.provider_id, path=filename, size=len(content), cap=cap,
                )
                return False
            client = await self.get_client_async()
            FileStorage = modal.Cls.from_name(self.app_name, "FileStorage", client=client)
            storage = FileStorage()
            path = f"{directory}/{filename}" if directory else filename
            await storage.put_file.remote.aio(path=path, content=content)
            return True
        except Exception as exc:
            logger.error("modal_vllm_upload_failed", provider_id=self.provider_id, path=filename, error=str(exc))
            return False

    async def get_object_info(self) -> Dict[str, Any]:
        return {"object_info": {}}

    async def get_storage_stats(self) -> Dict[str, Any]:
        if not HAS_MODAL or modal is None:
            return {"provider_id": self.provider_id, "total": 0, "by_directory": {}}
        try:
            entries = await self.list_models("models")
            return {"provider_id": self.provider_id, "total": len(entries), "by_directory": {"models": len(entries)}}
        except Exception as exc:
            logger.warning("modal_vllm_storage_stats_failed", provider_id=self.provider_id, error=str(exc))
            return {"provider_id": self.provider_id, "total": 0, "by_directory": {}, "error": str(exc)}

    def _retryable_for_remote_error(self, data: Dict[str, Any]) -> bool:
        """Classify a failure the REMOTE reported, mirroring old modal/client.py.

        An explicit ``retryable`` bool wins; then an HTTP status (either key);
        with neither the failure is permanent (False) — the opposite of a
        hardcoded True, which re-ran permanently-failing requests across every
        provider in the pool.
        """
        marker = data.get("retryable")
        if isinstance(marker, bool):
            return marker
        for key in ("status_code", "http_status"):
            status = data.get(key)
            if isinstance(status, int):
                return retryable_for_status(status)
        return False

    async def inference(
        self,
        workflow: Dict[str, Any],
        job_id: Optional[str] = None,
        use_snapshot: bool = True,
        timeout: float = 300.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        timeout = clamp_timeout(timeout, default=300.0)
        yield {"event": "started", "job_id": job_id, "provider_id": self.provider_id}
        full_content = ""
        try:
            client = await self.get_client_async()
            VLLMClass = modal.Cls.from_name(self.app_name, self.cls_name, client=client)
            instance = VLLMClass()

            # Remote signature is generate(model_id, messages, tools,
            # timeout_seconds, sampling) — see llm_worker/engines/modal/modal_app.py.
            # The workflow payload carries model/messages/tools plus flat sampling
            # keys (temperature/top_p/max_output_tokens/penalties); unpack them.
            model_id = workflow.get("model") or "default-model"
            messages = workflow.get("messages") or []
            tools = workflow.get("tools")
            sampling: Dict[str, Any] = {}
            for key in ("temperature", "top_p", "max_output_tokens",
                        "frequency_penalty", "presence_penalty"):
                if workflow.get(key) is not None:
                    sampling[key] = workflow[key]

            def _cancelled_event() -> Dict[str, Any]:
                return {
                    "event": "cancelled",
                    "job_id": job_id,
                    "message": "Job cancelled by user",
                    "outputs": [{
                        "role": "assistant",
                        "content": full_content,
                        "cancelled": True,
                    }],
                }

            async with asyncio.timeout(timeout):
                # Fetcher-task + queue + 2s poll parity with container llm modal
                # client (client.py:162-204) and image engines: cancel is observed
                # even mid-stall instead of parking until outer timeout.
                queue: asyncio.Queue = asyncio.Queue()

                async def _fetcher() -> None:
                    try:
                        async for _update in instance.generate.remote_gen.aio(
                            model_id, messages, tools, timeout, sampling or None
                        ):
                            if job_id and job_id in self._cancelled_jobs:
                                return
                            await queue.put(_update)
                        await queue.put(None)
                    except Exception as _exc:
                        await queue.put(_exc)

                _task = asyncio.create_task(_fetcher())
                try:
                    while True:
                        if job_id and job_id in self._cancelled_jobs:
                            self._cancelled_jobs.discard(job_id)
                            yield _cancelled_event()
                            return
                        try:
                            update = await asyncio.wait_for(queue.get(), timeout=2.0)
                        except asyncio.TimeoutError:
                            continue
                        if update is None:
                            break
                        if isinstance(update, Exception):
                            raise update

                        if isinstance(update, str):
                            try:
                                update = json.loads(update)
                            except (json.JSONDecodeError, TypeError):
                                yield {
                                    "event": "failed",
                                    "job_id": job_id,
                                    "message": f"Malformed remote event: {update}",
                                    "retryable": False,
                                }
                                return
                        if not isinstance(update, dict):
                            yield {
                                "event": "failed",
                                "job_id": job_id,
                                "message": f"Malformed remote event: {update}",
                                "retryable": False,
                            }
                            return
                        event_kind = update.get("event")
                        if event_kind == "delta":
                            text = update.get("text", "")
                            full_content += text
                            yield {"event": "delta", "job_id": job_id, "text": text}
                            continue
                        elif event_kind == "completed":
                            outputs = update.get("outputs") or [{"role": "assistant", "content": full_content}]
                            yield {"event": "completed", "job_id": job_id, "outputs": outputs}
                            return
                        elif event_kind == "failed":
                            retryable = update.get("retryable")
                            if retryable is None:
                                retryable = self._retryable_for_remote_error(update)
                            yield {
                                "event": "failed",
                                "job_id": job_id,
                                "message": update.get("message", "vLLM failed"),
                                "retryable": bool(retryable),
                            }
                            return
                        elif event_kind == "cancelled":
                            yield {
                                "event": "cancelled",
                                "job_id": job_id,
                                "message": update.get("message") or "Job cancelled by user",
                                "outputs": update.get("outputs") or [{
                                    "role": "assistant",
                                    "content": full_content,
                                    "cancelled": True,
                                }],
                            }
                            return
                        elif event_kind:
                            passthrough = dict(update)
                            passthrough.setdefault("job_id", job_id)
                            yield passthrough
                            continue

                        # Legacy {"type": ...} / {"status": ...} dialect from a
                        # remote deployed before the TaskEvent switch — translated
                        # locally so the backend always sees canonical events.
                        msg_type = update.get("type") or update.get("status")
                        if msg_type == "progress":
                            text = update.get("message") or update.get("text") or ""
                            full_content += text
                            yield {"event": "delta", "job_id": job_id, "text": text}
                        elif msg_type == "completed":
                            outputs = update.get("outputs")
                            first = (outputs or [{}])[0] if isinstance(outputs, list) else {}
                            cancelled = bool(update.get("cancelled")) or bool(
                                first.get("cancelled") if isinstance(first, dict) else False
                            )
                            if cancelled:
                                yield {
                                    "event": "cancelled",
                                    "job_id": job_id,
                                    "message": update.get("message") or "Job cancelled by user",
                                    "outputs": outputs,
                                }
                            else:
                                yield {"event": "completed", "job_id": job_id, "outputs": outputs}
                            return
                        elif msg_type == "error":
                            yield {
                                "event": "failed",
                                "job_id": job_id,
                                "message": update.get("message", "Unknown error"),
                                "retryable": self._retryable_for_remote_error(update),
                            }
                            return
                        else:
                            passthrough = dict(update)
                            passthrough.setdefault("job_id", job_id)
                            yield passthrough
                finally:
                    _task.cancel()
                    try:
                        await _task
                    except (asyncio.CancelledError, Exception):
                        pass

            # The remote generator ended without a terminal event. The old
            # llm modal client emitted nothing here, so the backend reducer
            # raised a retryable ProviderCallError; yielding completed would
            # commit a truncated answer to the chat as if it were whole.
            logger.error("modal_vllm_stream_truncated", provider_id=self.provider_id, job_id=job_id)
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": "Modal vLLM stream ended without a completed event",
                "retryable": True,
            }

        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("modal_vllm_inference_timeout", provider_id=self.provider_id, job_id=job_id)
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"Modal vLLM inference timed out after {int(timeout)}s",
                "retryable": True,
            }
        except Exception as exc:
            if _is_modal_connection_error(exc):
                logger.warning("modal_vllm_connection_error", provider_id=self.provider_id, job_id=job_id, error=str(exc))
                yield {
                    "event": "failed",
                    "job_id": job_id,
                    "message": f"Modal connection error: {exc}",
                    "retryable": True,
                }
            else:
                yield {"event": "failed", "job_id": job_id, "message": f"Modal vLLM error: {exc}", "retryable": retryable_for_exception(exc)}


ANTHROPIC_API_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GOOGLE_API_KEY_HEADER = "x-goog-api-key"
_LLM_HEALTH_PROBE_TIMEOUT = 1.5


class AnthropicLLMEngine(InProcessEngine):
    """In-process execution engine for the Anthropic Messages API (Claude).

    Wire parity with llm_worker/engines/anthropic/client.py: x-api-key +
    anthropic-version headers, system prompt split, tool translation, SSE
    event parsing (content_block_start/delta), free GET /v1/models health
    probe, empty-list-on-failure list_models.
    """

    def __init__(
        self,
        provider_id: str,
        api_key: Optional[str] = None,
        default_model: str = "claude-3-haiku-20240307",
    ):
        super().__init__(provider_id)
        self.api_key = (api_key or "").strip()
        self.default_model = default_model or "claude-3-haiku-20240307"
        self._http: Optional[httpx.AsyncClient] = None


    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def get_http_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=120.0)
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def get_info(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "anthropic",
            "engine": "anthropic",
            "default_model": self.default_model,
        }

    async def check_health(self) -> Dict[str, Any]:
        t0 = time.monotonic()
        if not self.api_key:
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 2),
                "engine": "anthropic",
                "error": "no API key configured (ANTHROPIC_API_KEY)",
            }
        try:
            resp = await self.get_http_client().get(
                f"{ANTHROPIC_API_BASE}/v1/models",
                headers={"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION},
                timeout=_health_probe_timeout(
                    "ANTHROPIC_HEALTH_PROBE_TIMEOUT", _LLM_HEALTH_PROBE_TIMEOUT
                ),
            )
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            if resp.status_code >= 400:
                return {
                    "status": "unhealthy",
                    "provider_id": self.provider_id,
                    "ready": False,
                    "latency_ms": latency_ms,
                    "engine": "anthropic",
                    "error": f"GET /v1/models returned HTTP {resp.status_code}",
                    "retryable": retryable_for_status(resp.status_code),
                }
            return {
                "status": "healthy",
                "provider_id": self.provider_id,
                "ready": True,
                "latency_ms": latency_ms,
                "engine": "anthropic",
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 2),
                "engine": "anthropic",
                "error": f"GET /v1/models failed: {exc}",
                "retryable": retryable_for_exception(exc),
            }

    async def list_models(self, directory: str = "") -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        try:
            resp = await self.get_http_client().get(
                f"{ANTHROPIC_API_BASE}/v1/models",
                headers={"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION},
                timeout=10.0,
            )
            resp.raise_for_status()
            models = [m.get("id", "") for m in resp.json().get("data", []) if m.get("id")]
            return [{"name": m, "id": m, "type": "llm"} for m in sorted(models)]
        except Exception as exc:
            logger.warning("anthropic_list_models_failed", provider_id=self.provider_id, error=str(exc))
            return []

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        raise NotImplementedError("File streaming is not applicable for hosted LLM endpoints")

    async def delete_file(self, path: str) -> bool:
        return False

    async def inference(
        self,
        workflow: Dict[str, Any],
        job_id: Optional[str] = None,
        use_snapshot: bool = True,
        timeout: float = 120.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        messages, system_prompt = translate_messages_anthropic(workflow.get("messages") or [])
        tools = translate_tools_anthropic(workflow.get("tools"))
        model = workflow.get("model") or self.default_model
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": workflow.get("max_output_tokens") or 4096,
        }
        if tools:
            payload["tools"] = tools
        if workflow.get("temperature") is not None:
            payload["temperature"] = workflow["temperature"]
        if workflow.get("top_p") is not None:
            payload["top_p"] = workflow["top_p"]
        if system_prompt:
            payload["system"] = system_prompt.strip()

        timeout = clamp_timeout(timeout, default=120.0)
        logger.info("llm_inference_start", provider_id=self.provider_id, job_id=job_id, model=model)
        yield {"event": "started", "job_id": job_id, "provider_id": self.provider_id}

        full_content = ""
        tool_blocks: Dict[int, Dict[str, str]] = {}
        try:
            async with self.get_http_client().stream(
                "POST",
                f"{ANTHROPIC_API_BASE}/v1/messages",
                headers=self._headers(),
                json=payload,
                timeout=timeout,
            ) as response:
                if response.status_code != 200:
                    err_text = await response.aread()
                    err_msg = f"Anthropic returned {response.status_code}: {err_text.decode('utf-8', 'ignore')}"
                    yield {"event": "failed", "job_id": job_id, "message": err_msg,
                           "retryable": retryable_for_status(response.status_code)}
                    return
                async for data_str in iter_sse_data(response.aiter_lines()):
                    if job_id and job_id in self._cancelled_jobs:
                        self._cancelled_jobs.discard(job_id)
                        yield {
                            "event": "cancelled",
                            "job_id": job_id,
                            "message": "Job cancelled by user",
                            "outputs": [{
                                "role": "assistant",
                                "content": full_content,
                                "cancelled": True,
                            }],
                        }
                        return
                    data = parse_sse_json(data_str)
                    if data is None:
                        continue
                    type_ = data.get("type")
                    if type_ == "content_block_start":
                        block = data.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            tool_blocks[data.get("index", 0)] = {
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "input_json": "",
                            }
                    elif type_ == "content_block_delta":
                        delta = data.get("delta", {}) or {}
                        if delta.get("type") == "input_json_delta":
                            entry = tool_blocks.setdefault(
                                data.get("index", 0), {"id": "", "name": "", "input_json": ""})
                            entry["input_json"] += delta.get("partial_json", "")
                        else:
                            text = delta.get("text", "")
                            if text:
                                full_content += text
                                yield {"event": "delta", "job_id": job_id, "text": text}
            output: Dict[str, Any] = {"role": "assistant", "content": full_content}
            if tool_blocks:
                output["tool_calls"] = [
                    {"id": b["id"], "type": "function",
                     "function": {"name": b["name"], "arguments": b["input_json"]}}
                    for b in (tool_blocks[i] for i in sorted(tool_blocks))
                ]
            yield {"event": "completed", "job_id": job_id, "outputs": [output]}
        except httpx.TimeoutException:
            yield {"event": "failed", "job_id": job_id,
                   "message": f"LLM generation timed out after {int(timeout)}s", "retryable": True}
        except asyncio.CancelledError:
            # Parity with the container Anthropic client: an externally
            # cancelled stream yields a cancelled event (empty content —
            # the half-written message is not recorded as a success).
            yield {"event": "cancelled", "job_id": job_id,
                    "message": "Job cancelled by user",
                    "outputs": [{"role": "assistant", "content": "", "cancelled": True}]}
        except Exception as exc:
            logger.exception("llm_inference_error", provider_id=self.provider_id, job_id=job_id, error=str(exc))
            yield {"event": "failed", "job_id": job_id, "message": f"LLM generation error: {exc}",
                   "retryable": retryable_for_exception(exc)}


class GoogleLLMEngine(InProcessEngine):
    """In-process execution engine for the Google Gemini API.

    Wire parity with llm_worker/engines/google/client.py: x-goog-api-key
    header (never query string), contents/systemInstruction/generationConfig
    payload, candidates.parts SSE parsing, key redaction on error paths,
    free GET /v1beta/models health probe.
    """

    def __init__(
        self,
        provider_id: str,
        api_key: Optional[str] = None,
        default_model: str = "gemini-1.5-flash",
    ):
        super().__init__(provider_id)
        self.api_key = (api_key or "").strip()
        self.default_model = default_model or "gemini-1.5-flash"
        self._http: Optional[httpx.AsyncClient] = None


    def get_http_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=120.0)
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def get_info(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "google",
            "engine": "google",
            "default_model": self.default_model,
        }

    async def check_health(self) -> Dict[str, Any]:
        t0 = time.monotonic()
        if not self.api_key:
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 2),
                "engine": "google",
                "error": "no API key configured (GOOGLE_API_KEY)",
            }
        try:
            resp = await self.get_http_client().get(
                f"{GOOGLE_API_BASE}/models",
                headers={GOOGLE_API_KEY_HEADER: self.api_key},
                timeout=_health_probe_timeout(
                    "GOOGLE_HEALTH_PROBE_TIMEOUT", _LLM_HEALTH_PROBE_TIMEOUT
                ),
            )
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            if resp.status_code >= 400:
                return {
                    "status": "unhealthy",
                    "provider_id": self.provider_id,
                    "ready": False,
                    "latency_ms": latency_ms,
                    "engine": "google",
                    "error": f"GET /models returned HTTP {resp.status_code}",
                    "retryable": retryable_for_status(resp.status_code),
                }
            return {
                "status": "healthy",
                "provider_id": self.provider_id,
                "ready": True,
                "latency_ms": latency_ms,
                "engine": "google",
            }
        except Exception:
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 2),
                "engine": "google",
                "error": "GET /models failed: connection error",
                "retryable": True,
            }

    async def list_models(self, directory: str = "") -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        try:
            resp = await self.get_http_client().get(
                f"{GOOGLE_API_BASE}/models",
                headers={GOOGLE_API_KEY_HEADER: self.api_key},
                timeout=10.0,
            )
            resp.raise_for_status()
            models = []
            for m in resp.json().get("models", []):
                name = m.get("name", "")
                if name.startswith("models/"):
                    name = name[7:]
                if "generateContent" in (m.get("supportedGenerationMethods") or []):
                    models.append(name)
            return [{"name": m, "id": m, "type": "llm"} for m in sorted(models)]
        except Exception as exc:
            logger.warning("google_list_models_failed", provider_id=self.provider_id,
                           error=redact_api_key(str(exc), self.api_key))
            return []

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        raise NotImplementedError("File streaming is not applicable for hosted LLM endpoints")

    async def delete_file(self, path: str) -> bool:
        return False

    async def inference(
        self,
        workflow: Dict[str, Any],
        job_id: Optional[str] = None,
        use_snapshot: bool = True,
        timeout: float = 120.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        contents, system_prompt = translate_messages_google(workflow.get("messages") or [])
        tools = translate_tools_google(workflow.get("tools"))
        model = workflow.get("model") or self.default_model
        payload: Dict[str, Any] = {"contents": contents}
        if tools:
            payload["tools"] = tools
        generation_config: Dict[str, Any] = {}
        if workflow.get("temperature") is not None:
            generation_config["temperature"] = workflow["temperature"]
        if workflow.get("top_p") is not None:
            generation_config["topP"] = workflow["top_p"]
        if workflow.get("max_output_tokens") is not None:
            generation_config["maxOutputTokens"] = workflow["max_output_tokens"]
        if workflow.get("frequency_penalty") is not None:
            generation_config["frequencyPenalty"] = workflow["frequency_penalty"]
        if workflow.get("presence_penalty") is not None:
            generation_config["presencePenalty"] = workflow["presence_penalty"]
        if generation_config:
            payload["generationConfig"] = generation_config
        if system_prompt:
            payload["systemInstruction"] = {
                "role": "user", "parts": [{"text": system_prompt.strip()}]}

        url = f"{GOOGLE_API_BASE}/models/{model}:streamGenerateContent?alt=sse"
        timeout = clamp_timeout(timeout, default=120.0)
        logger.info("llm_inference_start", provider_id=self.provider_id, job_id=job_id, model=model)
        yield {"event": "started", "job_id": job_id, "provider_id": self.provider_id}

        full_content = ""
        tool_calls: List[Dict[str, Any]] = []
        try:
            async with self.get_http_client().stream(
                "POST",
                url,
                headers={"Content-Type": "application/json", GOOGLE_API_KEY_HEADER: self.api_key},
                json=payload,
                timeout=timeout,
            ) as response:
                if response.status_code != 200:
                    err_text = await response.aread()
                    err_msg = redact_api_key(
                        f"Google returned {response.status_code}: {err_text.decode('utf-8', 'ignore')}",
                        self.api_key)
                    yield {"event": "failed", "job_id": job_id, "message": err_msg,
                           "retryable": retryable_for_status(response.status_code)}
                    return
                async for data_str in iter_sse_data(response.aiter_lines()):
                    if job_id and job_id in self._cancelled_jobs:
                        self._cancelled_jobs.discard(job_id)
                        yield {
                            "event": "cancelled",
                            "job_id": job_id,
                            "message": "Job cancelled by user",
                            "outputs": [{
                                "role": "assistant",
                                "content": full_content,
                                "cancelled": True,
                            }],
                        }
                        return
                    data = parse_sse_json(data_str)
                    if data is None:
                        continue
                    # First candidate only (parity with the container Google
                    # client): extra candidates would emit duplicate deltas
                    # and duplicate tool_calls.
                    candidates = data.get("candidates", []) or []
                    if candidates:
                        for part in (candidates[0].get("content", {}).get("parts", []) or []):
                            text = part.get("text", "")
                            if text:
                                full_content += text
                                yield {"event": "delta", "job_id": job_id, "text": text}
                            fn_call = part.get("functionCall")
                            if fn_call:
                                name = fn_call.get("name", "")
                                tool_calls.append({
                                    "id": name,
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(fn_call.get("args") or {}),
                                    },
                                })
            output: Dict[str, Any] = {"role": "assistant", "content": full_content}
            if tool_calls:
                output["tool_calls"] = tool_calls
            yield {"event": "completed", "job_id": job_id, "outputs": [output]}
        except httpx.TimeoutException:
            yield {"event": "failed", "job_id": job_id,
                   "message": f"LLM generation timed out after {int(timeout)}s", "retryable": True}
        except asyncio.CancelledError:
            # Parity with the container Google client: an externally
            # cancelled stream yields a cancelled event, never a success
            # carrying a half-written message.
            yield {"event": "cancelled", "job_id": job_id,
                    "message": "Job cancelled by user",
                    "outputs": [{"role": "assistant", "content": "", "cancelled": True}]}
        except Exception as exc:
            message = redact_api_key(str(exc), self.api_key)
            logger.exception("llm_inference_error", provider_id=self.provider_id, job_id=job_id, error=message)
            yield {"event": "failed", "job_id": job_id, "message": f"LLM generation error: {message}",
                   "retryable": retryable_for_exception(exc)}
