import abc
from typing import Dict, Any, Optional

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

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        updated = []
        for key, value in updates.items():
            if key in self.runtime_config:
                self.runtime_config[key] = value
                updated.append(key)
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
        pass

    @abc.abstractmethod
    async def validate_models(self, request: Any) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    async def validate_all_models(self) -> Dict[str, Any]:
        pass
