"""
In-Process Beam Execution Engine.

Parity twin of the ``beam`` container client
(provider_containers/image_worker/engines/beam/client.py): GPU inference
over a websocket to the Beam realtime endpoint, and model lifecycle against
the Beam storage app over REST — without an intermediate container.
"""

import asyncio
import base64
import json
import os
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
import websockets

from config import env_positive_int
from infrastructure.logging import get_logger
from services.engines.base import (
    TERMINAL_EVENTS,
    EngineAuthError,
    FileTooLargeError,
    InProcessEngine,
    clamp_timeout,
    _files_from,
    get_file_size_cap,
    get_upload_size_cap,
    is_auth_error,
    normalize_validation_result,
    translate_legacy_image_update,
)

logger = get_logger("beam_engine")

# Through the shared tolerant reader: `int(os.getenv(...))` turns a typo in a
# deployment env file into a boot crash for the whole backend.
_WS_MAX_SIZE_MB = env_positive_int(os.getenv("WS_MAX_SIZE_MB"), 20)
_WS_OPEN_TIMEOUT = env_positive_int(os.getenv("WS_OPEN_TIMEOUT"), 120)
_STREAM_CHUNK_BYTES = 1024 * 1024  # 1 MiB


def _max_background_tasks() -> int:
    """Bound for concurrent fire-and-forget downloads, mirroring the
    container's MAX_BACKGROUND_TASKS (provider_core.background, default 16,
    env PROVIDER_MAX_BACKGROUND_TASKS). The container answered 429
    failed(retryable=True) past saturation; the engine answers a busy dict
    with the same retryable marker."""
    try:
        return env_positive_int(os.getenv("PROVIDER_MAX_BACKGROUND_TASKS"), 16)
    except (TypeError, ValueError):
        return 16


