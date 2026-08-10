import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional

import modal
from fastapi.responses import StreamingResponse

from provider_core.base_client import BaseProviderClient
from provider_core.models import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest,
    build_status_response, build_error_response, TaskEvent,
)

logger = logging.getLogger("provider_core.engines.vllm_modal")


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
                                model_id, messages, tools, request.timeout_seconds
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
            result = await setup_func.spawn.aio()
            if isinstance(result, dict):
                return build_status_response(
                    "success" if result.get("status") == "success" else "error",
                    result.get("message", "Setup complete"),
                    provider=self.provider_id,
                )
            return build_status_response("success", "Setup complete", provider=self.provider_id)
        except Exception as e:
            return build_error_response(f"Failed to setup: {e}")

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
            return build_status_response("queued", f"Download queued for {request.path}", provider=self.provider_id)
        except Exception as e:
            return build_error_response(f"Failed to queue download: {e}")

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        directory = request.directory if request else ""
        try:
            list_func = self._get_modal_function("list_models_with_metadata")
            files = await list_func.remote.aio(directory)
            return build_status_response("success", f"Listed models in {directory}", provider=self.provider_id, files=files)
        except Exception as e:
            self.logger.warning(f"Failed to list models: {e}")
            return build_status_response("success", f"Listed models in {directory}", provider=self.provider_id, files=[])

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        try:
            storage = self._get_file_storage_cls()()
            success = await storage.delete_file.remote.aio(request.path)
            return {
                "success": success,
                "message": f"Deleted {request.path}" if success else f"Failed to delete {request.path}",
                "provider": self.provider_id,
            }
        except Exception as e:
            return build_error_response(f"Failed to delete model: {e}")

    async def get_file(self, path: str):
        try:
            from fastapi import Response
            storage = self._get_file_storage_cls()()
            file_contents = await storage.read_file.remote.aio(path)
            return Response(content=file_contents, media_type="application/octet-stream")
        except FileNotFoundError:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        return await self.delete_model(DeleteModelRequest(path=path))

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        import base64
        try:
            content = base64.b64decode(request.content_base64)
            storage = self._get_file_storage_cls()()
            path = f"{request.directory}/{request.filename}"
            await storage.put_file.remote.aio(path=path, content=content)
            return {"status": "success", "path": path, "size": len(content)}
        except Exception as e:
            return build_error_response(f"File upload failed: {e}")

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from provider_core.deploy import start_deploy_task
        from provider_core.base_client import _DEPLOY_STATE

        commands = [["modal", "deploy", "/app/llm_worker/engines/modal/modal_app.py"]]
        start_deploy_task("Modal vLLM", commands)
        return _DEPLOY_STATE

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        try:
            validate_fn = self._get_modal_function("validate_models")
            result = await validate_fn.remote.aio(request.directories, request.delete_invalid)
            return result
        except Exception as e:
            return build_error_response(f"Validation failed: {e}")

    async def validate_all_models(self) -> Dict[str, Any]:
        try:
            validate_fn = self._get_modal_function("validate_models")
            result = await validate_fn.remote.aio(["models"], False)
            return {"status": "success", "result": result}
        except Exception as e:
            return build_error_response(f"Validation failed: {e}")

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
            await storage.delete_file.remote.aio(storage_path)
            return True

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
