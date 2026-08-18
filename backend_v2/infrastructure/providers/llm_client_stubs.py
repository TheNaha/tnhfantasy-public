# Graceful stubs for LLM provider clients
# LLM provider types (google, anthropic, openai_compat, ...) are API-backed:
# they carry no model files and no file proxy. The ServerlessProvider base
# declares four abstract methods that only make sense for image providers;
# these mixins implement them with informative errors instead of leaving the
# class abstract (which crashed create_provider_client at runtime).
from typing import Any

from core.exceptions import ProviderError

_MODEL_MGMT_NOT_SUPPORTED = (
    "Provider '{provider_type}' (id={provider_id}) is an LLM API provider: "
    "it has no worker-side model file storage. Model download/list/delete "
    "operations are not applicable to this provider type."
)

_FILE_PROXY_NOT_SUPPORTED = (
    "Provider '{provider_type}' (id={provider_id}) is an LLM API provider: "
    "it exposes no HTTP file proxy. File operations are only supported for "
    "image provider containers (modal, beam, direct_url)."
)


class LLMClientGracefulStubMixin:
    """Implements the file-oriented ServerlessProvider abstract methods with
    informative ProviderError exceptions so LLM-only provider classes remain
    instantiable."""

    async def download_model(
        self,
        url: str,
        path: str,
        token: str = None,
        preview_url: str = None,
        metadata: dict = None,
        info: dict | None = None,
    ) -> dict[str, Any]:
        raise ProviderError(self.provider_id, _MODEL_MGMT_NOT_SUPPORTED.format(
            provider_type=self.provider_type, provider_id=self.provider_id
        ))

    async def list_models(self, directory: str) -> list[dict[str, Any]]:
        raise ProviderError(self.provider_id, _MODEL_MGMT_NOT_SUPPORTED.format(
            provider_type=self.provider_type, provider_id=self.provider_id
        ))

    async def delete_model(self, path: str) -> bool:
        raise ProviderError(self.provider_id, _MODEL_MGMT_NOT_SUPPORTED.format(
            provider_type=self.provider_type, provider_id=self.provider_id
        ))

    def get_file_proxy(self):
        raise ProviderError(self.provider_id, _FILE_PROXY_NOT_SUPPORTED.format(
            provider_type=self.provider_type, provider_id=self.provider_id
        ))