"""
Modal engine client for the TTS worker.

A thin relay: it holds the Modal SDK and calls the `TTSWorker` class in the
`comfy-modal-tts` app, forwarding the workflow the backend built and streaming
`TaskEvent` lines back. It runs no ComfyUI and holds no models — the app does.

Deliberately narrow compared to `image_worker.engines.modal.client`. That client
carries the model volume, the FileStorage class, node extraction, memory
snapshots and a stalled-run profiler, none of which a speech container needs.
Copying it wholesale would import the image worker's failure modes — and its
cold start — into the thing meant to avoid both.

What is kept is the part that must behave identically to the other engines,
because the backend shares it: the NDJSON `TaskEvent` stream, the retry
classification, and the cancelled/timeout handling.
"""

import asyncio
import json
import os
from typing import Any, Dict, Optional

import modal
from fastapi import HTTPException

from provider_core.base_client import BaseProviderClient
from provider_core.logging import get_logger
from provider_core.models import InferenceRequest, TaskEvent

logger = get_logger("tts_worker.modal.client")

# Distinct from the image worker's `MODAL_APP_NAME`, so `modal.Cls.from_name` is
# unambiguous and the two deployments keep separate histories.
MODAL_TTS_APP_NAME = os.getenv("MODAL_TTS_APP_NAME", "comfy-modal-tts")

# The class inside that app. Must match `tts_worker/engines/modal/modal_app.py`;
# a rename on one side only fails at the first call, not at import.
TTS_CLASS_NAME = os.getenv("MODAL_TTS_CLASS", "TTSWorker")

# Ceiling on a file this worker will read or accept. Speech is small; the point
# is that the generic `/file` route cannot be pointed at a checkpoint, which the
# image worker exists to stream.
_MAX_AUDIO_BYTES = 64 * 1024 * 1024


