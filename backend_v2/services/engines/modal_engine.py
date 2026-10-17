"""
In-Process Modal Execution Engine.

Directly interacts with Modal cloud without intermediate container proxies, supporting
multiple concurrent Modal accounts via discrete modal.Client.from_credentials(...) instances.
"""

import asyncio
import base64
import inspect
import os
import time
from typing import Any, AsyncIterator, Dict, List, Optional

try:
    import modal
    HAS_MODAL = True
except ImportError:
    modal = None  # type: ignore
    HAS_MODAL = False

from config import env_positive_float
from infrastructure.logging import get_logger
from services.engines.base import (
    TERMINAL_EVENTS,
    EngineAuthError,
    InProcessEngine,
    MODEL_DIRECTORIES,
    clamp_timeout,
    get_upload_size_cap,
    is_auth_error,
    normalize_validation_result,
    translate_legacy_image_update,
)

logger = get_logger("modal_engine")

_RANGE_CHUNK_BYTES = 8 * 1024 * 1024  # 8 MiB per slice for large volume reads

# Deadline for the whole get-file stream, mirroring
# MODAL_GET_FILE_TIMEOUT_SECONDS in the modal container client (default
# 3600s): a stalled volume read must fail instead of hanging the fetch.
_GET_FILE_TIMEOUT_SECONDS = env_positive_float(
    os.getenv("MODAL_GET_FILE_TIMEOUT_SECONDS"), 3600.0
)

# Cancel-poll window inside the inference loop. The old container client
# checked job_tracker.is_cancelled on a 2s timeout even mid-stall
# (modal/client.py:141-146); polling the async iterator on the same window
# bounds cancel latency when the Modal stream goes quiet.
_CANCEL_POLL_SECONDS = 2.0

_TRUTHY = ("true", "1", "yes")


def resolve_enable_memory_snapshot(
    config: dict | None = None,
    env_vars: dict | None = None,
) -> bool:
    """Whether a Modal image job asks for the `ComfyUISnapshot` class.

    The single resolution point for `enable_memory_snapshot`. There used to be
    two — `engine_factory` and this constructor — and they had already drifted
    on string coercion and on whether the env fallback applied, so the same
    provider could be built Snapshot and dispatched Stable.

    Precedence is provider-row config, then the per-provider `.env.<id>` file,
    then the process environment, then False. An explicit `None` in the config
    means "not decided here" and falls through, which is what keeps the env
    fallback reachable for a legacy deployment.

    Defaulting to False rather than True is deliberate: the deprecated container
    client fell back to "true" when the env was unset, so an unset variable
    silently rented the larger snapshot image.
    """
    raw = (config or {}).get("enable_memory_snapshot")
    if isinstance(raw, str):
        return raw.strip().lower() in _TRUTHY
    if raw is not None:
        return bool(raw)
    for source in ((env_vars or {}), os.environ):
        candidate = source.get("ENABLE_MEMORY_SNAPSHOT")
        if candidate is None or str(candidate).strip() == "":
            continue
        return str(candidate).strip().lower() in _TRUTHY
    return False


