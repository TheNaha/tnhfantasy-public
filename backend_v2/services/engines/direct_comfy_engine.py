"""
In-Process Direct ComfyUI Engine.

Directly communicates with any standard ComfyUI server instance over HTTP and WebSockets
without intermediate container proxies.
"""

import asyncio
import base64
import json
import os
import time
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
import websockets

from infrastructure.logging import get_logger
from services.engines.base import (
    EngineAuthError,
    FileTooLargeError,
    InProcessEngine,
    MODEL_DIRECTORIES,
    clamp_timeout,
    get_upload_size_cap,
    normalize_validation_result,
    retryable_for_status,
)

# The node whose `voice` input this engine feeds, and whose enum therefore IS
# the catalogue. Same constant the graph builder uses, imported rather than
# re-spelled — a rename of the pack must move both or neither.
from services.tts_workflow_builder import NODE_SPEAK

logger = get_logger("direct_comfy_engine")

_STREAM_CHUNK_BYTES = 1024 * 1024  # 1 MiB

# Ceiling on EACH of the two /health upstream probes, which run concurrently.
# Honors REMOTE_HEALTH_PROBE_TIMEOUT / COMFYUI_HEALTH_PROBE_TIMEOUT like the
# remote_comfy and direct_url container clients: the dispatcher's health
# budget is ~2s, so two sequential 1.5s probes would read as "no answer" on
# a fully dead rig.
def _health_probe_timeout() -> float:
    # Literals are written out (not looped over a tuple) so the
    # test_env_contracts AST walk resolves each key to its .env.example entry.
    for raw in (
        os.getenv("REMOTE_HEALTH_PROBE_TIMEOUT", ""),
        os.getenv("COMFYUI_HEALTH_PROBE_TIMEOUT", ""),
    ):
        raw = raw.strip()
        if raw:
            try:
                return max(0.1, float(raw))
            except (TypeError, ValueError):
                continue
    return 1.5


HEALTH_PROBE_TIMEOUT = _health_probe_timeout()


def _object_info_cache_ttl() -> float:
    raw = os.getenv("COMFYUI_OBJECT_INFO_CACHE_TTL", "").strip()
    if raw:
        try:
            # Zero disables the cache (parity with container clients which did
            # unclamped float(env or default)); negative falls back to default.
            parsed = float(raw)
            if parsed == 0:
                return 0.0
            if parsed > 0:
                return parsed
        except (TypeError, ValueError):
            pass
    return 30.0

# Timeout for agent /get-file streams. The old remote_comfy client allowed
# 600s (_GET_FILE_TIMEOUT_SECONDS): checkpoint reads stall longer than the
# 60s agent-client default.
AGENT_GET_FILE_TIMEOUT_SECONDS = 600.0

# WebSocket connect attempts, mirroring workflow_executor._connect_with_retry
# (max_retries=5): a transient connect failure must not fail the job.
_WS_CONNECT_RETRIES = 5

NODE_TO_DIRECTORY = {
    "CheckpointLoaderSimple": "checkpoints",
    "CheckpointLoader": "checkpoints",
    "UNETLoader": "unet",
    "LoraLoader": "loras",
    "LoraLoaderModelOnly": "loras",
    "VAELoader": "vae",
    "ControlNetLoader": "controlnet",
    "UpscaleModelLoader": "upscale_models",
    "CLIPLoader": "clip",
    "CLIPVisionLoader": "clip_vision",
    "HypernetworkLoader": "hypernetworks",
    "unCLIPCheckpointLoader": "checkpoints",
}

MODEL_INPUT_NAMES = {
    "ckpt_name", "model_name", "lora_name", "vae_name", "control_net_name",
    "model_name1", "clip_name", "upscaler_name", "hypernetwork_name",
}


def _normalize_directory(directory: Optional[str]) -> str:
    value = (directory or "").strip().strip("/")
    if value == "models":
        return ""
    if value.startswith("models/"):
        value = value[len("models/"):]
    return value


def normalize_comfy_url(raw: str, default: str = "http://localhost:8188") -> str:
    """Normalize a ComfyUI server URL, accepting scheme-less `host:port`.

    Mirrors provider_containers `workflow_executor.py:32-36`: a bare
    `host:port` gains an `http://` prefix instead of parsing to
    `netloc=""` and silently targeting 127.0.0.1:8188.
    """
    value = (raw or "").strip().rstrip("/")
    if not value:
        return default
    if "://" not in value:
        value = f"http://{value}"
    return value.rstrip("/")


def _files_from(payload: Any) -> List[Dict[str, Any]]:
    """Extract a file list from an agent/storage listing body.

    Mirrors provider_core.responses.files_from: the agent answers a dict with
    a ``files`` key today, but a proxy in front of it may answer a bare JSON
    array — accept either, and degrade to [] rather than raising.
    """
    if isinstance(payload, list):
        files = payload
    elif isinstance(payload, dict):
        files = payload.get("files", [])
    else:
        return []
    if not isinstance(files, list):
        return []
    return [f for f in files if isinstance(f, dict)]


@asynccontextmanager
async def _ws_connect_with_retry(ws_url: str, extra_headers: Dict[str, str]):
    """Connect to ComfyUI's websocket with retries.

    Mirrors workflow_executor._connect_with_retry (max_retries=5): a
    transient connect failure sleeps briefly and retries instead of failing
    the job. Yields the open socket; always closes it on exit. Tries
    ``additional_headers`` first then falls back to ``extra_headers`` on
    TypeError for websockets version drift (workflow_executor.py:44-80).
    """
    def _connect(url: str):
        try:
            return websockets.connect(url, additional_headers=extra_headers)
        except TypeError:
            return websockets.connect(url, extra_headers=extra_headers)

    last_error: Optional[Exception] = None
    for attempt in range(1, _WS_CONNECT_RETRIES + 1):
        candidate = _connect(ws_url)
        try:
            ws = await candidate.__aenter__()
        except Exception as exc:
            last_error = exc
            try:
                await candidate.__aexit__(type(exc), exc, exc.__traceback__)
            except Exception:
                pass
            if attempt >= _WS_CONNECT_RETRIES:
                raise
            logger.warning(
                "direct_comfy_ws_retry",
                ws_url=ws_url,
                attempt=attempt,
                error=str(exc),
            )
            await asyncio.sleep(min(attempt, 3))
            continue
        try:
            yield ws
        finally:
            try:
                await candidate.__aexit__(None, None, None)
            except Exception:
                pass
        return
    assert last_error is not None  # unreachable: the loop raises on the last attempt
    raise last_error


