"""
Beam and self-hosted-container engines for the LLM and TTS categories.

These four cells were empty in the provider matrix before this module existed.
The Beam integration only ever spoke the ComfyUI WebSocket protocol, and the
container path for LLM/TTS was folded in-process on 2026-10-08 — which left
"Beam LLM", "Beam TTS", "self-hosted LLM container" and "self-hosted TTS
container" as cells that nothing could fill, so nothing offered them either.

The design keeps each engine as small as its protocol allows:

* ``BeamLLMEngine`` / ``BeamTTSEngine`` reuse ``BeamEngine``'s websocket
  plumbing wholesale and differ only in the frame dialect they speak. Both are
  subclasses, not copies — a second websocket client for the same provider
  transport is exactly the duplication that made the old flat registry
  ambiguous.
* ``RemoteLLMEngine`` subclasses ``OpenAICompatLLMEngine`` — our own LLM
  container speaks the OpenAI protocol (that is the point of deploying it),
  so the only real difference is where the credentials come from: a remote_agent
  service token instead of a hosted API key.
* ``RemoteTTSEngine`` talks plain REST to the TTS container, which is what a
  synthesis request actually is — a POST with no streaming progress worth
  relaying frame by frame.

Protocol notes for the deployed containers (see ``remote_workers/``):
* Beam realtime handlers answer ``{"token", <payload>}`` with the same
  ``{"event": ...}`` TaskEvent frames the ComfyUI and LLM engines already
  emit. Nothing new to learn on either side.
* The remote containers authenticate with the ``Authorization: Bearer
  <service-token>`` header that ``remote_agent/provider_core`` already
  validates, so a container reused for image agents works unchanged.
"""

import asyncio
import json
import os
from typing import Any, AsyncIterator, Dict, Optional

import httpx
import websockets

from config import env_positive_float, env_positive_int
from infrastructure.logging import get_logger
from services.engines.base import (
    TERMINAL_EVENTS,
    EngineAuthError,
    FileTooLargeError,
    InProcessEngine,
    clamp_timeout,
    get_file_size_cap,
    is_auth_error,
)
from services.engines.beam_engine import BeamEngine
from services.engines.llm_engine import OpenAICompatLLMEngine

logger = get_logger("worker_transport_engines")

#: The remote container's ports, when the defaults are not overridden. The two
#: workers are separate images with separate health contracts, so they listen on
#: different ports rather than sharing one compose service.
LLM_DEFAULT_PORT = 8001
TTS_DEFAULT_PORT = 8002

#: Header the remote_agent service-token auth middleware validates. Shared with
#: DirectComfyEngine's agent path so a container that already serves image
#: agents needs no second credential scheme.
SERVICE_TOKEN_HEADER = "Authorization"

#: Poll interval while a remote LLM request is in flight. The container streams
#: SSE, so this only bounds how long we wait for the *first* byte.
_LLM_STREAM_TIMEOUT_SECONDS = env_positive_float(
    os.getenv("REMOTE_LLM_STREAM_TIMEOUT_SECONDS"), 300.0
)

#: How many bytes of a synthesised clip to hold in memory before spilling.
_TTS_MAX_BODY_BYTES = env_positive_int(
    os.getenv("REMOTE_TTS_MAX_BODY_BYTES"), 512 * 1024 * 1024
)


