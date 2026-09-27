import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional

import modal
from fastapi.responses import StreamingResponse

from provider_core.base_client import BaseProviderClient
from provider_core.ranged_read import RangedReader, cancel_ranged_reads
from provider_core.models import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest, TaskEvent,
)
from provider_core.responses import failed, from_upstream, ok, outcome
logger = logging.getLogger("provider_core.engines.vllm_modal")

# One ranged slice per RPC. Large enough that a multi-GB model is not thousands
# of round trips, small enough that neither side holds more than this.
#
# 4 MiB, not 512 KiB: at the old size a 7 GB model was 14,336 RPCs, and the
# per-call latency multiplied out to a transfer that took longer than anyone
# would wait through. 4 MiB brings it to ~1,792 while still holding only one
# slice in memory on each side — the same trade the image worker's 8 MiB makes.
_MODAL_RANGE_BYTES = 4 * 1024 * 1024

# Deadline for one whole ranged read, in seconds. See
# provider_core/ranged_read.py: the read is a sequence of RPCs against a
# container in another place, and nothing else bounds it.
MODAL_GET_FILE_TIMEOUT_SECONDS = float(os.environ.get("MODAL_GET_FILE_TIMEOUT_SECONDS", "3600"))



class VLLMModalProviderClient(BaseProviderClient):
    """
    Provider Client for LLM generation via vLLM deployed on Modal.
    Calls the VLLMEngine.generate method on the Modal deployment.
    """

    def __init__(self, provider_id: str, runtime_config: Dict[str, Any]):
        super().__init__(provider_id=provider_id, runtime_config=runtime_config)
        self.logger = logging.getLogger("provider_core.engines.vllm_modal")
        self.modal_app_name = os.environ.get("MODAL_APP_NAME", "vllm-modal-stack")
        self.modal_username = os.environ.get("MODAL_USERNAME", "")
        self._cls_cache: dict = {}
        self._func_cache: dict = {}
        self._deploy_task: Optional[asyncio.Task] = None
        self._read_tasks: set = set()

    async def close(self):
        """Cancel in-flight ranged reads so a SIGTERM does not wait them out.

        The worker lifespan teardown looks for `hasattr(client, "close")`; this
        class never defined one, so nothing could cancel a read parked mid-range.
        The reads are tasks (provider_core/ranged_read.py) so this can stop them.
        """
        await cancel_ranged_reads(self._read_tasks)

    def _get_vllm_engine_cls(self):
        if "VLLMEngine" not in self._cls_cache:
            self._cls_cache["VLLMEngine"] = modal.Cls.from_name(self.modal_app_name, "VLLMEngine")
        return self._cls_cache["VLLMEngine"]

    def _get_file_storage_cls(self):
        if "FileStorage" not in self._cls_cache:
            self._cls_cache["FileStorage"] = modal.Cls.from_name(self.modal_app_name, "FileStorage")
        return self._cls_cache["FileStorage"]

    def _get_modal_function(self, func_name: str):
        key = f"{self.modal_app_name}.{func_name}"
        if key not in self._func_cache:
            self.logger.info(f"[{self.provider_id}] Caching Modal function: {key}")
            self._func_cache[key] = modal.Function.from_name(self.modal_app_name, func_name)
        return self._func_cache[key]

    async def get_health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "provider_id": self.provider_id,
            "engine": "vllm_modal",
            "modal_app": self.modal_app_name,
        }

    async def get_info(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "vllm_modal",
            "app_name": self.modal_app_name,
            "containerized": True,
        }

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        # Unified InferenceRequest: LLM jobs carry messages/tools/model top-level.
        workflow = request.workflow or {}
        messages = request.messages or workflow.get("messages", [])
        tools = request.tools or workflow.get("tools")
        model_id = (request.model or workflow.get("model") or "default-model")
        job_id = request.job_id
        # Forward extended sampling controls to the vLLM engine (None values
        # are dropped so the engine keeps its own defaults).
        sampling: dict[str, float | int] = {}
        for key in ("temperature", "top_p", "max_output_tokens", "frequency_penalty", "presence_penalty"):
            value = getattr(request, key, None)
            if value is not None:
                sampling[key] = value
        inference_timeout = max(
            1.0,
            float(request.timeout_seconds or self.runtime_config.get("inference_timeout_seconds", 3600.0)),
        )

        if job_id:
            await self.job_tracker.start_job(job_id)

        async def stream():
            task = None
            try:
                VLLMClass = self._get_vllm_engine_cls()
                vllm_instance = VLLMClass()

                async with asyncio.timeout(inference_timeout):
                    q: asyncio.Queue = asyncio.Queue()

                    async def fetcher():
                        try:
                            async for update in vllm_instance.generate.remote_gen.aio(
                                model_id, messages, tools, request.timeout_seconds, sampling or None
                            ):
                                await q.put(update)
                            await q.put(None)
                        except Exception as e:
                            await q.put(e)

                    task = asyncio.create_task(fetcher())

                    while True:
                        try:
                            item = await asyncio.wait_for(q.get(), timeout=2.0)
                        except asyncio.TimeoutError:
                            if job_id and await self.job_tracker.is_cancelled(job_id):
                                task.cancel()
                                yield TaskEvent(
                                    event="cancelled",
                                    job_id=job_id,
                                    outputs=[{"role": "assistant", "content": "", "cancelled": True}],
                                ).to_ndjson()
                                return
                            continue

                        if item is None:
                            break

                        if isinstance(item, Exception):
                            raise item

                        if job_id and await self.job_tracker.is_cancelled(job_id):
                            task.cancel()
                            yield TaskEvent(
                                event="cancelled",
                                job_id=job_id,
                                outputs=[{"role": "assistant", "content": "", "cancelled": True}],
                            ).to_ndjson()
                            return

                        yield self._translate_remote_event(item, job_id) + "\n"

            except asyncio.TimeoutError:
                yield TaskEvent(
                    event="failed",
                    job_id=job_id,
                    message=f"Inference timed out after {int(inference_timeout)}s",
                    retryable=True,
                ).to_ndjson()
            except modal.exception.ConnectionError as ce:
                yield TaskEvent(
                    event="failed",
                    job_id=job_id,
                    message=f"Modal connection error: {ce}",
                    retryable=True,
                ).to_ndjson()
            except Exception as e:
                self.logger.error(f"Error during inference: {str(e)}")
                yield TaskEvent(event="failed", job_id=job_id, message=str(e), retryable=True).to_ndjson()
            finally:
                if task is not None:
                    task.cancel()
                if job_id:
                    await self.job_tracker.end_job(job_id)

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    def _translate_remote_event(self, raw, job_id) -> str:
        """Translate a remote VLLMEngine dict into a unified TaskEvent line.

        The deployed remote may still emit the legacy {"type": ...} dialect
        until `modal deploy` is re-run; translate it locally so the backend
        always receives TaskEvent NDJSON. TaskEvent-shaped dicts pass through.
        """
        if isinstance(raw, dict) and raw.get("event"):
            return json.dumps(raw)
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"event": "failed", "job_id": job_id, "message": f"Malformed remote event: {raw}", "retryable": True})
        if not isinstance(data, dict):
            return json.dumps({"event": "failed", "job_id": job_id, "message": f"Malformed remote event: {raw}", "retryable": True})

        msg_type = data.get("type") or data.get("status")
        if msg_type == "progress":
            return TaskEvent(event="delta", job_id=job_id, text=data.get("message") or data.get("text") or "").to_ndjson()
        if msg_type == "completed":
            cancelled = bool(data.get("cancelled")) or bool((data.get("outputs") or [{}])[0].get("cancelled"))
            if cancelled:
                return TaskEvent(event="cancelled", job_id=job_id, outputs=data.get("outputs")).to_ndjson()
            return TaskEvent(event="completed", job_id=job_id, outputs=data.get("outputs")).to_ndjson()
        if msg_type == "error":
            return TaskEvent(event="failed", job_id=job_id, message=data.get("message", "Unknown error"), retryable=True).to_ndjson()
        return json.dumps(data)

    async def setup_models(self) -> Dict[str, Any]:
        try:
            setup_func = self._get_modal_function("setup_models")
            # `spawn.aio()` resolves to a `modal.FunctionCall` receipt, never to the
            # function's return value — so the three `isinstance(result, dict)`
            # branches this used to hold could not run, and every setup, including
            # one that failed seconds later, was reported as
            # ok(..., "Setup complete"). The outcome of a spawned call is not
            # readable without `get()`, which blocks for the whole run (setup
            # seeds several GB and can take ten minutes) and defeats the point of
            # spawning, so the receipt is simply dropped and the answer says what
            # is actually true: it is queued, not complete.
            #
            # Matches image_worker/engines/modal/client.py:167. The backend reads
            # `status in {"queued", "started"}` here
            # (services/provider_lifecycle_service.py), so `queued` is still the
            # accepted shape.
            await setup_func.spawn.aio()
            return ok("Setup queued", provider=self.provider_id, status="queued")
        except Exception as e:
            return failed(f"Failed to queue setup: {e}", provider=self.provider_id)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        try:
            download_func = self._get_modal_function("download_model")
            await download_func.spawn.aio(
                request.url,
                request.path,
                request.token,
                request.preview_url,
                request.metadata,
            )
            return ok(f"Download queued for {request.path}", provider=self.provider_id, status="queued")
        except Exception as e:
            return failed(f"Failed to queue download: {e}", provider=self.provider_id)

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        directory = request.directory if request else ""
        try:
            list_func = self._get_modal_function("list_models_with_metadata")
            files = await list_func.remote.aio(directory)
            return ok(f"Listed models in {directory}", provider=self.provider_id, files=files)
        except Exception as e:
            self.logger.warning(f"Failed to list models: {e}")
            return ok(f"Listed models in {directory}", provider=self.provider_id, files=[])

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        try:
            storage = self._get_file_storage_cls()()
            success = await storage.delete_file.remote.aio(request.path)
            return outcome(
                bool(success),
                f"Deleted {request.path}" if success else f"Failed to delete {request.path}",
                provider=self.provider_id,
                code=None if success else 404,
            )
        except Exception as e:
            return failed(f"Failed to delete model: {e}", provider=self.provider_id)

    async def get_file(self, path: str) -> StreamingResponse:
        """Stream a volume file out in ranged slices.

        This was `read_file.remote.aio(path)` into a buffered Response. A modal
        method serialises its return value across the RPC boundary, so the whole
        file existed in the storage container and then again in this worker
        before the response was even built — a 7 GB GGUF is 7 GB twice over, and
        there is no streaming return value to reach for.

        So: ask for the size, then pull fixed-size ranges and yield each one. Peak
        memory is one slice on each side, and the transfer costs one RPC per
        slice, which is slow for a very large model and is the trade for not being
        OOM-killed. A small file is one RPC and behaves exactly as before.

        The read is deadline-bounded and cancellable (see
        provider_core/ranged_read.py): without either, a storage container that
        stops answering holds this call, its RPC and the caller's worker open for
        as long as the peer stays silent.
        """
        from fastapi import HTTPException

        storage = self._get_file_storage_cls()()

        reader = RangedReader(
            read_size=storage.file_size.remote.aio,
            read_range=storage.read_file_range.remote.aio,
            path=path,
            range_bytes=_MODAL_RANGE_BYTES,
            timeout_seconds=MODAL_GET_FILE_TIMEOUT_SECONDS,
            registry=self._read_tasks,
        )

        async def _stream():
            try:
                async for chunk in reader.stream():
                    yield chunk
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail=f"File not found: {path}")

        return StreamingResponse(_stream(), media_type="application/octet-stream")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        return await self.delete_model(DeleteModelRequest(path=path))

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        import base64
        try:
            content = base64.b64decode(request.content_base64)
            storage = self._get_file_storage_cls()()
            path = f"{request.directory}/{request.filename}"
            await storage.put_file.remote.aio(path=path, content=content)
            return ok("File uploaded", provider=self.provider_id, path=path, size=len(content))
        except Exception as e:
            return failed(f"File upload failed: {e}", provider=self.provider_id)

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from provider_core.deploy import start_deploy_task, get_deploy_state

        commands = [["modal", "deploy", "/app/llm_worker/engines/modal/modal_app.py"]]
        # Retained: the coroutine shells out to `modal deploy` and streams for
        # minutes, and a bare create_task is GC-eligible the moment this
        # coroutine returns. image_worker/engines/modal/client.py and
        # beam/client.py both hold the reference; see provider_core/background.py.
        self._deploy_task = start_deploy_task("Modal vLLM", commands)
        return get_deploy_state()

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        try:
            validate_fn = self._get_modal_function("validate_models")
            result = await validate_fn.remote.aio(request.directories, request.delete_invalid)
            return from_upstream(result, provider=self.provider_id, message="Validated models")
        except Exception as e:
            return failed(f"Validation failed: {e}", provider=self.provider_id)

    async def validate_all_models(self) -> Dict[str, Any]:
        try:
            validate_fn = self._get_modal_function("validate_models")
            result = await validate_fn.remote.aio(["models"], False)
            return ok("Validated all models", provider=self.provider_id, result=result)
        except Exception as e:
            return failed(f"Validation failed: {e}", provider=self.provider_id)

    async def get_object_info(self) -> Dict[str, Any]:
        return {"object_info": {}}

    async def get_storage_stats(self) -> Dict[str, Any]:
        try:
            storage = self._get_file_storage_cls()()
            total = 0
            by_directory = {}
            for directory in ["models"]:
                try:
                    files = await storage.list_directory.remote.aio(directory)
                    by_directory[directory] = len(files)
                    total += len(files)
                except Exception:
                    by_directory[directory] = 0

            return {
                "provider_id": self.provider_id,
                "total": total,
                "by_directory": by_directory,
            }
        except Exception as e:
            self.logger.warning(f"Failed to get storage stats: {e}")
            return {
                "provider_id": self.provider_id,
                "total": 0,
                "by_directory": {},
                "error": str(e),
            }

    async def run_reconciliation(self, quick_sync: bool = False) -> Dict[str, Any]:
        async def validate_existing(delete_invalid: bool):
            validate_fn = self._get_modal_function("validate_models")
            timeout_seconds = max(1.0, float(self.runtime_config.get("validation_timeout_seconds", 300.0)))
            return await asyncio.wait_for(
                validate_fn.remote.aio(["models"], delete_invalid),
                timeout=timeout_seconds,
            )

        async def list_existing_files():
            paths = {}
            list_func = self._get_modal_function("list_models_with_metadata")
            list_timeout_seconds = max(1.0, float(self.runtime_config.get("reconciliation_list_timeout_seconds", 3600.0)))

            async def _fetch_dir(directory: str):
                try:
                    files = await asyncio.wait_for(
                        list_func.remote.aio(directory),
                        timeout=list_timeout_seconds,
                    )
                    return directory, files
                except asyncio.TimeoutError:
                    raise RuntimeError(f"Timeout listing {directory} on Modal after {list_timeout_seconds}s")
                except Exception as e:
                    raise RuntimeError(f"Failed to list {directory} on Modal: {e}")

            results = await asyncio.gather(*[_fetch_dir(d) for d in ["models"]])
            for directory, files in results:
                for file_info in files:
                    paths[f"{directory}/{file_info['name']}"] = file_info

            return paths

        async def download_file(download_url: str, storage_path: str, token: str = None):
            download_func = self._get_modal_function("download_model")
            result = await download_func.remote.aio(
                url=download_url,
                path=storage_path,
                token=token,
            )
            if isinstance(result, dict) and result.get("status") == "error":
                raise RuntimeError(result.get("message", "Download failed"))

        async def delete_file(storage_path: str):
            storage = self._get_file_storage_cls()()
            # Adopt, rather than assume. The callback contract is True/False and
            # reconciliation increments `deletions_completed` on True, so
            # returning an unconditional True reported a clean sweep for orphans
            # that were still on the volume. `delete_file` already answers the
            # question truthfully; the question is that we asked it.
            return bool(await storage.delete_file.remote.aio(storage_path))

        HF_TOKEN = os.environ.get("HF_TOKEN", "")
        CIVITAI_TOKEN = os.environ.get("CIVITAI_TOKEN", "")
        BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8002")

        return await self._start_reconciliation_task(
            backend_url=BACKEND_URL,
            hf_token=HF_TOKEN,
            civitai_token=CIVITAI_TOKEN,
            storage_label="Modal-LLM",
            validate_existing_fn=validate_existing,
            list_existing_files_fn=list_existing_files,
            download_file_fn=download_file,
            delete_file_fn=delete_file,
            quick_sync=quick_sync,
        )
