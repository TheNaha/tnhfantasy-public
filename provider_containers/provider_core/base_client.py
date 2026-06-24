import abc
from typing import Any, Dict, List, Optional, Callable
import asyncio
from datetime import datetime

_DEPLOY_STATE: Dict[str, Any] = {}

from provider_core import (
    CancelJobRequest,
    get_job_tracker,
    get_reconciliation_state,
    get_logger
)

logger = get_logger("provider_core.base_client")

class BaseProviderClient(abc.ABC):
    def __init__(self, provider_id: str, runtime_config: Dict[str, Any]):
        self.provider_id = provider_id
        self.runtime_config = runtime_config
        self.job_tracker = get_job_tracker()
        self.reconciliation_state = get_reconciliation_state(provider_id)

    def get_config(self) -> Dict[str, Any]:
        return {"config": self.runtime_config}

    async def get_storage_stats(self) -> Dict[str, Any]:
        try:
            # We must import ListModelsRequest here to avoid circular imports if needed,
            # or it should be passed from models
            from provider_core.models import ListModelsRequest
            result = await self.list_models(ListModelsRequest(directory=""))
            files = result.get("files", [])
            by_directory = {}
            for file in files:
                path = file.get("path", "")
                if not path:
                    continue
                # Assuming path is like models/checkpoints/foo.safetensors
                parts = path.split("/")
                if len(parts) > 1:
                    directory = "/".join(parts[:-1])
                else:
                    directory = "root"
                by_directory[directory] = by_directory.get(directory, 0) + 1
                
            return {
                "provider_id": self.provider_id,
                "total": len(files),
                "by_directory": by_directory
            }
        except Exception as e:
            logger.error(f"[{self.provider_id}] Failed to get storage stats: {e}")
            return {"provider_id": self.provider_id, "total": 0, "by_directory": {}, "error": str(e)}

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        updated = []
        for key, value in updates.items():
            if key in self.runtime_config:
                self.runtime_config[key] = value
                updated.append(key)
                if "TOKEN" in key.upper() or "SECRET" in key.upper() or "KEY" in key.upper():
                    logger.info(f"[{self.provider_id}] Config updated: {key} = ✓ Set")
                else:
                    logger.info(f"[{self.provider_id}] Config updated: {key} = {value}")
        return {"status": "updated", "updated_keys": updated, "config": self.runtime_config}

    async def cancel_job(self, request: CancelJobRequest) -> Dict[str, Any]:
        job_id = request.job_id
        cancelled = await self.job_tracker.cancel_job(job_id)
        if cancelled:
            return {"status": "cancelled", "job_id": job_id, "message": "Job marked for cancellation"}
        return {"status": "not_found", "job_id": job_id, "message": "Job not currently active"}

    def get_reconciliation_status(self) -> Dict[str, Any]:
        return self.reconciliation_state.to_dict()

    async def _start_reconciliation_task(
        self,
        backend_url: str,
        hf_token: str,
        civitai_token: str,
        storage_label: str,
        validate_existing_fn,
        list_existing_files_fn,
        download_file_fn,
        delete_file_fn,
    ) -> Dict[str, Any]:
        from provider_core.reconciliation import run_reconciliation_v2
        import asyncio
        if self.reconciliation_state.status == "reconciling":
            return {"status": "already_running", "message": "Reconciliation already in progress"}

        async def perform_reconciliation():
            try:
                await run_reconciliation_v2(
                    provider_id=self.provider_id,
                    backend_url=backend_url,
                    reconciliation_state=self.reconciliation_state,
                    max_concurrent_downloads=self.runtime_config.get("max_concurrent_downloads", 2),
                    hf_token=hf_token,
                    civitai_token=civitai_token,
                    storage_label=storage_label,
                    validate_existing=validate_existing_fn,
                    list_existing_files=list_existing_files_fn,
                    download_file=download_file_fn,
                    delete_file=delete_file_fn
                )
            except Exception as e:
                logger.exception(f"[{self.provider_id}] Fatal error in reconciliation task: {e}")
                self.reconciliation_state.status = "error"

        asyncio.create_task(perform_reconciliation())
        return {"status": "started", "message": "Reconciliation started"}

    @abc.abstractmethod
    async def get_health(self) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def get_info(self) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def run_reconciliation(self) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def inference(self, request: Any):
        pass

    @abc.abstractmethod
    async def setup_models(self) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def download_model(self, request: Any) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def list_models(self, request: Optional[Any] = None) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def delete_model(self, request: Any) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def get_file(self, path: str):
        pass

    @abc.abstractmethod
    async def delete_file(self, path: str) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def upload_file(self, request: Any) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    async def get_deploy_status(self) -> Dict[str, Any]:
        return _DEPLOY_STATE or {"status": "unknown"}

    @abc.abstractmethod
    async def validate_models(self, request: Any) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def validate_all_models(self) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def get_object_info(self) -> Dict[str, Any]:
        pass