class BeamEngine(InProcessEngine):
    """In-process compute engine for Beam serverless workers."""

    manages_model_files = True

    def __init__(
        self,
        provider_id: str,
        api_key: str,
        workspace_id: str = "",
        gpu_url: str = "",
        storage_url: str = "",
        download_url: str = "",
        extractor_url: str = "",
        hf_token: str = "",
        civitai_token: str = "",
        gpu_type: str = "RTX4090",
        ws_max_size_mb: int = _WS_MAX_SIZE_MB,
        ws_open_timeout: int = _WS_OPEN_TIMEOUT,
    ):
        super().__init__(provider_id)
        self.api_key = (api_key or "").strip()
        self.workspace_id = (workspace_id or "").strip()
        self.gpu_url = (gpu_url or "").strip().rstrip("/")
        self.storage_url = (storage_url or "").strip().rstrip("/")
        self.download_url = (download_url or "").strip().rstrip("/") or self.storage_url
        # NOT `or self.storage_url`. The storage app serves no `/object_info`,
        # so that fallback turned a missing field into a bare 404 from the
        # wrong deployment — indistinguishable, from the node catalogue, from
        # "ComfyUI has no nodes". `registry.py` now declares `extractor_url` as
        # a form field so it can actually be entered; when it is absent the
        # caller gets told which deployment is missing.
        self.extractor_url = (extractor_url or "").strip().rstrip("/")
        self.hf_token = hf_token or os.getenv("HF_TOKEN", "")
        self.civitai_token = civitai_token or os.getenv("CIVITAI_TOKEN", "")
        self.gpu_type = gpu_type
        self.ws_max_size_mb = max(1, int(ws_max_size_mb))
        self.ws_open_timeout = max(1, int(ws_open_timeout))
        self._http: Optional[httpx.AsyncClient] = None
        self._download_slots = asyncio.Semaphore(_max_background_tasks())
        self._background_tasks: set = set()

    def _headers(self) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.workspace_id:
            headers["X-Beam-Workspace-Id"] = self.workspace_id
        return headers

    def get_http_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=60.0, headers=self._headers())
        return self._http

    async def close(self) -> None:
        if self._background_tasks:
            tasks = list(self._background_tasks)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._background_tasks.clear()
        if self._http and not self._http.is_closed:
            await self._http.aclose()
    async def check_health(self) -> Dict[str, Any]:
        """Local-only check: never ping the serverless deployment.

        A probe bills GPU time (VISION #4), so health only verifies that the
        engine is configured — mirroring the beam container client. Missing
        config is unhealthy without a retryable marker: it will not fix
        itself, and a 503 read as retryable fails the job over to another
        provider.
        """
        t0 = time.monotonic()
        missing = []
        if not self.api_key:
            missing.append("BEAM_API_KEY")
        if not self.gpu_url:
            missing.append("BEAM_GPU_URL")
        if not self.storage_url:
            missing.append("BEAM_STORAGE_URL")
        latency_ms = round((time.monotonic() - t0) * 1000, 2)
        if missing:
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": latency_ms,
                "engine": "beam",
                "error": f"provider is not configured (missing: {', '.join(missing)})",
                "retryable": False,
            }
        return {
            "status": "healthy",
            "provider_id": self.provider_id,
            "ready": True,
            "latency_ms": latency_ms,
            "engine": "beam",
            "gpu_type": self.gpu_type,
        }

    async def inference(
        self,
        workflow: Dict[str, Any],
        job_id: Optional[str] = None,
        use_snapshot: bool = True,
        timeout: float = 3600.0,
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Execute a workflow against the Beam GPU realtime endpoint.

        ``use_snapshot`` is accepted and ignored: Beam's snapshot deployment
        is a different app, chosen at the provider level, not per request.
        """
        _ = use_snapshot
        logger.info("beam_inference_start", provider_id=self.provider_id, job_id=job_id)
        yield {"event": "started", "job_id": job_id, "provider_id": self.provider_id}

        # Same floor the container applied: a non-positive timeout clamps to
        # 1s instead of failing every poll immediately (beam/client.py:114).
        # clamp_timeout also falls back to default on garbage input (parity
        # with Modal/Direct) instead of raising ValueError.
        timeout = clamp_timeout(timeout, default=3600.0)

        async def _is_cancelled() -> bool:
            return bool(job_id and job_id in self._cancelled_jobs)

        async def _take_cancelled() -> bool:
            if await _is_cancelled():
                self._cancelled_jobs.discard(job_id or "")
                return True
            return False

        if await _take_cancelled():
            yield {"event": "cancelled", "job_id": job_id, "message": "Job cancelled"}
            return

        try:
            async with asyncio.timeout(timeout):
                queue: asyncio.Queue = asyncio.Queue()

                async def _fetcher() -> None:
                    try:
                        headers = {"Authorization": f"Bearer {self.api_key}"}
                        try:
                            ws_ctx = websockets.connect(
                                self.gpu_url,
                                max_size=self.ws_max_size_mb * 1024 * 1024,
                                additional_headers=headers,
                                open_timeout=self.ws_open_timeout,
                            )
                        except TypeError:
                            # websockets version drift: older/newer builds
                            # name the kwarg extra_headers (same fallback
                            # DirectComfyEngine uses).
                            ws_ctx = websockets.connect(
                                self.gpu_url,
                                max_size=self.ws_max_size_mb * 1024 * 1024,
                                extra_headers=headers,
                                open_timeout=self.ws_open_timeout,
                            )
                        async with ws_ctx as ws:
                            # The token travels in the payload as well as the
                            # header: `comfy_gpu` is a @realtime handler whose
                            # request-context object is not readable in every
                            # deployed SDK version. The endpoint bills GPU time
                            # and fails closed without one.
                            await ws.send(json.dumps({"token": self.api_key, "workflow": workflow}))
                            async for message in ws:
                                if await _is_cancelled():
                                    return
                                await queue.put(message)
                            await queue.put(None)
                    except Exception as exc:
                        await queue.put(exc)

                task = asyncio.create_task(_fetcher())
                # Cancelling the fetcher exits `async with ws_ctx` (above), which
                # closes the websocket to the Beam endpoint — a real upstream stop,
                # not just a local flag. Without this a cancel is only seen between
                # stream frames, so a quiet run kept the billed GPU-side handler
                # running until the next frame or the caller's timeout.
                self.register_abort(job_id, task.cancel)
                try:
                    while True:
                        try:
                            item = await asyncio.wait_for(queue.get(), timeout=2.0)
                        except asyncio.TimeoutError:
                            if await _is_cancelled():
                                task.cancel()
                                self._cancelled_jobs.discard(job_id or "")
                                yield {"event": "cancelled", "job_id": job_id, "message": "Job cancelled"}
                                return
                            continue

                        if item is None:
                            break
                        if isinstance(item, Exception):
                            raise item

                        message = item.decode("utf-8") if isinstance(item, bytes) else item

                        if await _is_cancelled():
                            task.cancel()
                            self._cancelled_jobs.discard(job_id or "")
                            yield {"event": "cancelled", "job_id": job_id, "message": "Job cancelled"}
                            return

                        try:
                            payload = json.loads(message)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        # Canonical TaskEvents pass through with job_id
                        # filled; the Beam app's legacy {"status": ...}
                        # frames translate to the same shapes the
                        # container's translate_task_events produced.
                        # Anything without progress (keep-alives, unknown
                        # shapes) is dropped, not relayed raw.
                        event = translate_legacy_image_update(payload, job_id)
                        if event is None:
                            continue
                        yield event
                        if event.get("event") in TERMINAL_EVENTS:
                            task.cancel()
                            return
                finally:
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
        except TimeoutError:
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"Inference timed out after {int(timeout)}s",
                "retryable": True,
            }
        except websockets.exceptions.ConnectionClosedError as exc:
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"Websocket connection closed with error: {exc}",
                "retryable": True,
                "code": 1006,
            }
        except websockets.exceptions.ConnectionClosed as exc:
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"Websocket connection closed: {exc}",
                "retryable": True,
                "code": 1006,
            }
        except Exception as exc:
            logger.error("beam_inference_error", provider_id=self.provider_id, job_id=job_id, error=str(exc))
            if is_auth_error(exc):
                # Bad credentials fail fast: same rule as ModalEngine
                # (modal_engine.py) — failing over only spends a retry
                # reproducing the same rejection.
                yield {
                    "event": "failed",
                    "job_id": job_id,
                    "message": f"Beam authentication failed: {exc}",
                    "retryable": False,
                }
                return
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"Beam inference error: {exc}",
                "retryable": True,
            }

    async def list_models(self, directory: str, timeout: float = 60.0) -> List[Dict[str, Any]]:
        """List models in a directory on the storage app.

        The default budget mirrors the container public route
        (beam/client.py ``timeout=60.0``) so UI scans fail fast; the
        reconciler passes ``timeout=3600.0`` explicitly for the cold-storage
        fan-out (container reconcile _fetch_dir wait_for).
        401/403 raises EngineAuthError; anything else also raises (after
        the modal/beam legacy behaviour of erroring on non-200) so a cold
        storage app or 5xx never reads as an empty directory — that is
        the misread that made reconciliation clean-sweep expected files.
        Callers that scan fan out per directory already catch Exception.
        """
        client = self.get_http_client()
        try:
            resp = await client.post(
                f"{self.storage_url}/list-models", json={"directory": directory}, timeout=timeout
            )
            if resp.status_code in (401, 403):
                raise EngineAuthError(
                    f"Beam storage rejected credentials for /list-models ({directory}): "
                    f"HTTP {resp.status_code}: {resp.text[:200]}",
                    status_code=resp.status_code,
                )
            if resp.status_code == 200:
                return _files_from(resp.json())
            raise RuntimeError(f"Beam list-models failed for {directory}: HTTP {resp.status_code}")
        except EngineAuthError:
            raise
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Beam list-models failed for {directory}: {exc}") from exc

    async def get_object_info(self) -> Dict[str, Any]:
        """Fetch `/object_info` from the extractor deployment.

        `comfyui-extractor` serves exactly this and nothing else — it is a
        separate deployment precisely because the node catalogue is CPU work
        that must not boot a GPU — so there is no sensible fallback. Saying so
        beats a 404 from the storage app, which read as "ComfyUI has no nodes".
        """
        if not self.extractor_url:
            raise RuntimeError(
                f"Beam provider {self.provider_id!r} has no extractor_url; deploy "
                f"comfyui-extractor and set it on the provider row (registry.py "
                f"exposes it as the 'Extractor REST URL' field)"
            )
        client = self.get_http_client()
        try:
            resp = await client.get(f"{self.extractor_url}/object_info", timeout=120.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (401, 403):
                raise EngineAuthError(
                    f"Beam extractor rejected credentials: HTTP {status}",
                    status_code=status,
                ) from exc
            raise
        doc = resp.json()
        return doc if isinstance(doc, dict) else {}

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        """Stream a file from the storage app without buffering it whole.

        Mirrors the container's get_file: a declared Content-Length over the
        cap fails fast with 413 semantics (FileNotFoundError carries the 404,
        over-cap is FileTooLargeError, anything else is a RuntimeError); the base64-JSON variant is decoded
        under the cap; otherwise bytes are relayed with a cumulative ceiling.
        """
        http_client = self.get_http_client()
        max_bytes = get_file_size_cap()
        req = http_client.build_request(
            "POST", f"{self.storage_url}/get-file", json={"path": path}, timeout=120.0
        )
        resp = await http_client.send(req, stream=True)
        try:
            if resp.status_code != 200:
                await resp.aread()
                if resp.status_code == 404:
                    raise FileNotFoundError(f"File not found on Beam storage: {path}")
                if resp.status_code in (401, 403):
                    raise EngineAuthError(
                        f"Beam storage rejected credentials for /get-file ({path}): "
                        f"HTTP {resp.status_code}",
                        status_code=resp.status_code,
                    )
                raise RuntimeError(f"Beam storage returned {resp.status_code} for {path}")

            content_type = str(resp.headers.get("content-type", ""))
            declared = resp.headers.get("content-length")
            try:
                declared_len: Optional[int] = int(declared) if declared is not None else None
            except (TypeError, ValueError):
                declared_len = None
            if max_bytes and declared_len is not None and declared_len > max_bytes:
                raise FileTooLargeError(path, size=declared_len, cap=max_bytes)

            if "json" in content_type.lower():
                body = await resp.aread()
                if max_bytes and len(body) > max_bytes:
                    raise FileTooLargeError(path, size=len(body), cap=max_bytes)
                try:
                    payload = json.loads(body)
                except ValueError:
                    yield bytes(body)
                    return
                if isinstance(payload, dict) and payload.get("content_base64"):
                    decoded = base64.b64decode(payload["content_base64"])
                    if max_bytes and len(decoded) > max_bytes:
                        raise FileTooLargeError(path, size=len(decoded), cap=max_bytes)
                    yield decoded
                    return
                yield bytes(body)
                return

            total = 0
            async for chunk in resp.aiter_bytes(_STREAM_CHUNK_BYTES):
                total += len(chunk)
                if max_bytes and total > max_bytes:
                    raise FileTooLargeError(path, size=total, cap=max_bytes)
                yield chunk
        finally:
            await resp.aclose()

    async def _delete_via(self, endpoint: str, path: str) -> bool:
        client = self.get_http_client()
        try:
            resp = await client.post(
                f"{self.storage_url}/{endpoint}", json={"path": path}, timeout=60.0
            )
            if resp.status_code in (401, 403):
                raise EngineAuthError(
                    f"Beam storage rejected credentials for /{endpoint} ({path}): "
                    f"HTTP {resp.status_code}",
                    status_code=resp.status_code,
                )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Beam storage /{endpoint} returned {resp.status_code} "
                    f"for {path}: {resp.text[:200]}"
                )
            # Adopt, rather than assume: the storage app answers HTTP 200 with
            # success:false for a file it could not remove.
            payload = resp.json()
            return not (isinstance(payload, dict) and payload.get("success") is False)
        except (EngineAuthError, RuntimeError):
            raise
        except Exception as exc:
            logger.warning("beam_delete_failed", provider_id=self.provider_id, path=path, endpoint=endpoint, error=str(exc))
            return False

    async def delete_file(self, path: str) -> bool:
        """Delete exactly one path via /delete-file (no sidecars).

        Parity with container beam_app /delete-file (removes only the resolved
        path). Reconciliation orphan cleanup wants sidecars too — it calls
        delete_model() below which hits /delete-model.
        """
        return await self._delete_via("delete-file", path)

    async def delete_model(self, path: str) -> bool:
        """Delete a model plus its sidecars via /delete-model.

        Mirrors the container reconcile path (beam/client.py): /delete-model
        also removes ``.json``/``.preview.png``/``.sha256`` sidecars.
        """
        return await self._delete_via("delete-model", path)

    async def upload_file(self, filename: str, content_base64: str, directory: str = "") -> bool:
        from services.engines.base import encoded_upload_over_cap

        # Encoded-length pre-check first (parity with the container's
        # content-length 413 pre-check): never base64-decode a body the wire
        # cap already rejects. It sits outside the try so a fault in the
        # guard itself is not swallowed into a generic `return False`.
        if encoded_upload_over_cap(len(content_base64)):
            logger.warning("beam_upload_over_cap", provider_id=self.provider_id, path=filename)
            return False
        client = self.get_http_client()
        try:
            cap = get_upload_size_cap()
            if cap and len(base64.b64decode(content_base64, validate=False)) > cap:
                logger.warning("beam_upload_over_cap", provider_id=self.provider_id, path=filename, cap=cap)
                return False
            resp = await client.post(
                f"{self.storage_url}/upload-file",
                json={"filename": filename, "content_base64": content_base64, "directory": directory},
                timeout=120.0,
            )
            if resp.status_code != 200:
                return False
            payload = resp.json()
            return not (isinstance(payload, dict) and payload.get("success") is False)
        except Exception as exc:
            logger.warning("beam_upload_file_failed", provider_id=self.provider_id, error=str(exc))
            return False

    async def validate_models(
        self,
        directories: List[str],
        delete_invalid: bool = False,
    ) -> Dict[str, Any]:
        """Validate models per directory on the storage app.

        `delete_invalid` is forwarded (the old client posted it per
        directory; without it reconciliation's full pass cannot prune).
        Non-200 answers raise with the upstream status and body — the old
        reconcile probe raised rather than report a clean sweep — with
        401/403 typed as EngineAuthError.
        """
        client = self.get_http_client()
        results: Dict[str, Any] = {"by_directory": {}, "valid": [], "invalid": [], "partial": []}
        for directory in directories:
            resp = await client.post(
                f"{self.storage_url}/validate-models",
                json={"directory": directory, "delete_invalid": delete_invalid},
                timeout=120.0,
            )
            if resp.status_code in (401, 403):
                raise EngineAuthError(
                    f"Beam storage rejected credentials for /validate-models ({directory}): "
                    f"HTTP {resp.status_code}: {resp.text[:200]}",
                    status_code=resp.status_code,
                )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Beam storage /validate-models returned {resp.status_code} "
                    f"for {directory}: {resp.text[:200]}"
                )
            payload = resp.json()
            results["by_directory"][directory] = payload
            results["valid"].extend(payload.get("valid", []))
            results["invalid"].extend(payload.get("invalid", []))
            results["partial"].extend(payload.get("partial", []))
        return normalize_validation_result({"status": "ok", **results}, directories)

    async def validate_all_models(
        self,
        directories: Optional[List[str]] = None,
        delete_invalid: bool = False,
    ) -> Dict[str, Any]:
        """Single-call full-tree validation for reconciliation step 0.

        Mirrors the container's /validate-all-models probe (one POST, raise
        on non-200 with the upstream status and body as the diagnosis).
        """
        _ = directories
        client = self.get_http_client()
        resp = await client.post(
            f"{self.storage_url}/validate-all-models",
            json={"delete_invalid": delete_invalid},
            timeout=300.0,
        )
        if resp.status_code in (401, 403):
            raise EngineAuthError(
                "Beam storage rejected credentials for /validate-all-models: "
                f"HTTP {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Beam storage /validate-all-models returned {resp.status_code}: "
                f"{resp.text[:200]}"
            )
        return normalize_validation_result(resp.json())

    async def setup_models(self) -> bool:
        client = self.get_http_client()
        try:
            resp = await client.post(f"{self.storage_url}/setup", timeout=300.0)
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("beam_setup_failed", provider_id=self.provider_id, error=str(exc))
            return False

    def _download_token(self, url: str) -> str:
        lowered = (url or "").lower()
        if "huggingface.co" in lowered:
            return self.hf_token
        if "civitai.com" in lowered or "civitai.red" in lowered:
            return self.civitai_token
        return ""

    async def download_file(
        self,
        download_url: str,
        storage_path: str,
        token: Optional[str] = None,
        timeout: float = 1800.0,
    ) -> Dict[str, Any]:
        """Download one model via the storage app, awaiting completion.

        `queue_download` stays fire-and-forget for parity with the container
        worker's `spawn` route; the in-process reconciler needs attribution,
        so it awaits this instead.
        """
        client = self.get_http_client()
        resp = await client.post(
            f"{self.download_url}/download-model",
            json={
                "url": download_url,
                "path": storage_path,
                "token": token if token is not None else self._download_token(download_url),
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Beam download failed with status {resp.status_code}: {resp.text[:200]}")
        result = resp.json() if resp.content else {}
        if isinstance(result, dict) and result.get("status") == "error":
            raise RuntimeError(result.get("message", "Download failed"))
        return result if isinstance(result, dict) else {"status": "ok"}

    async def queue_download(
        self,
        url: str,
        path: str,
        token: Optional[str] = None,
        preview_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Fire-and-forget a storage-app download, mirroring the container's
        background download (which answers "queued" immediately).

        Bounded by the download slots (container: MAX_BACKGROUND_TASKS):
        past saturation this answers a busy dict with retryable=True, the
        in-process shape of the container's 429, instead of queueing
        unboundedly.
        """
        client = self.get_http_client()

        if self._download_slots.locked():
            logger.warning("beam_download_saturated", provider_id=self.provider_id, path=path)
            return {
                "status": "busy",
                "provider_id": self.provider_id,
                "path": path,
                "retryable": True,
                "message": "Download slots saturated; retry shortly",
            }

        async def _do_download() -> None:
            async with self._download_slots:
                try:
                    resp = await client.post(
                        f"{self.download_url}/download-model",
                        json={
                            "url": url,
                            "path": path,
                            "token": token or self._download_token(url),
                            "preview_url": preview_url,
                            "metadata": metadata,
                        },
                        timeout=1800.0,
                    )
                    if resp.status_code != 200:
                        logger.error("beam_download_failed", provider_id=self.provider_id, status=resp.status_code)
                except Exception as exc:
                    logger.error("beam_download_failed", provider_id=self.provider_id, error=str(exc))

        # Held on the instance: a bare create_task is only weakly held by
        # the loop and can be collected mid-download.
        task = asyncio.create_task(_do_download(), name=f"beam-download:{path}")
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return {"status": "queued", "provider_id": self.provider_id, "path": path}

    trigger_download = queue_download

    async def get_info(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "beam",
            "engine": "beam",
            "gpu_type": self.gpu_type,
            "gpu_url_configured": bool(self.gpu_url),
            "storage_url_configured": bool(self.storage_url),
        }
