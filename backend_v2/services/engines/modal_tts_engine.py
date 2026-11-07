"""
In-Process Modal TTS Compute Engine.

Directly communicates with Modal's comfy-modal-tts deployment without intermediate container wrappers.
Supports multi-account Modal credentials and streams TaskEvents directly.
"""

import asyncio
import base64
import inspect
import os
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from infrastructure.logging import get_logger
from services.engines.base import (
    FileTooLargeError,
    InProcessEngine,
    TERMINAL_EVENTS,
    clamp_timeout,
    get_file_size_cap,
)

logger = get_logger("modal_tts_engine")

try:
    import modal
    HAS_MODAL = True
except ImportError:
    modal = None  # type: ignore
    HAS_MODAL = False

#: Upload ceiling, contract parity with the container TTS client: it answers an
#: over-cap upload with 413, so this engine answers `False`. The upload
#: number is deliberately NOT `PROVIDER_GET_FILE_MAX_BYTES` — that knob governs
#: streamed *reads* (see `fetch_audio_file` below), and an upload budget and a
#: read budget are different decisions. Audio fetch uses the shared read cap.
_MAX_AUDIO_BYTES = 64 * 1024 * 1024

# Timeout for the Modal volume RPCs (file_size/read_file/put_file). Matches
# `_TTS_FETCH_TIMEOUT_SECONDS` in `services/job_processing.py`, which is the
# ceiling the container-HTTP fetch branch for the same audio applies — the two
# paths fetch the same bytes and should give up on the same terms.
_TTS_FILE_TIMEOUT_SECONDS = 120.0

# An app event that ends the stream. Anything else is progress the reducer
# places, and the loop must not claim a completion of its own once one of
# these has been seen — that is exactly how a failure came to be reported
# as a green job on the container path
# (tts_worker/engines/modal/client.py::_TERMINAL_EVENTS).
def _task_event_for_update(update: Any, job_id: str | None) -> dict[str, Any] | None:
    """Translate one event from the TTS Modal app into the unified dialect.

    Mirrors `task_event_for_update` in
    `tts_worker/engines/modal/client.py`: the app's own vocabulary is
    `{"status": ...}` — `success` with an `outputs` list of
    `{filename, subfolder, type}`, `running` once per poll, `error` with an
    explicit `retryable` flag — while the backend reducer has no branch for
    `running`, so forwarding one would only manufacture progress with no
    value. `None` means "no event".
    """
    if isinstance(update, (bytes, bytearray)):
        update = update.decode("utf-8", "replace")
    if isinstance(update, str):
        try:
            import json

            update = json.loads(update)
        except ValueError:
            return {
                "event": "failed",
                "job_id": job_id,
                "message": f"Malformed TTS app event: {update!r}",
                # A payload the engine cannot read is our bug, not the app's,
                # and repeating the request reproduces it exactly.
                "retryable": False,
            }
    if not isinstance(update, dict):
        return {
            "event": "failed",
            "job_id": job_id,
            "message": f"Malformed TTS app event: {update!r}",
            "retryable": False,
        }

    status = str(update.get("status") or "").lower()
    if status == "success":
        return {"event": "completed", "job_id": job_id, "outputs": update.get("outputs") or []}
    if status == "error":
        return {
            "event": "failed",
            "job_id": job_id,
            "message": update.get("message") or "TTS generation failed",
            "retryable": bool(update.get("retryable")),
        }
    if status == "cancelled":
        return {"event": "cancelled", "job_id": job_id, "message": update.get("message") or "cancelled"}
    if status == "running":
        return None
    if status in TERMINAL_EVENTS:
        return {
            "event": status,
            "job_id": job_id,
            "message": update.get("message"),
            "outputs": update.get("outputs"),
            "retryable": update.get("retryable"),
        }
    # The legacy container returned None for everything outside the
    # ``status`` vocabulary: forwarding progress/preview/node dicts here
    # manufactured valueless ``Rendering: 0%`` rows and GENERATING writes
    # in the image reducer for every TTS job. Drop them.
    event_kind = update.get("event")
    if event_kind == "completed":
        return {
            "event": "completed",
            "job_id": job_id,
            "outputs": update.get("outputs") or [],
            "details": update.get("details", {}),
        }
    if event_kind == "failed":
        return {
            "event": "failed",
            "job_id": job_id,
            "message": update.get("message") or "TTS generation failed",
            "retryable": bool(update.get("retryable", False)),
        }
    if event_kind == "cancelled":
        return {
            "event": "cancelled",
            "job_id": job_id,
            "message": update.get("message") or "cancelled",
            "outputs": update.get("outputs"),
        }
    return None