class ModalTTSProviderClient(BaseProviderClient):
    """Calls the `TTSWorker` class in the TTS Modal app."""

    def __init__(self, runtime_config: Dict[str, Any]):
        # `select_client` passes `runtime_config` as a keyword, and the provider id
        # comes FROM it. Mirrors `image_worker.engines.modal.client`, which
        # reads PROVIDER_ID from the module rather than taking it as an argument —
        # so the two constructors cannot drift apart in a way that only shows at
        # the first call.
        provider_id = (runtime_config or {}).get("provider_id", "")
        super().__init__(provider_id, runtime_config)
        self.runtime_config = runtime_config or {}
        self.job_tracker = self.runtime_config.get("job_tracker")

    async def get_health(self) -> Dict[str, Any]:
        """Report on the TTS app specifically, not on the image one.

        The image worker's equivalent only checks that `MODAL_APP_NAME` is set,
        which is why a shared container could claim to be healthy while the TTS
        app did not exist. A dedicated container is the fix; this is the second
        half, so the answer names the app it actually depends on.
        """
        if not MODAL_TTS_APP_NAME:
            from fastapi import HTTPException

            from provider_core.responses import config_fault_detail

            raise HTTPException(
                status_code=503,
                detail=config_fault_detail(
                    "provider is not configured",
                    status="unhealthy",
                    provider_id=self.provider_id,
                    ready=False,
                    missing=["MODAL_TTS_APP_NAME"],
                ),
            )
        return {
            "status": "healthy",
            "provider_id": self.provider_id,
            "type": "modal",
            "modal_app": MODAL_TTS_APP_NAME,
            "modal_class": TTS_CLASS_NAME,
            "capabilities": ["tts"],
            "ready": True,
        }

    async def get_info(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "modal",
            "app_name": MODAL_TTS_APP_NAME,
            "capabilities": ["tts"],
            "containerized": True,
        }

    async def inference(self, request: InferenceRequest) -> Any:
        from fastapi.responses import StreamingResponse

        job_id = request.job_id
        timeout = max(
            1.0,
            float(
                request.timeout_seconds
                or self.runtime_config.get("inference_timeout_seconds", 1800.0)
            ),
        )

        if job_id and self.job_tracker:
            await self.job_tracker.start_job(job_id)

        async def event_stream():
            try:
                cls = modal.Cls.from_name(MODAL_TTS_APP_NAME, TTS_CLASS_NAME)
                instance = cls()
                try:
                    async with asyncio.timeout(timeout):
                        async for event in instance.run.remote_gen.aio(request.workflow):
                            if isinstance(event, str):
                                event = json.loads(event)
                            yield TaskEvent(
                                event="running", job_id=job_id, message=json.dumps(event)
                            ).to_ndjson()
                except asyncio.TimeoutError:
                    yield TaskEvent(
                        event="failed",
                        job_id=job_id,
                        message=f"Inference timed out after {int(timeout)}s",
                        retryable=True,
                    ).to_ndjson()
                except asyncio.CancelledError:
                    yield TaskEvent(
                        event="cancelled", job_id=job_id, message="cancelled"
                    ).to_ndjson()
                    raise
                except Exception as exc:
                    # Not retryable, and a specific message. A TTS failure here is
                    # almost always the graph (a node the image lacks, a model
                    # that has not downloaded), and retrying it on every other
                    # provider would just be a slower way to fail.
                    yield TaskEvent(
                        event="failed",
                        job_id=job_id,
                        message=f"TTS generation failed: {type(exc).__name__}: {exc}",
                        retryable=False,
                    ).to_ndjson()
            finally:
                if job_id and self.job_tracker:
                    await self.job_tracker.end_job(job_id)
            yield TaskEvent(event="completed", job_id=job_id).to_ndjson()

        return StreamingResponse(event_stream(), media_type="application/x-ndjson")

    # ------------------------------------------------------------------ files
    #
    # Needed, unlike the model-management methods below: the backend has to
    # fetch the produced audio, and a user cloning a voice uploads a reference
    # the worker then reads. Both go through the shared Modal volume, so they are
    # small and there is nothing image-specific about them.

    def _volume(self):
        return modal.Volume.from_name(
            os.getenv("MODAL_VOLUME_NAME", "comfy-storage"), create_if_missing=True
        )

    async def get_file(self, path: str):
        """Read a file off the shared volume.

        NOT the ranged reader the image worker uses. That machinery exists to
        stream a 7 GB checkpoint without materialising it twice — `RangedReader`
        plus a `FileStorage` Modal class, one RPC per 8 MiB slice. A speech clip
        is a few hundred KB to a few MB, so the whole file in one call is
        simpler, faster (one RPC instead of many) and bounded.

        The trade is a memory ceiling: a path pointing at something enormous
        would materialise it. That cannot happen from the TTS paths, which only
        ever write audio, but the method is on a generic `/file` route — so the
        cap below refuses anything large rather than trusting the caller.
        """
        from fastapi.responses import Response

        volume = self._volume()
        try:
            size = await volume.stat.remote(path)
        except Exception:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        size = int(getattr(size, "size", 0) or 0)
        if size > _MAX_AUDIO_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"{path} is {size} bytes; this worker only serves audio up to "
                    f"{_MAX_AUDIO_BYTES}. Use the image worker for large files."
                ),
            )
        data = await volume.read_file.remote(path)
        return Response(content=data, media_type="application/octet-stream")

    async def upload_file(self, request: Any):
        """Write an uploaded file onto the shared volume.

        Used for a cloning reference: the user uploads audio, the worker reads it
        from the volume. Base64 because that is what `UploadFileRequest` carries
        on every engine, so the shape is not this worker's to change.
        """
        import base64

        volume = self._volume()
        path = f"{request.directory}/{request.filename}"
        content = base64.b64decode(request.content_base64)
        if len(content) > _MAX_AUDIO_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"reference is {len(content)} bytes; limit is {_MAX_AUDIO_BYTES}",
            )
        await volume.write_file.remote(path, content)
        return {"status": "ok", "path": path, "size": len(content)}

    async def delete_file(self, path: str):
        try:
            await self._volume().remove_file.remote(path)
            return {"status": "deleted", "path": path}
        except Exception:
            return {"status": "missing", "path": path}

    # ------------------------------------------------- model management
    #
    # Explicit rather than left abstract, because `attach_provider_routes`
    # exposes all of these and `reconciliation_loop` calls several on a timer. An
    # unimplemented abstract method turns a periodic background call into a 500
    # in the logs forever, and an operator cannot tell a broken provider from one
    # that was never asked to do this.

    _NOT_APPLICABLE = "a TTS worker serves speech, not a ComfyUI model tree"

    async def list_models(self, request: Optional[Any] = None) -> Dict[str, Any]:
        return {"models": [], "note": self._NOT_APPLICABLE}

    async def get_object_info(self) -> Dict[str, Any]:
        return {"object_info": {}, "note": self._NOT_APPLICABLE}

    async def setup_models(self) -> Dict[str, Any]:
        return {"status": "skipped", "note": self._NOT_APPLICABLE}

    async def download_model(self, request: Any) -> Dict[str, Any]:
        return {"status": "skipped", "note": self._NOT_APPLICABLE}

    async def delete_model(self, request: Any) -> Dict[str, Any]:
        return {"status": "skipped", "note": self._NOT_APPLICABLE}

    async def validate_models(self, request: Any) -> Dict[str, Any]:
        return {"status": "skipped", "note": self._NOT_APPLICABLE}

    async def validate_all_models(self) -> Dict[str, Any]:
        return {"status": "skipped", "note": self._NOT_APPLICABLE}

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # NOT a no-op: the TTS Modal app is built by this worker, so `deploy` is
        # the route the backend's `POST /providers/{id}/deploy` ultimately drives
        # (through `provider_deploy_orchestrator`, in a separate container). This
        # method is the engine-level hook and is answered honestly rather than
        # skipped, so a caller that reaches it gets the truth.
        return {
            "status": "not_supported",
            "note": (
                "Modal deploys run in a dedicated container via "
                "provider_deploy_orchestrator, not in the serving worker. Use "
                "POST /api/v2/providers/{id}/deploy."
            ),
        }

    async def run_reconciliation(self, quick_sync: bool = False) -> Dict[str, Any]:
        # There is no ComfyUI model tree to reconcile. Answering explicitly beats
        # the abstract NotImplementedError, which the periodic reconciliation
        # loop would turn into an error in the logs every cycle.
        return {
            "status": "skipped",
            "note": self._NOT_APPLICABLE,
            "checked": 0,
            "invalid": 0,
        }