class DirectComfyEngine(InProcessEngine):
    """In-process execution engine for direct ComfyUI instances.

    With ``agent_url`` set this also fronts the remote-agent sidecar
    (remote_agent/server.py: list/delete/upload/validate/setup over HTTP),
    giving single-engine parity with the ``remote_comfy`` container client.
    Without it this is the plain ``direct_url`` shape: ComfyUI's own
    /object_info + /view, and no mutation support.
    """

    def __init__(
        self,
        provider_id: str,
        comfy_url: str = "http://localhost:8188",
        api_key: Optional[str] = None,
        stall_timeout: float = 300.0,
        agent_url: Optional[str] = None,
        agent_token: Optional[str] = None,
        hf_token: Optional[str] = None,
        civitai_token: Optional[str] = None,
    ):
        super().__init__(provider_id)
        self.comfy_url = normalize_comfy_url(comfy_url)
        self.api_key = (api_key or "").strip()
        self.stall_timeout = max(1.0, float(stall_timeout))
        self.agent_url = (agent_url or "").strip().rstrip("/")
        self.agent_token = (agent_token or "").strip()
        self.hf_token = hf_token or os.getenv("HF_TOKEN", "")
        self.civitai_token = civitai_token or os.getenv("CIVITAI_TOKEN", "")

        self._headers: Dict[str, str] = {}
        if self.api_key:
            self._headers["Authorization"] = f"Bearer {self.api_key}"

        self._http: Optional[httpx.AsyncClient] = None
        self._agent_http: Optional[httpx.AsyncClient] = None
        self._object_info_cache: Optional[tuple[float, Dict[str, Any]]] = None
        self._object_info_lock = asyncio.Lock()
        self._object_info_ttl = _object_info_cache_ttl()
        # job_id -> prompt_id, and prompt_id -> job_id for interrupts. ComfyUI's
        # `/interrupt` is global to the instance, so a cancel has to be attributed
        # to the prompt that was streaming, or a sibling job's cancel is reported
        # as this job's and a real completion looks like a cancellation.
        self._job_prompt_ids: Dict[str, str] = {}
        self._interrupted_prompts: Dict[str, str] = {}

    @property
    def _has_agent(self) -> bool:
        return bool(self.agent_url)

    @property
    def manages_model_files(self) -> bool:
        # Plain ComfyUI exposes no mutation surface (no upload, no download,
        # no delete): the model tree is only manageable through the agent
        # sidecar, which is also what makes this engine the remote_comfy
        # shape rather than the direct_url one.
        return self._has_agent

    supports_discovery_reconcile = True

    def _agent_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.agent_token:
            headers["Authorization"] = f"Bearer {self.agent_token}"
        return headers

    def download_token_for_url(self, url: str) -> Optional[str]:
        """Which registry token authenticates this download URL.

        Same predicate as `provider_core.utils.determine_download_token`,

        The old remote_comfy client resolved HF/Civitai tokens for agent
        downloads; without this, authenticated downloads 401.
        """
        lowered = (url or "").lower()
        if "huggingface.co" in lowered:
            return self.hf_token or None
        if "civitai.com" in lowered or "civitai.red" in lowered:
            return self.civitai_token or None
        return None

    def get_agent_client(self) -> httpx.AsyncClient:
        """Lazily initialize the sidecar agent HTTP client."""
        if self._agent_http is None or self._agent_http.is_closed:
            self._agent_http = httpx.AsyncClient(
                base_url=self.agent_url,
                timeout=60.0,
                headers=self._agent_headers(),
            )
        return self._agent_http

    async def _on_cancel(self, job_id: str) -> None:
        """Interrupt the shared ComfyUI worker. Base ``cancel_job`` only calls
        this for jobs currently streaming through ``run_inference`` — the
        old override fired unconditionally and could kill another job's
        prompt (remote_comfy legacy interrupted only its active job)."""
        # Attribute the interrupt to this job's prompt before POSTing, so the
        # loop's post-break check can tell "my cancel arrived" from "a sibling
        # job's interrupt arrived" — ComfyUI answers /interrupt with the same
        # `executing {node: null}` frame either way.
        prompt_id = self._job_prompt_ids.get(job_id)
        if prompt_id:
            self._interrupted_prompts[prompt_id] = job_id
        client = self.get_http_client()
        try:
            await client.post("/interrupt", timeout=5.0)
        except Exception as exc:
            logger.warning("direct_comfy_interrupt_failed", provider_id=self.provider_id, job_id=job_id, error=str(exc))
            if prompt_id:
                self._interrupted_prompts.pop(prompt_id, None)

    def get_http_client(self) -> httpx.AsyncClient:
        """Lazily initialize or retrieve the shared httpx.AsyncClient."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self.comfy_url,
                timeout=30.0,
                headers=self._headers,
            )
        return self._http

    async def close(self) -> None:
        """Close underlying HTTP client connections."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
        if self._agent_http and not self._agent_http.is_closed:
            await self._agent_http.aclose()

    async def get_info(self) -> dict[str, Any]:
        engine_type = "remote_comfy" if self._has_agent else "direct_url"
        return {
            "provider_id": self.provider_id,
            "type": engine_type,
            "engine": engine_type,
            "comfy_url": self.comfy_url,
            "comfy_url_configured": bool(self.comfy_url),
            "remote_agent_url_configured": bool(self.agent_url),
            "containerized": False,
        }

    async def check_health(self) -> Dict[str, Any]:
        """Probe ComfyUI /system_stats, plus the agent /health when configured.

        The two probes run concurrently inside the dispatcher's ~2s health
        budget (same reasoning as the remote_comfy container client). A dead
        upstream reads as unhealthy without a retryable marker — it really
        can come back, unlike a configuration fault.
        """
        t0 = time.monotonic()
        client = self.get_http_client()
        comfy_error: Optional[str] = None
        agent_error: Optional[str] = None

        async def _probe_comfy() -> Optional[str]:
            try:
                resp = await client.get("/system_stats", timeout=HEALTH_PROBE_TIMEOUT)
                if resp.status_code != 200:
                    return f"ComfyUI returned HTTP {resp.status_code}"
                return None
            except Exception as exc:
                return f"ComfyUI server is unreachable: {type(exc).__name__}: {exc}"

        async def _probe_agent() -> Optional[str]:
            try:
                agent = self.get_agent_client()
                resp = await agent.get("/health", timeout=HEALTH_PROBE_TIMEOUT)
                if resp.status_code != 200:
                    return f"Remote agent returned HTTP {resp.status_code}"
                return None
            except Exception as exc:
                return f"Remote agent is unreachable: {type(exc).__name__}: {exc}"

        if self._has_agent:
            comfy_error, agent_error = await asyncio.gather(_probe_comfy(), _probe_agent())
        else:
            comfy_error = await _probe_comfy()

        latency_ms = round((time.monotonic() - t0) * 1000, 2)
        failures = [e for e in (comfy_error, agent_error) if e]
        if failures:
            for error in failures:
                logger.warning("direct_comfy_health_failed", provider_id=self.provider_id, error=error)
            result: Dict[str, Any] = {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": latency_ms,
                "engine": "remote_comfy" if self._has_agent else "direct_url",
                "comfy_reachable": comfy_error is None,
                "error": "; ".join(failures),
            }
            if self._has_agent:
                result["agent_reachable"] = agent_error is None
            return result
        return {
            "status": "healthy",
            "provider_id": self.provider_id,
            "ready": True,
            "latency_ms": latency_ms,
            "engine": "remote_comfy" if self._has_agent else "direct_url",
            "comfy_reachable": True,
            **({"agent_reachable": True} if self._has_agent else {}),
        }

    async def _fetch_object_info(self) -> Dict[str, Any]:
        """Fetch and cache ComfyUI /object_info document with single-flight locking."""
        now = time.monotonic()
        if self._object_info_cache and now - self._object_info_cache[0] < self._object_info_ttl:
            return self._object_info_cache[1]

        async with self._object_info_lock:
            now = time.monotonic()
            if self._object_info_cache and now - self._object_info_cache[0] < self._object_info_ttl:
                return self._object_info_cache[1]

            client = self.get_http_client()
            try:
                resp = await client.get("/object_info")
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in (401, 403):
                    raise EngineAuthError(
                        f"ComfyUI rejected credentials for /object_info: HTTP {status}",
                        status_code=status,
                    ) from exc
                raise
            doc = resp.json()
            self._object_info_cache = (time.monotonic(), doc)
            return doc

    def _iter_object_info_model_paths(self, object_info: Dict[str, Any], directory: str = "") -> List[str]:
        paths: List[str] = []
        norm_dir = _normalize_directory(directory)
        for node_type, node_info in object_info.items():
            target_dir = NODE_TO_DIRECTORY.get(node_type)
            if not target_dir:
                continue
            if norm_dir and target_dir != norm_dir:
                continue
            node_input = node_info.get("input", {}) or {}
            inputs = []
            if isinstance(node_input.get("required"), dict):
                inputs.extend(node_input["required"].items())
            elif isinstance(node_input.get("required"), (list, tuple)):
                inputs.extend(node_input["required"])

            if isinstance(node_input.get("optional"), dict):
                inputs.extend(node_input["optional"].items())
            elif isinstance(node_input.get("optional"), (list, tuple)):
                inputs.extend(node_input["optional"])

            for input_def in inputs:
                if not isinstance(input_def, (list, tuple)) or len(input_def) < 2:
                    continue
                input_name = input_def[0]
                if input_name not in MODEL_INPUT_NAMES:
                    continue
                model_list = input_def[1]
                if isinstance(model_list, list) and model_list:
                    choices = model_list[0] if isinstance(model_list[0], list) else model_list
                    for model_name in choices:
                        if isinstance(model_name, str) and model_name:
                            # `models/`-prefixed, matching what every consumer of
                            # this list expects: `get_all_storage_paths` builds
                            # `models/{model.directory}/{filename}` and matches on
                            # it (`model_repo_v2.py`), the maintenance scan uses the
                            # same shape, and the agent branch reports `path` as
                            # `os.path.relpath(..., DATA_DIR)` which already carries
                            # the prefix. `target_dir` is bare after
                            # `_normalize_directory`, so without the prefix the
                            # no-agent rig's discovery matched nothing at all — files
                            # stayed pending forever and counted as orphaned on every
                            # tick, and `_storage_path_for_entry` had to undo the
                            # damage one level up.
                            paths.append(f"models/{target_dir}/{model_name}")
        return sorted(set(paths))

    async def list_models(self, directory: str) -> List[Dict[str, Any]]:
        """List models, preferring the agent sidecar when configured.

        The agent owns storage, so its listing is the source of truth on a
        remote_comfy rig. On agent failure this falls back to ComfyUI's own
        /object_info — the same rig, the same loadable models.
        """
        if self._has_agent:
            try:
                agent = self.get_agent_client()
                resp = await agent.post("/list-models", json={"directory": directory}, timeout=60.0)
                if resp.status_code in (401, 403):
                    # An agent-token mismatch must never fall through to the
                    # /object_info fallback: that would report the rig's
                    # loadable models as the agent's storage state.
                    raise EngineAuthError(
                        f"Remote agent rejected credentials for /list-models ({directory}): "
                        f"HTTP {resp.status_code}: {resp.text[:200]}",
                        status_code=resp.status_code,
                    )
                if resp.status_code == 200:
                    return _files_from(resp.json())
                logger.warning(
                    "direct_comfy_agent_list_models_failed",
                    provider_id=self.provider_id,
                    status=resp.status_code,
                )
                # A configured agent that cannot answer is an error, not a
                # license to report the comfyUI rig's loadables as the
                # agent's storage state (the old remote_comfy returned
                # failed here for the same reason).
                raise RuntimeError(
                    f"Remote agent /list-models failed for {directory}: HTTP {resp.status_code}"
                )
            except EngineAuthError:
                raise
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(f"Remote agent /list-models failed for {directory}: {exc}") from exc
        try:
            doc = await self._fetch_object_info()
            paths = self._iter_object_info_model_paths(doc, directory)
            return [
                # Basename, not "everything after the first segment": `path` now
                # carries `models/` as well as the directory, so a split-from-the-left
                # would leave `name` as `checkpoints/foo.safetensors` — a filename
                # no consumer can match, and one the reconciler would store.
                {
                    "name": os.path.basename(path),
                    "path": path,
                    "type": "file",
                    "size": 0,
                }
                for path in paths
            ]
        except EngineAuthError:
            raise
        except Exception as exc:
            # A dead ComfyUI must fail the listing (the container answered
            # a failed envelope and its reconcile pushed failed): returning
            # [] reads as "empty directory" and the reconciler marks every
            # expected file pending behind a "Discovery complete".
            logger.warning("direct_comfy_list_models_failed", provider_id=self.provider_id, error=str(exc))
            raise RuntimeError(f"ComfyUI /object_info listing failed for {directory}: {exc}") from exc

    async def get_object_info(self) -> Dict[str, Any]:
        """Raw pass-through of ComfyUI's /object_info document (nodes parity)."""
        return await self._fetch_object_info()

    async def validate_models(
        self,
        directories: List[str],
        delete_invalid: bool = False,
    ) -> Dict[str, Any]:
        """Validate models per directory via the agent, else via /object_info.

        `delete_invalid` is forwarded to the agent (without it
        reconciliation's full pass cannot prune corrupt models). Agent
        failures raise — the old reconcile probe raised on non-200 rather
        than report a clean sweep — with 401/403 typed as EngineAuthError.
        """
        if self._has_agent:
            results: Dict[str, Any] = {"by_directory": {}, "valid": [], "invalid": [], "partial": []}
            agent = self.get_agent_client()
            for directory in directories:
                resp = await agent.post(
                    "/validate-models",
                    json={"directory": directory, "delete_invalid": delete_invalid},
                    timeout=120.0,
                )
                if resp.status_code in (401, 403):
                    raise EngineAuthError(
                        f"Remote agent rejected credentials for /validate-models ({directory}): "
                        f"HTTP {resp.status_code}: {resp.text[:200]}",
                        status_code=resp.status_code,
                    )
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Remote agent /validate-models returned {resp.status_code} "
                        f"for {directory}: {resp.text[:200]}"
                    )
                payload = resp.json()
                results["by_directory"][directory] = payload
                results["valid"].extend(payload.get("valid", []))
                results["invalid"].extend(payload.get("invalid", []))
                results["partial"].extend(payload.get("partial", []))
            return normalize_validation_result({"status": "ok", **results}, directories)

        try:
            doc = await self._fetch_object_info()
        except Exception as exc:
            # Raise (don't return an empty-valid envelope): reconciliation
            # reads total_invalid/total_partial, so a returned dict with
            # empty lists would read as "all valid" for a dead ComfyUI —
            # the exact clean-sweep bug the container probes fixed by
            # raising on non-200. The reconciler catches this into
            # errors[] instead of silently passing.
            raise RuntimeError(f"Failed to query ComfyUI: {exc}") from exc
        by_directory: Dict[str, List[str]] = {}
        available: List[str] = []
        for directory in directories:
            found = self._iter_object_info_model_paths(doc, directory)
            by_directory[directory] = found
            available.extend(found)
        normalized = normalize_validation_result(
            {
                "status": "ok",
                "valid": sorted(set(available)),
                "invalid": [],
                "partial": [],
                "by_directory": by_directory,
            },
            directories,
        )
        # Container-compat keys: the legacy direct_url client answered an
        # ok() envelope with result/available/by_directory. Reconciliation
        # reads totals, but node/status consumers read available/result.
        normalized.setdefault("available", sorted(set(available)))
        normalized.setdefault("result", sorted(set(available)))
        return normalized

    async def validate_all_models(
        self,
        directories: Optional[List[str]] = None,
        delete_invalid: bool = False,
    ) -> Dict[str, Any]:
        """Single-call full-tree validation for reconciliation step 0.

        Via the agent's /validate-all-models when configured (mirroring the
        container probe: one POST, raise on non-200 with the upstream status
        and body as the diagnosis); otherwise the read-only /object_info
        aggregation over the standard tree.
        """
        _ = directories
        if not self._has_agent:
            return await self.validate_models(list(MODEL_DIRECTORIES))
        agent = self.get_agent_client()
        resp = await agent.post(
            "/validate-all-models",
            json={"delete_invalid": delete_invalid},
            timeout=300.0,
        )
        if resp.status_code in (401, 403):
            raise EngineAuthError(
                "Remote agent rejected credentials for /validate-all-models: "
                f"HTTP {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Remote agent /validate-all-models returned {resp.status_code}: "
                f"{resp.text[:200]}"
            )
        return normalize_validation_result(resp.json())

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        """Stream a file, preferring the agent sidecar when configured.

        The agent serves from its data dir via /get-file (model-dir metadata
        and preview sidecars that ComfyUI's /view 404s on); without an agent
        this streams ComfyUI's /view, as before.

        Upstream statuses are preserved, not collapsed: 404 reads as
        FileNotFoundError, anything else as RuntimeError carrying the
        status. The agent branch streams under a 600s timeout (the old
        remote_comfy client allowed 600s; the shared agent client defaults
        to 60s, which a multi-GB checkpoint read can exceed).

        Both branches are bounded by `get_file_size_cap()`: the caps exist
        so a wrong `path` cannot stream a whole weights file into the
        caller, and they have to agree because the caller cannot tell which
        branch served it.
        """
        from services.engines.base import get_file_size_cap

        max_bytes = get_file_size_cap()

        if self._has_agent:
            agent = self.get_agent_client()
            url = f"/get-file/{urllib.parse.quote(path, safe='/')}"
            async with agent.stream("GET", url, timeout=AGENT_GET_FILE_TIMEOUT_SECONDS) as resp:
                if resp.status_code == 404:
                    raise FileNotFoundError(f"File not found on remote agent: {path}")
                if resp.status_code == 413:
                    # Over the agent's own cap — surface it as the cap error
                    # it is, not a generic status the caller cannot act on.
                    raise FileTooLargeError(path, cap=get_file_size_cap())
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Remote agent /get-file returned {resp.status_code} for {path}"
                    )
                # Same ceiling the /view branch enforces: the agent 413s on
                # its own cap, but a mis-typed path into a weights file must
                # not stream unbounded into the caller when the agent's cap
                # is disabled (PROVIDER_GET_FILE_MAX_BYTES=0).
                declared = resp.headers.get("content-length")
                if max_bytes and declared and declared.isdigit() and int(declared) > max_bytes:
                    raise FileTooLargeError(path, size=int(declared), cap=max_bytes)

                async def _capped_agent() -> AsyncIterator[bytes]:
                    total = 0
                    async for chunk in resp.aiter_bytes(_STREAM_CHUNK_BYTES):
                        total += len(chunk)
                        if max_bytes and total > max_bytes:
                            raise FileTooLargeError(path, size=total, cap=max_bytes)
                        yield chunk

                async for chunk in _capped_agent():
                    yield chunk
            return

        client = self.get_http_client()
        req = client.build_request("GET", "/view", params={"filename": path})
        resp = await client.send(req, stream=True)
        if resp.status_code == 404:
            await resp.aread()
            await resp.aclose()
            raise FileNotFoundError(f"File not found on ComfyUI: {path}")
        if resp.status_code != 200:
            await resp.aread()
            await resp.aclose()
            raise RuntimeError(f"ComfyUI /view returned {resp.status_code} for {path}")

        declared = resp.headers.get("content-length")
        if max_bytes and declared and declared.isdigit() and int(declared) > max_bytes:
            await resp.aread()
            await resp.aclose()
            raise FileTooLargeError(path, size=int(declared), cap=max_bytes)

        async def _capped() -> AsyncIterator[bytes]:
            total = 0
            async with asyncio.timeout(AGENT_GET_FILE_TIMEOUT_SECONDS):
                async for chunk in resp.aiter_bytes(_STREAM_CHUNK_BYTES):
                    total += len(chunk)
                    if max_bytes and total > max_bytes:
                        raise FileTooLargeError(path, size=total, cap=max_bytes)
                    yield chunk

        try:
            async for chunk in _capped():
                yield chunk
        finally:
            await resp.aclose()

    async def delete_file(self, path: str) -> bool:
        """Delete a file via the agent sidecar; unsupported without one."""
        if not self._has_agent:
            logger.info("direct_comfy_delete_file_unsupported", provider_id=self.provider_id, path=path)
            return False
        try:
            agent = self.get_agent_client()
            resp = await agent.post("/delete-file", json={"path": path}, timeout=60.0)
            if resp.status_code in (401, 403):
                raise EngineAuthError(
                    f"Remote agent rejected credentials for /delete-file ({path}): "
                    f"HTTP {resp.status_code}",
                    status_code=resp.status_code,
                )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Remote agent /delete-file returned {resp.status_code} "
                    f"for {path}: {resp.text[:200]}"
                )
            # Adopt, rather than assume: the agent answers HTTP 200 with
            # {"success": false, ...} for a file it could not remove, and the
            # flag is in the body, not the status.
            payload = resp.json()
            return not (isinstance(payload, dict) and payload.get("success") is False)
        except (EngineAuthError, RuntimeError):
            # Fail fast like delete_model: a rejected credential reproduces on
            # every retry, so it must not read as a transient miss.
            #
            # This was `except (RuntimeError, Exception) as exc`, which needs
            # explaining: it is a one-element tuple. `RuntimeError` is a subclass
            # of `Exception`, so `(RuntimeError, Exception)` reduces to
            # `(RuntimeError,)` — the second entry only matches the exact class
            # `Exception`, never a subclass of it. The clause then did an
            # `isinstance(exc, (EngineAuthError, RuntimeError))` re-check to
            # decide what to re-raise, and the catch-all `except Exception` after
            # it swallowed both anyway. Measured against a 404 from the agent:
            # the raise never fired and the method answered `False` — identical
            # to "the file was already gone".
            raise
        except Exception as exc:
            logger.warning("direct_comfy_agent_delete_failed", provider_id=self.provider_id, path=path, error=str(exc))
            return False

    async def delete_model(self, path: str) -> bool:
        """Delete a model plus its sidecars via the agent /delete-model route.

        Parity with the legacy remote_comfy container reconcile path
        (remote_comfy/client.py delete_file closure POSTs /delete-model):
        /delete-model also removes ``.json``/``.preview.png``/``.sha256``
        sidecars, while /delete-file removes exactly one path. The
        in-process reconciler prefers this when present and falls back to
        delete_file otherwise. Unsupported without an agent.
        """
        if not self._has_agent:
            logger.info("direct_comfy_delete_model_unsupported", provider_id=self.provider_id, path=path)
            return False
        try:
            agent = self.get_agent_client()
            resp = await agent.post("/delete-model", json={"path": path}, timeout=60.0)
            if resp.status_code in (401, 403):
                raise EngineAuthError(
                    f"Remote agent rejected credentials for /delete-model ({path}): "
                    f"HTTP {resp.status_code}",
                    status_code=resp.status_code,
                )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Remote agent /delete-model returned {resp.status_code}: {resp.text[:200]}"
                )
            payload = resp.json()
            return not (isinstance(payload, dict) and payload.get("success") is False)
        except EngineAuthError:
            # Fail fast like delete_file: a rejected credential reproduces on
            # every retry, so it must not read as a transient miss.
            raise
        except Exception as exc:
            logger.warning("direct_comfy_agent_delete_model_failed", provider_id=self.provider_id, path=path, error=str(exc))
            return False

    async def upload_file(self, filename: str, content_base64: str, directory: str = "") -> bool:
        """Upload a file via the agent sidecar; unsupported without one."""
        if not self._has_agent:
            return False
        from services.engines.base import encoded_upload_over_cap

        # Encoded-length pre-check first (parity with BeamEngine): never
        # base64-decode a body the wire cap already rejects. Outside the try
        # so a fault in the guard is not swallowed into `return False`.
        if encoded_upload_over_cap(len(content_base64)):
            logger.warning(
                "direct_comfy_upload_over_cap",
                provider_id=self.provider_id,
                path=filename,
            )
            return False
        try:
            cap = get_upload_size_cap()
            if cap:
                try:
                    if len(base64.b64decode(content_base64, validate=False)) > cap:
                        logger.warning(
                            "direct_comfy_upload_over_cap",
                            provider_id=self.provider_id,
                            path=filename,
                            cap=cap,
                        )
                        return False
                except Exception:
                    # Undecodable body: let the agent reject it rather than
                    # failing the cap check on a guess.
                    pass
            agent = self.get_agent_client()
            resp = await agent.post(
                "/upload-file",
                json={"filename": filename, "content_base64": content_base64, "directory": directory},
                timeout=120.0,
            )
            if resp.status_code != 200:
                return False
            payload = resp.json()
            return not (isinstance(payload, dict) and payload.get("success") is False)
        except Exception as exc:
            logger.warning("direct_comfy_agent_upload_failed", provider_id=self.provider_id, error=str(exc))
            return False

    async def setup_models(self) -> bool:
        """Run the agent /setup pass; trivially true without an agent."""
        if not self._has_agent:
            return True
        try:
            agent = self.get_agent_client()
            resp = await agent.post("/setup", timeout=60.0)
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("direct_comfy_agent_setup_failed", provider_id=self.provider_id, error=str(exc))
            return False

    async def download_file(
        self,
        download_url: str,
        storage_path: str,
        token: Optional[str] = None,
        timeout: float = 1800.0,
    ) -> Dict[str, Any]:
        """Download one model via the agent /download-model route.

        Raises without an agent: plain ComfyUI has no download surface, and
        the in-process reconciler only calls this when manages_model_files
        (i.e. agent-backed) is true.
        """
        if not self._has_agent:
            raise RuntimeError("DirectComfyEngine has no agent sidecar: cannot download files")
        agent = self.get_agent_client()
        resp = await agent.post(
            "/download-model",
            json={
                "url": download_url,
                "path": storage_path,
                "token": token if token is not None else self.download_token_for_url(download_url),
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Agent download failed with status {resp.status_code}: {resp.text[:200]}")
        result = resp.json() if resp.content else {}
        if isinstance(result, dict) and result.get("status") == "error":
            raise RuntimeError(result.get("message", "Download failed"))
        return result if isinstance(result, dict) else {"status": "ok"}

    async def inference(
        self,
        workflow: Dict[str, Any],
        job_id: Optional[str] = None,
        use_snapshot: bool = True,
        timeout: float = 3600.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute an inference workflow by connecting to ComfyUI's WebSocket and dispatching /prompt.
        """
        timeout = clamp_timeout(timeout)
        # Fresh client id per attempt (parity with workflow_executor which
        # mints uuid4 per execute call): retries of the same job must not
        # share a clientId on the ComfyUI side. job_id stays the event key.
        import uuid

        client_id = f"direct_{uuid.uuid4().hex[:12]}"
        parsed = urllib.parse.urlparse(self.comfy_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        netloc = parsed.netloc or "127.0.0.1:8188"
        ws_url = f"{ws_scheme}://{netloc}/ws?clientId={client_id}"

        logger.info("direct_comfy_inference_start", provider_id=self.provider_id, job_id=job_id, ws_url=ws_url)
        yield {"event": "started", "job_id": job_id, "provider_id": self.provider_id}

        # Fast path: a cancel that arrived before dispatch must not wait on
        # socket or stall timeouts.
        if job_id and job_id in self._cancelled_jobs:
            self._cancelled_jobs.discard(job_id)
            yield {"event": "cancelled", "job_id": job_id, "message": "Job cancelled"}
            return

        client = self.get_http_client()
        extra_headers = self._headers.copy()

        try:
            async with _ws_connect_with_retry(ws_url, extra_headers) as ws:
                # Submit workflow via POST /prompt
                #
                # Unwrap the job envelope when there is one. Image jobs carry
                # the bare graph, but `tts_workflow_builder` returns
                # `{"prompt": {...}, "client_id": ..., "type": "tts"}` and
                # `job_runner` hands `job.workflow` through verbatim — so
                # posting `workflow` as the prompt sent ComfyUI a graph whose
                # node keys were `prompt`, `client_id` and `type`. Those are
                # not integers, `validate_prompt` rejects the lot, and every
                # `direct_tts` job failed 400 on a rig that was working
                # perfectly. The Modal twin has unwrapped this since the start
                # (`modal/tts/app.py`: `workflow_json.get("prompt",
                # workflow_json)`); this engine never did.
                graph = workflow.get("prompt") if isinstance(workflow.get("prompt"), dict) else workflow
                prompt_resp = await client.post(
                    "/prompt",
                    json={"prompt": graph, "client_id": client_id},
                    timeout=30.0,
                )
                if prompt_resp.status_code != 200:
                    err_msg = f"ComfyUI prompt rejected: {prompt_resp.text}"
                    logger.error("direct_comfy_prompt_rejected", provider_id=self.provider_id, error=err_msg)
                    yield {
                        "event": "failed",
                        "job_id": job_id,
                        "message": err_msg,
                        "retryable": retryable_for_status(prompt_resp.status_code),
                    }
                    return

                data = prompt_resp.json()
                # A 200 carrying node_errors means the graph was rejected
                # for a node, not accepted: fail permanent, like the old
                # workflow_executor did, rather than waiting 3600s on a
                # prompt that will never run.
                if data.get("node_errors"):
                    err_msg = f"ComfyUI node validation failed: {data.get('node_errors')}"
                    logger.error("direct_comfy_node_errors", provider_id=self.provider_id, error=str(data.get('node_errors'))[:500])
                    yield {"event": "failed", "job_id": job_id, "message": err_msg, "retryable": False}
                    return
                prompt_id = data.get("prompt_id")
                if not prompt_id:
                    err_msg = data.get("error", "No prompt_id returned by ComfyUI")
                    yield {"event": "failed", "job_id": job_id, "message": str(err_msg), "retryable": True}
                    return
                # Remember which prompt belongs to this job. `/interrupt` is
                # global to the ComfyUI instance, so it is the frame *arriving
                # interval*, not the flag, that says whether THIS prompt died;
                # a sibling job's interrupt must not be reported as this one.
                if job_id:
                    self._job_prompt_ids[job_id] = prompt_id

                # Last node seen: the stall message names it, as the old
                # workflow_executor did, so a hung graph is diagnosable.
                last_node: Optional[str] = None

                # Listen to WebSocket messages until execution completes or times out
                async with asyncio.timeout(timeout):
                    while True:
                        if job_id and job_id in self._cancelled_jobs:
                            self._cancelled_jobs.discard(job_id)
                            try:
                                await client.post("/interrupt", timeout=5.0)
                            except Exception as exc:
                                logger.warning("direct_comfy_interrupt_failed", provider_id=self.provider_id, job_id=job_id, error=str(exc))
                            yield {"event": "cancelled", "job_id": job_id, "message": "Job cancelled"}
                            return
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=self.stall_timeout)
                        except asyncio.TimeoutError:
                            # Verify if prompt completed in history before giving up
                            # (10s probe, parity with workflow_executor._get_history).
                            hist_resp = await client.get(f"/history/{prompt_id}", timeout=10.0)
                            if hist_resp.status_code == 200 and prompt_id in hist_resp.json():
                                break
                            stall_message = f"Execution stalled after {int(self.stall_timeout)}s without updates"
                            if last_node is not None:
                                stall_message += f" (last node: {last_node})"
                            yield {
                                "event": "failed",
                                "job_id": job_id,
                                "message": stall_message,
                                "retryable": True,
                                "code": 408,
                                "details": {
                                    "reason": "workflow_stalled",
                                    "prompt_id": prompt_id,
                                    "last_node": last_node,
                                    "stall_timeout_seconds": int(self.stall_timeout),
                                },
                            }
                            return

                        if not isinstance(msg, str):
                            continue

                        try:
                            payload = json.loads(msg)
                        except json.JSONDecodeError:
                            continue

                        msg_type = payload.get("type")
                        msg_data = payload.get("data", {})
                        msg_prompt_id = msg_data.get("prompt_id")

                        if msg_type == "executing":
                            node = msg_data.get("node")
                            if node is None and msg_prompt_id == prompt_id:
                                # Completed
                                break
                            if msg_prompt_id == prompt_id and node is not None:
                                last_node = str(node)
                                yield {"event": "node", "job_id": job_id, "node": str(node)}

                        elif msg_type == "execution_success":
                            # The terminal frame, and the one this loop
                            # actually terminates on.
                            #
                            # ComfyUI no longer ends a prompt with
                            # `executing {node: null}` — `execution.py` emits
                            # `executing` only while a real node is running and
                            # finishes with `execution_success`. The old loop
                            # had only the former as an exit, so EVERY job ran
                            # to the `stall_timeout` (300s) before the history
                            # probe below broke the loop — a five-minute tax on
                            # every generation — and any job slower than the
                            # stall timeout was reported `failed /
                            # workflow_stalled / retryable` while ComfyUI was
                            # still happily executing it. Worse, the retry
                            # re-ran a workflow that had already succeeded.
                            if msg_prompt_id == prompt_id:
                                break

                        elif msg_type == "execution_interrupted":
                            # An out-of-band interrupt. Falling through to the
                            # history probe reports it as `completed` with zero
                            # outputs, which finalises green having produced
                            # nothing.
                            if msg_prompt_id == prompt_id:
                                yield {"event": "cancelled", "job_id": job_id, "message": "Prompt interrupted"}
                                return

                        elif msg_type == "progress":
                            if msg_prompt_id is None or msg_prompt_id == prompt_id:
                                val = msg_data.get("value")
                                max_val = msg_data.get("max") or 0
                                pct = round(val / max_val * 100) if (val is not None and max_val) else val
                                yield {"event": "progress", "job_id": job_id, "value": pct, "value_unit": "percent"}

                        elif msg_type == "execution_cached":
                            if msg_prompt_id == prompt_id:
                                nodes = msg_data.get("nodes", [])
                                yield {"event": "cached_nodes", "job_id": job_id, "nodes": [str(n) for n in nodes]}

                        elif msg_type == "execution_error":
                            yield {"event": "failed", "job_id": job_id, "message": str(msg_data), "retryable": False}
                            return

                # Re-check the cancel flag before treating a broken loop as
                # "Completed". `cancel_job` sets the flag and `_on_cancel` POSTs
                # /interrupt, which makes ComfyUI emit `executing {node: null}` —
                # the same frame a finished prompt emits. That hits the `break`
                # above and falls straight through to the history fetch and
                # `completed`, so a cancelled job was finalised as a SUCCESS with
                # its outputs persisted, while the caller believed it had stopped
                # the provider. The loop-top check never runs again after a break.
                if job_id and job_id in self._cancelled_jobs:
                    self._cancelled_jobs.discard(job_id)
                    yield {"event": "cancelled", "job_id": job_id, "message": "Job cancelled"}
                    return
                if job_id and self._interrupted_prompts.get(prompt_id) == job_id:
                    # This job's own interrupt arrived, but the flag was already
                    # consumed by the loop-top check on a previous iteration.
                    self._interrupted_prompts.pop(prompt_id, None)
                    yield {"event": "cancelled", "job_id": job_id, "message": "Job cancelled"}
                    return

                # Completed: fetch results from /history/{prompt_id}
                hist_resp = await client.get(f"/history/{prompt_id}", timeout=10.0)
                if hist_resp.status_code != 200:
                    yield {"event": "failed", "job_id": job_id, "message": f"Failed to fetch history for prompt {prompt_id}", "retryable": True}
                    return

                history_doc = hist_resp.json().get(prompt_id, {})
                if not history_doc:
                    yield {"event": "failed", "job_id": job_id, "message": f"Prompt not found in history for {prompt_id}", "retryable": False}
                    return
                # Collect image refs first, then fetch concurrently preserving
                # order (parity with workflow_executor._collect_images_via_view_api
                # gather): a 4-image batch must not pay 4 sequential round trips.
                refs: list[tuple[str, str, str]] = []
                for node_id, node_output in history_doc.get("outputs", {}).items():
                    for idx, img in enumerate(node_output.get("images", [])):
                        fn = img.get("filename")
                        if not fn:
                            continue
                        refs.append((fn, img.get("subfolder", ""), img.get("type", "output")))

                async def _fetch_view(ref: tuple[str, str, str]) -> dict[str, Any] | None:
                    fn, sub, f_type = ref
                    view_url = f"/view?filename={urllib.parse.quote(fn)}&subfolder={urllib.parse.quote(sub)}&type={urllib.parse.quote(f_type)}"
                    img_resp = await client.get(view_url, timeout=30.0)
                    if img_resp.status_code != 200:
                        return None
                    b64_data = base64.b64encode(img_resp.content).decode("utf-8")
                    # Canonical artifact keys, matching what the
                    # container's translate_task_events produced:
                    # type "image", storage type as image_type, and
                    # the base64 marker so the reducer decodes
                    # instead of treating it as an on-disk file.
                    return {
                        "type": "image",
                        "data": b64_data,
                        "filename": fn,
                        "subfolder": sub,
                        "image_type": f_type,
                        "_base64_encoded": True,
                    }

                fetched = await asyncio.gather(*[_fetch_view(r) for r in refs]) if refs else []
                outputs = [a for a in fetched if a is not None]

                # Audio is not images. `SaveAudio` / `PreviewAudio` publish
                # `outputs[<node>]["audio"]` and never `images`, so a TTS
                # history document walked for images yields nothing at all:
                # `completed` with `outputs: []`, which finalises the job green
                # having produced no clip.
                #
                # Emitted as a REF, not fetched and inlined. The inline shape
                # routes through `build_job_outputs`, which opens every payload
                # with PIL and cannot write a WAV; the ref shape is what
                # `ModalTTSEngine` returns and what `_fetch_remote_tts_outputs`
                # was written for — it pulls the bytes through this engine's own
                # `get_file_stream`, which for a direct rig is `/view` and
                # defaults `type=output`, so the subfolder resolves without an
                # `output/` prefix to get wrong.
                if not outputs:
                    audio_refs: list[dict[str, Any]] = []
                    for node_output in history_doc.get("outputs", {}).values():
                        for clip in node_output.get("audio", []) or []:
                            fn = clip.get("filename")
                            if fn:
                                audio_refs.append({
                                    "type": "audio",
                                    "filename": fn,
                                    "subfolder": clip.get("subfolder", ""),
                                    "image_type": clip.get("type", "output"),
                                })
                    outputs = audio_refs

                yield {"event": "completed", "job_id": job_id, "outputs": outputs, "details": history_doc.get("status", {})}

        except TimeoutError:
            yield {"event": "failed", "job_id": job_id, "message": f"Inference timed out after {int(timeout)}s", "retryable": True}
        except asyncio.CancelledError:
            # Parity with workflow_executor: an outer cancellation still
            # best-efforts POST /interrupt so the orphaned ComfyUI run does
            # not keep executing, then re-raises for structured teardown.
            try:
                await client.post("/interrupt", timeout=5.0)
            except Exception:
                pass
            raise
        except Exception as exc:
            # A dropped socket means the run either died or is orphaned on
            # the far side: signal a cancel so the ComfyUI worker does not
            # keep executing a prompt nobody will collect, like the old
            # workflow_executor's 1006 path did. Preserve code/details parity
            # (stall 408 above, close 1006 here, generic 500) so reducers
            # keying on code/details.reason keep signal.
            job_ctx = job_id
            if job_ctx and self.is_job_active(job_ctx):
                client = self.get_http_client()
                try:
                    await client.post("/interrupt", timeout=5.0)
                except Exception:
                    pass
            logger.exception("direct_comfy_inference_exception", provider_id=self.provider_id, job_id=job_id, error=str(exc))
            code = getattr(exc, "code", None)
            is_close = isinstance(exc, websockets.exceptions.ConnectionClosed) if hasattr(websockets, "exceptions") else False
            if is_close:
                yield {
                    "event": "failed",
                    "job_id": job_id,
                    "message": f"Direct ComfyUI inference error: {exc}",
                    "retryable": True,
                    "code": int(code) if isinstance(code, int) else 1006,
                    "details": {"reason": "websocket_closed", "prompt_id": locals().get("prompt_id")},
                }
            else:
                yield {
                    "event": "failed",
                    "job_id": job_id,
                    "message": f"Direct ComfyUI inference error: {exc}",
                    "retryable": False,
                    "code": int(code) if isinstance(code, int) else 500,
                    "details": {"reason": "websocket_error", "prompt_id": locals().get("prompt_id")},
                }
        finally:
            # `_job_prompt_ids` and `_interrupted_prompts` are per-job scratch:
            # without this they grow for the life of the process, one entry per
            # job ever run through this engine.
            if job_id:
                prompt_id = self._job_prompt_ids.pop(job_id, None)
                if prompt_id:
                    self._interrupted_prompts.pop(prompt_id, None)


class DirectTTSEngine(DirectComfyEngine):
    """A ComfyUI rig that serves speech.

    Before this, TTS-on-a-ComfyUI-rig was not a distinct thing: a `tts`-worker
    provider had to be registered as `direct_url` and was then counted as image
    capacity by the old `worker_type != "llm"` pool rule. It is a separate
    provider type now — the same ComfyUI protocol, a different category, and no
    model tree of its own.

    The protocol is genuinely identical (WebSocket prompt, progress frames,
    `completed` with output paths), so this subclasses `DirectComfyEngine` rather
    than copying it. What differs:
      * `manages_model_files` is False — a speech rig's voices come from its node
        graph, so there are no checkpoints to reconcile and `list_models`
        answers the voice catalogue instead.
      * `list_models()` (no argument) returns voices, the same static catalogue
        the provider route serves, so the voice picker works for a rig whose
        voice list cannot be discovered over the API.
    """

    manages_model_files: bool = False
    supports_discovery_reconcile: bool = False

    #: Kokoro's built-in voices. A ComfyUI speech rig exposes them through its
    #: own nodes, so this is the catalogue for `list_models` rather than a
    #: discovery result. Same list `api/routes/providers/crud.py` serves for
    #: `modal_tts`, so the voice picker is identical across TTS providers.
    DEFAULT_VOICES: tuple[dict[str, str], ...] = (
        {"name": "af_bella", "id": "af_bella", "type": "voice", "gender": "female", "accent": "American"},
        {"name": "af_sarah", "id": "af_sarah", "type": "voice", "gender": "female", "accent": "American"},
        {"name": "am_adam", "id": "am_adam", "type": "voice", "gender": "male", "accent": "American"},
        {"name": "am_michael", "id": "am_michael", "type": "voice", "gender": "male", "accent": "American"},
        {"name": "bf_emma", "id": "bf_emma", "type": "voice", "gender": "female", "accent": "British"},
        {"name": "bf_isabella", "id": "bf_isabella", "type": "voice", "gender": "female", "accent": "British"},
        {"name": "bm_george", "id": "bm_george", "type": "voice", "gender": "male", "accent": "British"},
        {"name": "bm_lewis", "id": "bm_lewis", "type": "voice", "gender": "male", "accent": "British"},
    )

    async def list_models(self, directory: str = "voices") -> list[dict[str, Any]]:
        """Voices, not checkpoints.

        The base signature takes a directory; a TTS rig has no model tree, so any
        directory argument is answered with the voice catalogue rather than with
        an empty list a caller cannot distinguish from a broken rig.

        DISCOVERED FROM THE RIG, which is what this method's own docstring has
        always claimed. It used to return `DEFAULT_VOICES` — Kokoro ids
        (`af_bella`, `bm_george`, ...) — while the graph this engine drives is
        built from `QwenTTSSpeak`, whose `voice` input is a Qwen3-TTS speaker
        enum. Two taxonomies: every id the picker offered was rejected by the
        node it fed. The names were also duplicated verbatim in
        `api/routes/providers/crud.py`, so the mistake was in two places.

        `/object_info` carries the node's input schema, so the real enum is one
        request away. The static list survives only as a fallback for a rig that
        does not answer, and it says so via `discovered: False` rather than
        pretending to be what the node accepts.
        """
        discovered = await self._discover_voices()
        if discovered:
            return discovered
        return [
            {**dict(voice), "discovered": False}
            for voice in self.DEFAULT_VOICES
        ]

    async def _discover_voices(self) -> list[dict[str, Any]]:
        """The `voice` enum the rig's `QwenTTSSpeak` node actually accepts."""
        try:
            doc = await self.get_object_info()
        except Exception as exc:
            logger.info(
                "direct_tts_voice_discovery_failed",
                provider_id=self.provider_id,
                error=str(exc),
            )
            return []

        node = (doc or {}).get(NODE_SPEAK)
        if not isinstance(node, dict):
            return []
        required = (node.get("input") or {}).get("required") or {}
        spec = required.get("voice")
        if not isinstance(spec, (list, tuple)) or len(spec) < 2:
            return []
        # ComfyUI's combo widgets are [name, default, {options: [...]}].
        options = spec[2].get("options") if isinstance(spec[2], dict) else spec[1]
        if not isinstance(options, (list, tuple)):
            return []
        return [
            {
                "name": str(option),
                "id": str(option),
                "type": "voice",
                "discovered": True,
            }
            for option in options
        ]

    async def check_health(self) -> dict[str, Any]:
        """Health of the rig itself — the base already probes ComfyUI directly."""
        try:
            return await super().check_health()
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "status": "rejected",
                "provider_id": self.provider_id,
                "healthy": False,
                "reason": "comfyui_unreachable",
                "message": str(exc),
            }