class ModalTTSEngine(InProcessEngine):
    """In-process compute engine for Modal serverless TTS."""

    def __init__(
        self,
        provider_id: str,
        token_id: str,
        token_secret: str,
        app_name: str = "comfy-modal-tts",
        cls_name: str = "TTSWorker",
        storage_cls_name: str = "TTSFileStorage",
    ):
        super().__init__(provider_id)
        self.token_id = token_id.strip()
        self.token_secret = token_secret.strip()
        self.app_name = app_name or os.getenv("MODAL_TTS_APP_NAME", "comfy-modal-tts")
        self.cls_name = cls_name or os.getenv("MODAL_TTS_CLASS", "TTSWorker")
        self.storage_cls_name = storage_cls_name or os.getenv("MODAL_TTS_STORAGE_CLASS", "TTSFileStorage")
        self._client: Optional[Any] = None
        self._lock = asyncio.Lock()

    async def get_client_async(self) -> Any:
        if not HAS_MODAL or modal is None:
            raise RuntimeError("modal package is required for ModalTTSEngine")
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    logger.info("modal_tts_client_init", provider_id=self.provider_id, token_prefix=self.token_id[:8])
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
        """Release the cached Modal client (parity with ModalEngine close()).

        The client is closed when it exposes `aclose` before the reference is
        dropped: only setting `_client = None` leaks the client's connection
        pool across credential rotations and engine invalidations.
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
            logger.warning("modal_tts_client_close_failed", provider_id=self.provider_id, error=str(exc))

    async def check_health(self) -> Dict[str, Any]:
        """Probe Modal app availability.

        NOTE on shape: the container worker's `get_health`
        (`tts_worker/engines/modal/client.py`) answers
        `{status, provider_id, type, modal_app, modal_class, capabilities,
        ready}` and raises a 503 `config_fault_detail` when
        `MODAL_TTS_APP_NAME` is unset. The engine contract is a plain dict (no
        HTTP status channel), so this keeps its own keys (`engine`,
        `latency_ms`) and carries the config-fault signal as `retryable:
        False` in the unhealthy branch below instead of a 503.
        """
        t0 = time.monotonic()
        if not self.app_name:
            # Config fault, not an outage: retrying with the same config
            # reproduces it exactly, so it must not be retried. Mirrors the
            # container's 503 `config_fault_detail(missing=[...])` branch.
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": latency_ms,
                "engine": "modal_tts",
                "retryable": False,
                "missing": ["MODAL_TTS_APP_NAME"],
                "error": "MODAL_TTS_APP_NAME is not configured",
            }
        try:
            client = await self.get_client_async()
            modal.Cls.from_name(self.app_name, self.cls_name, client=client)
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            return {
                "status": "healthy",
                "provider_id": self.provider_id,
                "ready": True,
                "latency_ms": latency_ms,
                "engine": "modal_tts",
                "app_name": self.app_name,
                "capabilities": ["tts"],
                # Config validity, not reachability: `modal.Cls.from_name` is
                # a lazy stub that performs no RPC, so a missing or renamed
                # deployment answers healthy here and fails at first dispatch.
                # Said explicitly so the UI can render "configured" instead of
                # "reachable".
                "probed": False,
                "check": "config_only",
            }
        except Exception as exc:
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            logger.warning("modal_tts_health_check_failed", provider_id=self.provider_id, error=str(exc))
            return {
                "status": "unhealthy",
                "provider_id": self.provider_id,
                "ready": False,
                "latency_ms": latency_ms,
                "engine": "modal_tts",
                "error": str(exc),
            }

    async def get_info(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "modal_tts",
            "engine": "modal_tts",
            "app_name": self.app_name,
            "cls_name": self.cls_name,
            "storage_cls_name": self.storage_cls_name,
        }

    async def list_models(self, directory: str = "") -> List[Dict[str, Any]]:
        """TTS voices are selected inside the TTS Modal app, not from storage.

        Mirrors the container worker which honestly answers ``{"models": [],
        "note": ...}`` — no phantom row for a generic list_models consumer.
        """
        return []

    async def list_voices(self) -> List[Dict[str, Any]]:
        """Query the Modal TTS app's /v1/voices endpoint for available voices."""
        try:
            client = await self.get_client_async()
            # Try to call a voice listing method on the TTSWorker class
            TTSClass = modal.Cls.from_name(self.app_name, self.cls_name, client=client)
            instance = TTSClass()
            # Check if the class has a list_voices method
            if hasattr(instance, 'list_voices'):
                result = await instance.list_voices.remote.aio()
                if isinstance(result, dict) and "voices" in result:
                    return result["voices"]
                elif isinstance(result, list):
                    return result
            # Fallback: return preset voices known to Qwen3-TTS
            return [
                {"id": "friendly", "name": "Friendly", "type": "preset", "language": "en", "description": "Warm, approachable tone"},
                {"id": "professional", "name": "Professional", "type": "preset", "language": "en", "description": "Clear, authoritative delivery"},
                {"id": "cheerful", "name": "Cheerful", "type": "preset", "language": "en", "description": "Bright, energetic tone"},
                {"id": "calm", "name": "Calm", "type": "preset", "language": "en", "description": "Relaxed, soothing presence"},
                {"id": "deep", "name": "Deep", "type": "preset", "language": "en", "description": "Rich, resonant bass"},
                {"id": "bright", "name": "Bright", "type": "preset", "language": "en", "description": "Crisp, clear high register"},
                {"id": "storyteller", "name": "Storyteller", "type": "preset", "language": "en", "description": "Expressive, narrative style"},
                {"id": "whisper", "name": "Whisper", "type": "preset", "language": "en", "description": "Intimate, hushed delivery"},
                {"id": "dramatic", "name": "Dramatic", "type": "preset", "language": "en", "description": "Theatrical, emotional range"},
            ]
        except Exception as exc:
            logger.warning("modal_tts_list_voices_failed", provider_id=self.provider_id, error=str(exc))
            return []

    async def get_file_stream(self, path: str) -> AsyncIterator[bytes]:
        """Stream generated audio directly from Modal volume.

        Capped at 64 MiB like the container worker: speech is small, and the
        point of the ceiling is that this route cannot be pointed at a
        checkpoint, which the image engine exists to stream.

        Mirrors `get_file` in `tts_worker/engines/modal/client.py`: a
        `file_size` RPC first — a missing file surfaces as `FileNotFoundError`
        (the container's 404) and an over-cap file is refused — and the bytes
        are only fetched once the size is known to fit, so a large object is
        never materialised just to be rejected.
        """
        client = await self.get_client_async()
        StorageCls = modal.Cls.from_name(self.app_name, self.storage_cls_name, client=client)
        storage = StorageCls()

        try:
            size = await asyncio.wait_for(
                storage.file_size.remote.aio(path),
                timeout=_TTS_FILE_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            raise
        except Exception as exc:
            # Parity with container: only a missing file reads as 404 — a
            # volume outage must not masquerade as "not found".
            logger.error("modal_tts_stat_file_failed", provider_id=self.provider_id, path=path, error=str(exc))
            raise RuntimeError(f"Failed to stat audio on Modal volume: {path} ({exc})") from exc
        if size is None or size < 0:
            raise FileNotFoundError(f"Audio not found on Modal volume: {path}")
        size = int(size)
        # The streamed-read cap, not the upload cap: this is the same body the
        # `/view` and agent branches of `get_file_stream` bound, and the
        # operator knob that governs it is `PROVIDER_GET_FILE_MAX_BYTES`. Using
        # the upload number here would have made that knob a no-op for audio.
        cap = get_file_size_cap()
        if cap and size > cap:
            raise FileTooLargeError(path, size=size, cap=cap)

        try:
            data = await asyncio.wait_for(
                storage.read_file.remote.aio(path),
                timeout=_TTS_FILE_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            raise
        except Exception as exc:
            logger.error("modal_tts_read_file_failed", provider_id=self.provider_id, path=path, error=str(exc))
            raise RuntimeError(f"Failed to read audio from Modal volume: {path} ({exc})") from exc
        if not data:
            raise FileNotFoundError(f"Audio not found on Modal volume: {path}")
        if get_file_size_cap() and len(data) > get_file_size_cap():
            # Narrow race: the file grew between the size check and the read.
            # Refuse rather than stream an unbounded body.
            raise FileTooLargeError(path, size=len(data), cap=get_file_size_cap())
        # Yield in 1MB chunks
        chunk_size = 1024 * 1024
        for offset in range(0, len(data), chunk_size):
            yield data[offset:offset + chunk_size]

    async def delete_file(self, path: str) -> bool:
        """Delete audio from Modal volume."""
        client = await self.get_client_async()
        try:
            StorageCls = modal.Cls.from_name(self.app_name, self.storage_cls_name, client=client)
            storage = StorageCls()
            return bool(await storage.delete_file.remote.aio(path))
        except Exception as exc:
            logger.error("modal_tts_delete_file_failed", provider_id=self.provider_id, path=path, error=str(exc))
            return False

    async def upload_file(self, filename: str, content_base64: str, directory: str = "") -> bool:
        """Upload a voice-reference clip onto the Modal volume.

        Mirrors `upload_file` in `tts_worker/engines/modal/client.py`: base64
        in (that is what the caller carries on every engine), decoded and
        written via the storage class `put_file` at `{directory}/{filename}`
        — the symlinked ComfyUI input namespace the voice-clone node reads
        from — capped at 64 MiB. The container answers an over-cap upload with
        413; the engine contract is bool, so a cap breach (like any other
        failure here) is `False` with a log line, which the `files.py` sync
        caller already counts as a failed provider.
        """
        try:
            content = base64.b64decode(content_base64)
        except Exception as exc:
            logger.warning("modal_tts_upload_bad_content", provider_id=self.provider_id, filename=filename, error=str(exc))
            return False
        if len(content) > _MAX_AUDIO_BYTES:
            logger.warning(
                "modal_tts_upload_too_large",
                provider_id=self.provider_id,
                filename=filename,
                bytes=len(content),
            )
            return False
        try:
            client = await self.get_client_async()
            StorageCls = modal.Cls.from_name(self.app_name, self.storage_cls_name, client=client)
            storage = StorageCls()
            path = f"{directory}/{filename}" if directory else filename
            await asyncio.wait_for(
                storage.put_file.remote.aio(path=path, content=content),
                timeout=_TTS_FILE_TIMEOUT_SECONDS,
            )
            return True
        except Exception as exc:
            logger.error("modal_tts_upload_failed", provider_id=self.provider_id, path=filename, error=str(exc))
            return False

    async def inference(
        self,
        workflow: Dict[str, Any],
        job_id: Optional[str] = None,
        use_snapshot: bool = True,
        timeout: float = 1800.0,
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute TTS workflow directly against Modal's TTSWorker class and stream TaskEvents.
        """
        logger.info("modal_tts_inference_start", provider_id=self.provider_id, job_id=job_id, timeout=timeout)

        timeout = clamp_timeout(timeout, default=1800.0)
        yield {"event": "started", "job_id": job_id, "provider_id": self.provider_id}

        seen_terminal = False
        try:
            client = await self.get_client_async()
            TTSClass = modal.Cls.from_name(self.app_name, self.cls_name, client=client)
            instance = TTSClass()

            async with asyncio.timeout(timeout):
                # Fetcher-task + queue, matching ModalEngine's shape: cancelling
                # the fetcher closes the remote generator, which is the only way
                # to interrupt a stream that is parked in `__anext__`. The flag
                # the old loop checked between updates could not be observed
                # while nothing was being produced, so a quiet TTS run kept the
                # provider's GPU busy to completion after the user cancelled.
                queue: asyncio.Queue = asyncio.Queue()

                async def _fetcher() -> None:
                    try:
                        async for update in instance.run.remote_gen.aio(workflow):
                            await queue.put(update)
                        await queue.put(None)
                    except Exception as exc:
                        await queue.put(exc)

                task = asyncio.create_task(_fetcher())
                self.register_abort(job_id, task.cancel)
                try:
                    while True:
                        if job_id and job_id in self._cancelled_jobs:
                            self._cancelled_jobs.discard(job_id)
                            seen_terminal = True
                            # The wording stays the in-process family's "Job
                            # cancelled by user" rather than the container's bare
                            # "cancelled": both contain "cancelled", which is all
                            # `job_service.classify_failure` and the
                            # `provider_client` reducers key on (they default a
                            # missing message to this same string), so unifying
                            # on the family wording loses no signal.
                            yield {"event": "cancelled", "job_id": job_id, "message": "Job cancelled by user"}
                            return

                        try:
                            update = await asyncio.wait_for(queue.get(), timeout=2.0)
                        except asyncio.TimeoutError:
                            continue
                        if update is None:
                            break
                        if isinstance(update, Exception):
                            raise update

                        task_event = _task_event_for_update(update, job_id)
                        if task_event is None:
                            continue
                        if task_event.get("event") in TERMINAL_EVENTS:
                            seen_terminal = True
                        yield task_event
                        if task_event.get("event") in TERMINAL_EVENTS:
                            return
                finally:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

        except TimeoutError:
            logger.warning("modal_tts_timeout", provider_id=self.provider_id, job_id=job_id)
            seen_terminal = True
            yield {"event": "failed", "job_id": job_id, "message": f"TTS generation timed out after {int(timeout)}s", "retryable": True}
        except asyncio.CancelledError:
            seen_terminal = True
            yield {"event": "cancelled", "job_id": job_id, "message": "cancelled"}
            raise
        except Exception as exc:
            logger.exception("modal_tts_error", provider_id=self.provider_id, job_id=job_id, error=str(exc))
            seen_terminal = True
            # Not retryable: a TTS failure here is almost always the graph (a
            # node the image lacks, a model that has not downloaded), and
            # retrying it on every other provider would just be a slower way
            # to fail. Same rule as the container worker.
            yield {"event": "failed", "job_id": job_id, "message": f"TTS generation failed: {type(exc).__name__}: {exc}", "retryable": False}

        if not seen_terminal:
            # The app's generator ended without saying how the job went. A
            # completion asserted here would be a guess: the backend's reducer
            # stores the terminal event it last saw and finalizes on it, so
            # every audio file the app failed to report would be finalised as
            # a green job with `outputs=[]` and no error. Same wording the
            # container worker uses for the identical condition.
            yield {
                "event": "failed",
                "job_id": job_id,
                "message": "TTS app stream ended without a terminal event",
                "retryable": True,
            }