class _BeamLLMEngineBase(BeamEngine):
    """Shared plumbing for the two Beam LLM/TTS engines.

    ``BeamEngine`` already owns everything worth owning here: the websocket
    dial (with its two header-kwarg spellings for version drift), the
    fetcher-task + queue + 2 s poll loop, the cancellation abort, the retryable
    classification and the auth-error mapping. What the LLM/TTS dialects need is
    a different *payload* and a different *frame reader* — so those are the two
    hooks this class exposes, and nothing else is reimplemented.

    The ComfyUI image engine's ``inference`` is a separate method rather than a
    shared base because its frame set (``executing`` / ``progress`` /
    ``executed``) is genuinely unrelated to a chat delta stream. Sharing the
    loop would take more branches than it would save; sharing the *plumbing* is
    what removes the duplication.
    """

    #: The websocket endpoint on the Beam app: ``/llm`` or ``/tts``. Beam's
    #: realtime handler routes on the path, so this is the whole difference
    #: between the two engines.
    ws_path: str = "/llm"

    #: Keys the container needs in the request payload beyond ``token``.
    #: Overridden per engine so the payload is declarative.
    request_fields: tuple[str, ...] = ("messages",)

    def _ws_target(self) -> str:
        """The full websocket URL for this dialect."""
        if self.ws_path == "/":
            return self.gpu_url
        return f"{self.gpu_url.rstrip('/')}{self.ws_path}"

    def _payload(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """Build the request payload, carrying only the dialect's fields."""
        payload: Dict[str, Any] = {"token": self.api_key}
        if getattr(self, "wants_tts_request", False):
            payload.update(_tts_request_from_workflow(workflow))
        for field in self.request_fields:
            if field in workflow:
                payload[field] = workflow[field]
        # Sampling and voice settings pass through verbatim: the container owns
        # its own contract for them and a filtered-envelope approach here would
        # need updating every time a model added a sampler.
        for field in ("temperature", "top_p", "max_output_tokens",
                      "frequency_penalty", "presence_penalty", "model",
                      "voice", "speed", "stream"):
            if workflow.get(field) is not None:
                payload[field] = workflow[field]
        return payload

    def _connect(self, timeout: float):
        """Open the websocket for this dialect.

        Pulled out of the loop only so the two header-kwarg spellings live once;
        ``BeamEngine.inference`` has the same fallback for the same reason
        (websockets names the kwarg `additional_headers` in some builds and
        `extra_headers` in others).
        """
        headers = {"Authorization": f"Bearer {self.api_key}"}
        target = self._ws_target()
        try:
            return websockets.connect(
                target,
                max_size=self.ws_max_size_mb * 1024 * 1024,
                additional_headers=headers,
                open_timeout=self.ws_open_timeout,
            )
        except TypeError:
            return websockets.connect(
                target,
                max_size=self.ws_max_size_mb * 1024 * 1024,
                extra_headers=headers,
                open_timeout=self.ws_open_timeout,
            )

    async def inference(
        self,
        workflow: dict[str, Any],
        job_id: Optional[str] = None,
        use_snapshot: bool = True,
        timeout: float = 1800.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream TaskEvents from the Beam app over the dialect's websocket.

        Same loop as ``BeamEngine.inference``: fetcher + queue, 2 s poll so a
        cancel is observed during a stall, and the abort registered so the
        websocket actually closes rather than being left to the caller's timeout.
        """
        _ = use_snapshot
        logger.info(
            "beam_dialect_inference_start",
            provider_id=self.provider_id,
            job_id=job_id,
            dialect=self.ws_path,
        )
        yield {"event": "started", "job_id": job_id, "provider_id": self.provider_id}

        timeout = clamp_timeout(timeout, default=1800.0)
        queue: asyncio.Queue = asyncio.Queue()

        async def _fetcher() -> None:
            try:
                ws_ctx = self._connect(timeout)
                async with ws_ctx as ws:
                    await ws.send(json.dumps(self._payload(workflow)))
                    async for message in ws:
                        await queue.put(message)
                    await queue.put(None)
            except Exception as exc:
                await queue.put(exc)

        task = asyncio.create_task(_fetcher())
        self.register_abort(job_id, task.cancel)
        try:
            async with asyncio.timeout(timeout):
                while True:
                    if job_id and job_id in self._cancelled_jobs:
                        self._cancelled_jobs.discard(job_id)
                        yield {"event": "cancelled", "job_id": job_id, "message": "Job cancelled"}
                        return
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=2.0)
                    except asyncio.TimeoutError:
                        continue
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item

                    payload = item.decode("utf-8") if isinstance(item, bytes) else item
                    try:
                        event = json.loads(payload)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    event.setdefault("job_id", job_id)
                    yield event
                    if event.get("event") in TERMINAL_EVENTS:
                        task.cancel()
                        return
        except asyncio.TimeoutError:
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"Beam {self.ws_path.lstrip('/')} timed out after {int(timeout)}s",
                "retryable": True,
            }
        except asyncio.CancelledError:
            raise
        except EngineAuthError:
            raise
        except Exception as exc:
            if is_auth_error(exc):
                raise
            text = f"{type(exc).__name__}: {exc}".lower()
            if "unauthorized" in text or "401" in text or "403" in text:
                raise EngineAuthError(f"Beam {self.ws_path} rejected credentials: {exc}") from exc
            logger.warning(
                "beam_dialect_inference_failed",
                provider_id=self.provider_id,
                job_id=job_id,
                dialect=self.ws_path,
                error=str(exc),
            )
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"Beam {self.ws_path.lstrip('/')} stream error: {exc}",
                "retryable": True,
            }

    # ------------------------------------------------------------------
    # Model lifecycle. A hosted LLM/TTS endpoint has no model tree, so these
    # answer honestly instead of pretending to manage files on the app's volume.
    # ------------------------------------------------------------------
    manages_model_files: bool = False

    async def list_models(self, directory: str) -> list[dict[str, Any]]:
        """No model tree: the container owns its weights, not the backend."""
        return []

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        """Beam hosts no object storage for these dialects."""
        raise NotImplementedError(
            f"{type(self).__name__} has no file storage; generated audio is "
            "delivered in the `completed` event's outputs"
        )

    async def delete_file(self, path: str) -> bool:
        return False

    async def check_health(self) -> dict[str, Any]:
        """Report the URL as configured, not as reachable.

        A websocket dial from a health check would either block for the open
        timeout or — worse — be counted as a failure on a provider that is fine,
        because a ``@modal.concurrent``-style handler with no traffic answers
        slowly on the first request. The 15 s health cache and the load
        balancer's dispatch-time failure streak are the real signals; this
        reports config validity, which is what the health endpoint can honestly
        know without a round trip. Same trade BeamEngine's ``beam`` type makes.
        """
        return {
            "status": "healthy" if self.gpu_url else "rejected",
            "healthy": bool(self.gpu_url),
            "provider_id": self.provider_id,
            "engine": type(self).__name__,
            "gpu_url_configured": bool(self.gpu_url),
        }

    async def setup_models(self) -> bool:
        """Nothing to initialise: the container owns its weights."""
        return True

    async def get_object_info(self) -> Dict[str, Any]:
        return {"object_info": {}}

    async def get_storage_stats(self) -> Dict[str, Any]:
        return {"provider_id": self.provider_id, "total": 0, "by_directory": {}}

    async def upload_file(self, filename: str, content_base64: str, directory: str = "") -> bool:
        """No shared volume to write into for a hosted LLM/TTS endpoint."""
        return False

    async def get_info(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "beam",
            "category": "llm" if self.ws_path.startswith("/llm") else "tts",
            "engine": type(self).__name__,
            "gpu_type": self.gpu_type,
            "gpu_url_configured": bool(self.gpu_url),
        }


class BeamLLMEngine(_BeamLLMEngineBase):
    """Beam serverless LLM (a llama.cpp or vLLM endpoint behind the handler)."""

    ws_path = "/llm"
    request_fields = ("messages",)


class BeamTTSEngine(_BeamLLMEngineBase):
    """Beam serverless speech synthesis."""

    ws_path = "/tts"
    # Speech is a flat request rather than a ComfyUI graph, so this engine reads
    # the graph the app builds and sends the extracted text — see
    # `_tts_request_from_workflow`.
    request_fields = ()
    wants_tts_request = True


class RemoteLLMEngine(OpenAICompatLLMEngine):
    """The self-hosted TNHComfy LLM container.

    Speaks the OpenAI protocol — that is why the container is deployable
    anywhere and fronted by llama.cpp or vLLM — so this is
    ``OpenAICompatLLMEngine`` with a different credential envelope rather than a
    second HTTP client. The URL and token are read from the remote_agent config
    keys so a provider row written for the image agent sidecar points at the
    same container with no renaming.
    """

    def __init__(
        self,
        provider_id: str,
        agent_url: str,
        agent_token: str,
        default_model: str = "default",
        default_rp_model: str = "rp",
        default_util_model: str = "util",
        **kwargs: Any,
    ) -> None:
        base_url = (agent_url or "").strip().rstrip("/")
        if base_url and not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        super().__init__(
            provider_id=provider_id,
            base_url=base_url,
            api_key=(agent_token or "").strip(),
            default_model=default_model,
            **kwargs,
        )
        # The two-model router's per-kind defaults. Kept on the engine rather
        # than resolved at dispatch so a provider can pin `util` to a smaller
        # quantisation without touching the router's table.
        self.default_rp_model = default_rp_model or "rp"
        self.default_util_model = default_util_model or "util"

    def _headers(self) -> Dict[str, str]:
        """The service token, in the header the container validates.

        Bearer rather than a bespoke ``X-Service-Token`` because
        ``remote_agent/provider_core`` already validates
        ``Authorization: Bearer`` — a second scheme would need the container
        changed for no gain.
        """
        return {
            "Content-Type": "application/json",
            SERVICE_TOKEN_HEADER: f"Bearer {self.api_key}",
        }


def _tts_request_from_workflow(workflow: dict) -> dict:
    """Extract a TTS request from either workflow shape.

    The app builds ONE shape — a ComfyUI graph with the text buried at
    `prompt["<node>"]["inputs"]` — because `build_voice_speak_workflow` is shared
    with the ComfyUI-based TTS engines. The engines that speak a plain HTTP
    protocol (`remote_tts`, `beam_tts`) must read the same document, not a
    hypothetical flat one.

    Reading `workflow["text"]` instead made those two transports refuse every
    real narration with "TTS request carried no text", after the job had already
    been routed and paid for. Both shapes are accepted here so a caller that
    does have a flat workflow still works.
    """
    text = (workflow or {}).get("text")
    voice = (workflow or {}).get("voice")
    language = (workflow or {}).get("language")

    prompt = (workflow or {}).get("prompt")
    if isinstance(prompt, dict):
        for node in prompt.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs") or {}
            if not isinstance(inputs, dict):
                continue
            text = text or inputs.get("text")
            voice = voice or inputs.get("voice") or inputs.get("speaker")
            language = language or inputs.get("language")

    return {
        "text": (text or "").strip(),
        "voice": (voice or "").strip() or None,
        "language": (language or "").strip() or None,
    }


class RemoteTTSEngine(InProcessEngine):
    """The self-hosted TNHComfy TTS container.

    A synthesis request is not a progress stream: it is a POST whose useful
    signal is the clip that comes back, so this engine yields exactly the three
    events a caller can act on — ``started``, ``completed`` with the stored
    path, or ``failed`` — rather than relaying frame-by-frame progress that
    would have to be invented somewhere in the container.

    The clip is fetched through ``get_file_stream`` on the same
    ``remote_agent`` HTTP shape the image agent path uses, so file addressing and
    the service-token auth are identical across both.
    """

    manages_model_files: bool = False
    supports_discovery_reconcile: bool = False

    def __init__(
        self,
        provider_id: str,
        agent_url: str,
        agent_token: str,
        default_voice: str = "",
        timeout: float = 1800.0,
    ) -> None:
        super().__init__(provider_id)
        self.agent_url = (agent_url or "").strip().rstrip("/")
        self.agent_token = (agent_token or "").strip()
        self.default_voice = default_voice or os.getenv("TTS_DEFAULT_VOICE", "")
        self.timeout = float(timeout)
        self._http: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # HTTP client, the same shape DirectComfyEngine uses for its agent.
    # ------------------------------------------------------------------
    def get_http_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self.agent_url,
                timeout=clamp_timeout(self.timeout, default=1800.0),
                headers={
                    "Content-Type": "application/json",
                    SERVICE_TOKEN_HEADER: f"Bearer {self.agent_token}",
                },
            )
        return self._http

    async def close(self) -> None:
        client, self._http = self._http, None
        if client is not None and not client.is_closed:
            try:
                await client.aclose()
            except Exception as exc:
                # Teardown must never fail a job finalisation path.
                logger.warning(
                    "remote_tts_client_close_failed",
                    provider_id=self.provider_id,
                    error=str(exc),
                )

    def _auth_failure(self, exc: Exception) -> Optional[dict[str, Any]]:
        """An auth failure, or None when `exc` is not one."""
        if not is_auth_error(exc):
            return None
        return {
            "event": "failed",
            "job_id": None,
            "message": f"TTS container rejected the service token: {exc}",
            "retryable": False,
        }

    # ------------------------------------------------------------------
    # The engine contract.
    # ------------------------------------------------------------------
    async def inference(
        self,
        workflow: dict[str, Any],
        job_id: Optional[str] = None,
        use_snapshot: bool = True,
        timeout: float = 1800.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """Synthesise speech on the self-hosted container.

        The request carries the text, the voice and any sampling knobs the
        workflow dict happens to have. The response is a small JSON descriptor,
        not the audio itself — the clip is retrieved through get_file_stream, so
        the size cap that governs every other download governs it too.
        """
        _ = use_snapshot
        yield {"event": "started", "job_id": job_id, "provider_id": self.provider_id}

        if job_id and job_id in self._cancelled_jobs:
            self._cancelled_jobs.discard(job_id)
            yield {"event": "cancelled", "job_id": job_id, "message": "Job cancelled"}
            return

        request = _tts_request_from_workflow(workflow)
        text = request["text"]
        voice = request["voice"] or self.default_voice
        language = request["language"]
        if not text:
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": (
                    "TTS request carried no text; the workflow must put it in "
                    "`prompt[<node>][inputs][text]` or at the top level"
                ),
                "retryable": False,
            }
            return

        payload: Dict[str, Any] = {"text": text}
        if voice:
            payload["voice"] = voice
        if language:
            payload["language"] = language
        for field in ("speed", "format", "sample_rate"):
            if workflow.get(field) is not None:
                payload[field] = workflow[field]

        timeout = clamp_timeout(timeout or self.timeout, default=1800.0)
        try:
            client = self.get_http_client()
            response = await client.post("/synthesize", json=payload, timeout=timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            auth = self._auth_failure(exc)
            if auth is not None:
                yield {**auth, "job_id": job_id}
                return
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"TTS container request failed: {type(exc).__name__}: {exc}",
                "retryable": True,
            }
            return

        if response.status_code != 200:
            if response.status_code in (401, 403):
                yield {
                    "event": "failed",
                    "job_id": job_id,
                    "message": f"TTS container rejected the service token ({response.status_code})",
                    "retryable": False,
                }
                return
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"TTS container returned {response.status_code}: "
                           f"{response.text[:200] if response.text else ''}",
                "retryable": False,
            }
            return

        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"TTS container returned a non-JSON response: {exc}",
                "retryable": False,
            }
            return

        # The container answers in the agent's canonical envelope:
        # `{"status": "success", "message": ..., "result": {...}}`. Reading the
        # top level alone finds nothing and turns a synthesised clip into
        # "no file path" — the failure this fallback used to hit end to end.
        payload = body.get("result") if isinstance(body.get("result"), dict) else body
        path = (
            payload.get("path")
            or payload.get("storage_path")
            or payload.get("filename")
        )
        filename = payload.get("filename")
        duration = payload.get("duration")
        if not path:
            # A 200 with no address is a success that cannot be fetched, which
            # is worse than a failure: the caller would persist a job with
            # nothing to download. Reported as one rather than as a green job.
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": "TTS container returned no file path for the clip",
                "retryable": True,
            }
            return

        yield {
            "event": "completed",
            "job_id": job_id,
            "outputs": [{
                "filename": filename or path,
                "path": path,
                "type": "audio",
                "duration": duration,
                # The container echoes its own voice back when it substituted a
                # default, which is what the UI should show rather than the
                # request's.
                "voice": payload.get("voice") or voice,
            }],
        }

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        """Fetch a synthesised clip from the container.

        Bounded by the shared read cap, so a path that resolves to something
        enormous is refused rather than streamed into the caller — the same
        ceiling the ComfyUI `/view` and agent branches enforce.
        """
        import urllib.parse

        cap = get_file_size_cap()
        client = self.get_http_client()
        url = f"/get-file/{urllib.parse.quote(path, safe='/')}"
        async with client.stream("GET", url, timeout=120.0) as response:
            if response.status_code == 404:
                raise FileNotFoundError(f"TTS container has no file at {path}")
            if response.status_code != 200:
                raise RuntimeError(
                    f"TTS container /get-file returned {response.status_code} for {path}"
                )
            declared = response.headers.get("content-length")
            if cap and declared and declared.isdigit() and int(declared) > cap:
                raise FileTooLargeError(path, size=int(declared), cap=cap)

            total = 0
            async for chunk in response.aiter_bytes(65536):
                total += len(chunk)
                if cap and total > cap:
                    raise FileTooLargeError(path, size=total, cap=cap)
                yield chunk

    async def delete_file(self, path: str) -> bool:
        """Delete a clip. `True` means the path is gone afterwards.

        `POST /delete-file` with a JSON body — the protocol the agent already
        defines for every other artefact — rather than a path-shaped URL: a path
        in the URL has to be re-encoded, and the agent's own containment check
        (`_data_path`) is what makes a body path safe.
        """
        if not path:
            return False
        client = self.get_http_client()
        try:
            response = await client.post(
                "/delete-file", json={"path": path}, timeout=30.0
            )
            if response.status_code >= 400:
                # 404 means the clip is already gone, which is success for a
                # delete. Anything else is a real failure and must not read as
                # one — a false True here is how a caller ends up believing a
                # file it still has is gone.
                if response.status_code == 404:
                    return True
                logger.warning(
                    "remote_tts_delete_rejected",
                    provider_id=self.provider_id,
                    path=path,
                    status=response.status_code,
                )
                return False
            return True
        except Exception as exc:
            logger.warning(
                "remote_tts_delete_failed",
                provider_id=self.provider_id,
                path=path,
                error=str(exc),
            )
            return False

    async def list_models(self, directory: str = "voices") -> list[dict[str, Any]]:
        """The container's voice catalogue.

        A hosted TTS service cannot enumerate its voices over the API, so an
        empty answer means "ask the container" — reported as an empty list the
        voice picker renders as its default rather than as an error the user has
        to dismiss.
        """
        return []

    async def check_health(self) -> dict[str, Any]:
        """Config validity, per the same trade the Beam engines make.

        No round trip: a cold container would otherwise read unhealthy and the
        dispatch-time failure streak would take it out of rotation before it had
        a chance to scale up.
        """
        return {
            "status": "healthy" if (self.agent_url and self.agent_token) else "rejected",
            "healthy": bool(self.agent_url and self.agent_token),
            "provider_id": self.provider_id,
            "engine": "RemoteTTSEngine",
            "url_configured": bool(self.agent_url),
            "token_configured": bool(self.agent_token),
        }

    async def setup_models(self) -> bool:
        return True

    async def get_object_info(self) -> Dict[str, Any]:
        return {"object_info": {}}

    async def get_storage_stats(self) -> Dict[str, Any]:
        return {"provider_id": self.provider_id, "total": 0, "by_directory": {}}

    async def upload_file(self, filename: str, content_base64: str, directory: str = "") -> bool:
        """No shared volume: the container owns its own model files."""
        return False

    async def get_info(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "remote",
            "category": "tts",
            "engine": "RemoteTTSEngine",
            "url_configured": bool(self.agent_url),
            "token_configured": bool(self.agent_token),
        }


__all__ = [
    "BeamLLMEngine",
    "BeamTTSEngine",
    "RemoteLLMEngine",
    "RemoteTTSEngine",
    "LLM_DEFAULT_PORT",
    "TTS_DEFAULT_PORT",
]