class ModalEngine(InProcessEngine):
    """In-process compute engine for Modal serverless workers."""

    #: This engine owns a model tree on the Modal volume, so the in-process
    #: reconciliation runner drives downloads/validation through it. LLM and
    #: TTS engines leave this False — they have no model files to reconcile.
    manages_model_files = True

    def __init__(
        self,
        provider_id: str,
        token_id: str,
        token_secret: str,
        app_name: str = "comfy-modal-stack",
        hf_token: Optional[str] = None,
        civitai_token: Optional[str] = None,
        enable_memory_snapshot: Optional[bool] = None,
    ):
        super().__init__(provider_id)
        self.token_id = token_id.strip()
        self.token_secret = token_secret.strip()
        self.app_name = app_name or os.getenv("MODAL_APP_NAME", "comfy-modal-stack")
        self.hf_token = hf_token or os.getenv("HF_TOKEN", "")
        self.civitai_token = civitai_token or os.getenv("CIVITAI_TOKEN", "")
        # Resolved through the shared helper so the engine's view and the
        # dispatcher's view cannot disagree. Passing None means "not decided by
        # the caller", which is what makes the env fallback reachable at all —
        # `job_runner` used to pass an explicit False, which made this whole
        # branch dead and the env var inert.
        self.enable_memory_snapshot = resolve_enable_memory_snapshot(
            {"enable_memory_snapshot": enable_memory_snapshot}
        )
        self._client: Optional[modal.Client] = None
        self._lock = asyncio.Lock()

    async def get_client_async(self) -> modal.Client:
        """Get or lazily instantiate the dedicated Modal client using async interface."""
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    logger.info("modal_client_init", provider_id=self.provider_id, token_prefix=self.token_id[:8])
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

    def get_client(self) -> modal.Client:
        """Get or lazily instantiate the dedicated Modal client for this provider's credentials."""
        if self._client is None:
            logger.info("modal_client_init", provider_id=self.provider_id, token_prefix=self.token_id[:8])
            self._client = modal.Client.from_credentials(
                token_id=self.token_id,
                token_secret=self.token_secret,
            )
        return self._client

    async def check_health(self) -> Dict[str, Any]:
        """Verify the app is NAMED correctly and credentials are present.

        Not a reachability check, and it should not be read as one.
        `modal.Function.from_name` is a lazy stub: it performs no RPC and raises
        nothing, so a deleted deployment, a typo'd app name or a revoked token
        all answer `healthy` here and only fail at first dispatch. Making it a
        real call would mean booting a container, which is a GPU bill on every
        poll.

        So the verdict is CONFIG validity and says so, via `probed: False`. The
        Providers page is expected to render that as "configured" rather than
        "reachable" — `modal-zetsuke` sat here reading plain green for two
        months against a deployment whose `FileStorage` predated the engine's
        rename from `get_file_size` to `file_size`.
        """
        t0 = time.monotonic()
        try:
            client = await self.get_client_async()
            # Probe function lookup to verify workspace and app availability
            modal.Function.from_name(self.app_name, "list_models_with_metadata", client=client)
            latency = time.monotonic() - t0
            return {
                "status": "healthy",
                "provider_id": self.provider_id,
                "app_name": self.app_name,
                "latency_ms": round(latency * 1000, 2),
                "ready": True,
                "probed": False,
                "check": "config_only",
            }
        except Exception as exc:
            latency = time.monotonic() - t0
            logger.warning("modal_health_check_failed", provider_id=self.provider_id, error=str(exc))
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "app_name": self.app_name,
                "latency_ms": round(latency * 1000, 2),
                "ready": False,
                "error": str(exc),
            }

    async def inference(
        self,
        workflow: Dict[str, Any],
        job_id: Optional[str] = None,
        use_snapshot: Optional[bool] = None,
        timeout: float = 3600.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute inference directly against Modal's ComfyUI class and stream TaskEvents.
        """
        if use_snapshot is None:
            # The engine is the authority on its own snapshot class, resolved
            # once at construction from provider-row config > per-provider env
            # file > process env > False. A caller that passes an explicit bool
            # (as `job_runner` used to) silently overrides all of that, which is
            # how `ENABLE_MEMORY_SNAPSHOT` became a documented variable that
            # nothing could read.
            use_snapshot = self.enable_memory_snapshot
        class_name = "ComfyUISnapshot" if use_snapshot else "ComfyUIStable"
        logger.info(
            "modal_inference_start",
            provider_id=self.provider_id,
            job_id=job_id,
            target_cls=class_name,
            timeout=timeout,
        )

        # Emit initial started TaskEvent
        yield {"event": "started", "job_id": job_id, "provider_id": self.provider_id}

        timeout = clamp_timeout(timeout)
        try:
            client = await self.get_client_async()
            ComfyUIClass = modal.Cls.from_name(self.app_name, class_name, client=client)
            comfy_instance = ComfyUIClass()

            async with asyncio.timeout(timeout):
                # Fetcher-task + queue, like the legacy modal client
                # (modal/client.py:129-147) and the Beam engine: polling
                # ``iterator.__anext__()`` with wait_for cancels the pending
                # read on every quiet window, which throws CancelledError
                # into the remote generator and ends the stream early.
                queue: asyncio.Queue = asyncio.Queue()

                async def _fetcher() -> None:
                    try:
                        async for update in comfy_instance.run.remote_gen.aio(workflow):
                            if job_id and job_id in self._cancelled_jobs:
                                return
                            await queue.put(update)
                        await queue.put(None)
                    except Exception as exc:
                        await queue.put(exc)

                task = asyncio.create_task(_fetcher())
                # A user cancel must interrupt the *read*, not wait for the next
                # update. The flag is only checked between updates, so a quiet
                # provider (long denoise step, model still loading) kept
                # generating — and billing — until the next frame. Cancelling the
                # fetcher closes the remote generator, which is the strongest
                # lever `remote_gen` exposes: Modal publishes no public
                # `FunctionCall` handle for a generator function, so the upstream
                # function is signalled by the input stream closing rather than by
                # an explicit cancel call.
                self.register_abort(job_id, task.cancel)
                try:
                    while True:
                        if job_id and job_id in self._cancelled_jobs:
                            self._cancelled_jobs.discard(job_id)
                            yield {"event": "cancelled", "job_id": job_id, "message": "Job cancelled by user"}
                            return
                        try:
                            item = await asyncio.wait_for(queue.get(), timeout=2.0)
                        except asyncio.TimeoutError:
                            continue
                        if item is None:
                            break
                        if isinstance(item, Exception):
                            raise item

                        # Canonical TaskEvents pass through; legacy
                        # {"status": ...} updates translate to the same shapes
                        # the container's translate_task_events produced.
                        event = translate_legacy_image_update(item, job_id)
                        if event is None:
                            continue
                        yield event
                        if event.get("event") in TERMINAL_EVENTS:
                            return
                finally:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

        except TimeoutError:
            logger.error("modal_inference_timeout", provider_id=self.provider_id, job_id=job_id, timeout=timeout)
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"Inference timed out after {int(timeout)}s",
                "retryable": True,
            }
        except Exception as exc:
            modal_conn_error = (
                getattr(getattr(modal, "exception", None), "ConnectionError", ())
                if HAS_MODAL
                else ()
            )
            if isinstance(modal_conn_error, type) and isinstance(exc, modal_conn_error):
                # The old container client distinguished this with its own
                # message and retryable=True (modal/client.py:175-176).
                logger.error("modal_connection_timeout", provider_id=self.provider_id, job_id=job_id, error=str(exc))
                yield {
                    "event": "failed",
                    "job_id": job_id,
                    "message": f"Modal connection timeout: {exc}",
                    "retryable": True,
                }
                return
            logger.error("modal_inference_error", provider_id=self.provider_id, job_id=job_id, error=str(exc))
            if is_auth_error(exc):
                # Bad credentials fail fast like the container's marker-less
                # error: failing over to a second provider only spends a retry
                # reproducing the same rejection.
                yield {
                    "event": "failed",
                    "job_id": job_id,
                    "message": f"Modal authentication failed: {exc}",
                    "retryable": False,
                }
                return
            # A bad app/class name is a config fault, not transient: the
            # container wrapped class lookup in an outer try → 500 stream_err
            # with no retryable marker. Detect it so it reads permanent.
            text = f"{type(exc).__name__}: {exc}".lower()
            if "not found" in text or "does not exist" in text or "no such" in text:
                yield {
                    "event": "failed",
                    "job_id": job_id,
                    "message": f"Modal inference error: {exc}",
                    "retryable": False,
                }
                return
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": f"Modal inference error: {exc}",
                "retryable": True,
            }

    async def close(self) -> None:
        """Release the cached Modal client (parity with container close()).

        The client is closed when it exposes `aclose` before the reference is
        dropped: only setting `_client = None` leaks the client's connection
        pool across every credential rotation, which is exactly when this is
        called. A client without `aclose` is still cleared.
        """
        client, self._client = self._client, None
        aclose = getattr(client, "aclose", None)
        if aclose is None:
            return
        try:
            result = aclose()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            # Teardown must never fail a job finalisation path.
            logger.warning("modal_client_close_failed", provider_id=self.provider_id, error=str(exc))

    async def list_models(self, directory: str, timeout: float = 1800.0) -> List[Dict[str, Any]]:
        """Query models in a directory directly from Modal Volume.

        Raises on failure instead of returning []: reconciliation and the
        maintenance scan both catch per directory, and an empty success is
        exactly the clean-sweep misread the container probes fixed by
        raising on non-200. The default budget mirrors the container public
        route (fast fail for UI scans); the reconciler passes
        ``timeout=3600.0`` explicitly for the cold-volume fan-out.
        """
        client = await self.get_client_async()
        try:
            func = modal.Function.from_name(self.app_name, "list_models_with_metadata", client=client)
            res = await asyncio.wait_for(func.remote.aio(directory), timeout=timeout)
            return res if isinstance(res, list) else []
        except EngineAuthError:
            raise
        except Exception as exc:
            logger.error("modal_list_models_failed", provider_id=self.provider_id, directory=directory, error=str(exc))
            if is_auth_error(exc):
                raise EngineAuthError(
                    f"Modal rejected credentials for /list-models ({directory}): {exc}",
                ) from exc
            raise RuntimeError(f"Modal list-models failed for {directory}: {exc}") from exc

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        """Stream a file in 8 MiB chunks directly from Modal FileStorage volume.

        Existence is probed before streaming (a missing file raises
        FileNotFoundError before any bytes flow, mirroring the container's
        RangedReader.prepare()). The container worker imposes no get-file
        cap and streams multi-GB checkpoints, so no size ceiling is
        enforced here either; the whole stream runs under the
        MODAL_GET_FILE_TIMEOUT_SECONDS deadline.
        """
        client = await self.get_client_async()
        FileStorage = modal.Cls.from_name(self.app_name, "FileStorage", client=client)
        storage = FileStorage()

        try:
            total_size = await asyncio.wait_for(
                storage.file_size.remote.aio(path),
                timeout=_GET_FILE_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            raise
        except Exception as exc:
            if is_auth_error(exc):
                raise EngineAuthError(
                    f"Modal rejected credentials for get-file ({path}): {exc}",
                ) from exc
            raise
        if total_size is None or total_size < 0:
            raise FileNotFoundError(f"File not found on Modal volume: {path}")

        async with asyncio.timeout(_GET_FILE_TIMEOUT_SECONDS):
            offset = 0
            while offset < total_size:
                chunk = await storage.read_file_range.remote.aio(path, offset, _RANGE_CHUNK_BYTES)
                if not chunk:
                    # The provider declared `total_size` bytes; a short read
                    # is a truncated stream, not a clean end of file. Raising
                    # here is what stops the caller hashing and storing a
                    # half-written checkpoint that would later fail its own
                    # sha256 check — silently, because every byte it did
                    # receive is valid on its own.
                    raise RuntimeError(
                        f"Modal read_file_range returned a short read for {path}: "
                        f"{offset} of {total_size} bytes"
                    )
                offset += len(chunk)
                yield chunk

            if offset < total_size:
                raise RuntimeError(
                    f"Modal streamed only {offset} of {total_size} bytes for {path}"
                )

    def download_token_for_url(self, url: str) -> Optional[str]:
        from .base import determine_download_token

        return determine_download_token(url, self.hf_token, self.civitai_token)

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

        The container worker's `download_model` route fire-and-forgets
        (`spawn.aio`) because the worker is a separate process that reports
        back via reconciliation events. In-process the reconciler already runs
        downloads under a semaphore in a background task, so awaiting the
        remote call keeps success/failure attribution exact instead of
        reporting "queued" for a download that later fails silently.

        `preview_url`/`metadata` are forwarded to the Modal app (which
        accepts both); dropping them was a parity gap with the container
        route and with BeamEngine.queue_download.
        """
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

    async def validate_models(self, directories: List[str], delete_invalid: bool = False) -> Dict[str, Any]:
        """Validate model integrity on the Modal volume (mirrors the worker).

        The answer is normalized to the totals contract reconciliation step
        0 reads; failures raise (as the container probe did) instead of
        reporting a clean sweep.
        """
        client = await self.get_client_async()
        try:
            func = modal.Function.from_name(self.app_name, "validate_models", client=client)
            result = await asyncio.wait_for(
                func.remote.aio(directories, delete_invalid),
                # 600, not 300, matching the app's own `VALIDATE_TIMEOUT`. A
                # sweep stats every model in every directory, and on a cold
                # gcsfuse volume that outlasts 300s — so the engine abandoned
                # a sweep the app was still running and reported the outcome as
                # a validation failure, which reconciliation then read as
                # "something is wrong with your models".
                timeout=600.0,
            )
            return normalize_validation_result(result, directories)
        except EngineAuthError:
            raise
        except Exception as exc:
            logger.error("modal_validate_failed", provider_id=self.provider_id, error=str(exc))
            if is_auth_error(exc):
                raise EngineAuthError(
                    f"Modal rejected credentials for /validate-models: {exc}",
                ) from exc
            raise

    async def validate_all_models(
        self,
        directories: Optional[List[str]] = None,
        delete_invalid: bool = False,
    ) -> Dict[str, Any]:
        """Single-call full-tree validation for reconciliation step 0.

        The Modal app validates a directory list in one call, so this is
        validate_models over the standard tree (mirroring the container's
        /validate-all-models loop over MODEL_DIRECTORIES).
        """
        return await self.validate_models(directories or list(MODEL_DIRECTORIES), delete_invalid)

    async def setup_models(self) -> bool:
        """Queue the Modal app's directory setup (mirrors the worker's spawn)."""
        client = await self.get_client_async()
        try:
            func = modal.Function.from_name(self.app_name, "setup_models", client=client)
            await func.spawn.aio()
            return True
        except Exception as exc:
            logger.error("modal_setup_failed", provider_id=self.provider_id, error=str(exc))
            return False

    async def upload_file(self, filename: str, content_base64: str, directory: str = "") -> bool:
        """Upload a small file to the Modal volume via FileStorage.put_file.

        Enforces the provider upload cap (the container answered 413; the
        bool contract reports False). files.py checks first, so this is the
        backstop for direct engine callers.
        """
        from services.engines.base import encoded_upload_over_cap

        # Encoded-length pre-check first (parity with BeamEngine and the
        # container router's 413): decoding a multi-hundred-MB base64 blob
        # just to reject it OOMs the backend first — and a refused upload
        # must not construct a Modal client either.
        #
        # A cap of 0 (or negative) means *disabled*, so the guard must test
        # the cap itself before the comparison: `len(s) > 0` is true for
        # every non-empty body, which would refuse all uploads for an
        # operator who disabled the cap.
        if encoded_upload_over_cap(len(content_base64)):
            logger.warning("modal_upload_over_cap", provider_id=self.provider_id, path=filename)
            return False
        try:
            content = base64.b64decode(content_base64)
            cap = get_upload_size_cap()
            if cap and len(content) > cap:
                logger.warning("modal_upload_over_cap", provider_id=self.provider_id, path=filename, size=len(content), cap=cap)
                return False
            client = await self.get_client_async()
            FileStorage = modal.Cls.from_name(self.app_name, "FileStorage", client=client)
            storage = FileStorage()
            path = f"{directory}/{filename}" if directory else filename
            await storage.put_file.remote.aio(path=path, content=content)
            return True
        except Exception as exc:
            logger.error("modal_upload_failed", provider_id=self.provider_id, path=filename, error=str(exc))
            return False

    async def get_object_info(self) -> Dict[str, Any]:
        """Extract ComfyUI node definitions via the ComfyUINodeExtractor class."""
        client = await self.get_client_async()
        ComfyUINodeExtractor = modal.Cls.from_name(self.app_name, "ComfyUINodeExtractor", client=client)
        extractor = ComfyUINodeExtractor()
        return await extractor.get_object_info.remote.aio()

    async def delete_file(self, path: str) -> bool:
        """Delete a file from Modal volume."""
        client = await self.get_client_async()
        try:
            FileStorage = modal.Cls.from_name(self.app_name, "FileStorage", client=client)
            storage = FileStorage()
            return bool(await storage.delete_file.remote.aio(path))
        except Exception as exc:
            if is_auth_error(exc):
                raise EngineAuthError(
                    f"Modal rejected credentials for delete-file ({path}): {exc}",
                ) from exc
            logger.error("modal_delete_file_failed", provider_id=self.provider_id, path=path, error=str(exc))
            return False

    async def delete_model(self, path: str) -> bool:
        """Delete a model via the same volume path as delete_file.

        Parity alias for the reconciler's ``getattr(engine, "delete_model")``
        preference (Beam/Direct implement sidecar-aware /delete-model; the
        Modal container reconcile callback removed exactly one path, so both
        routes converge here).
        """
        return await self.delete_file(path)

    async def deploy(self) -> dict[str, Any]:
        """No-op deploy: the in-process engine needs no container deploy.

        Present for parity with the legacy container client's ``deploy()``
        (``modal deploy`` of the worker app) so callers probing the method
        get the ``not_applicable`` vocabulary the lifecycle route serves.
        """
        return {"status": "not_applicable", "mode": "in_process", "provider_id": self.provider_id}

    async def get_info(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "modal",
            "app_name": self.app_name,
            "engine": "modal",
        }
