# Provider Registry - Type-agnostic provider configuration system
# This module abstracts provider-specific logic from the core backend

import base64
from contextlib import asynccontextmanager
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from infrastructure.http_client import get_http_client
from infrastructure.logging import provider_logger

from infrastructure.providers.base import MAX_INLINE_FILE_BYTES, FileProxyProvider

logger = provider_logger()


def clean_registry_dict(d):
    """Return a new dict with only string keys and non-None values."""
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if isinstance(k, str) and v is not None}


# Forward a provider's file body in chunks. 8 MiB is a reasonable trade between
# syscall count and per-chunk overhead at these sizes.
_STREAM_CHUNK_BYTES = 8 * 1024 * 1024

# Long enough for a multi-GB checkpoint to arrive, short enough that a dead
# provider does not hold a worker indefinitely.
_STREAM_TIMEOUT_SECONDS = 600.0


class FileTooLargeError(Exception):
    """A file was too large to return inline. Use `stream_file` instead."""


async def _iter_chunks(stream_ctx) -> AsyncIterator[bytes]:
    """Yield the body of an open response in chunks, closing it when done.

    Takes the context manager rather than the response so the `async with` stays
    open for the whole iteration — an httpx streaming response is only valid inside
    its own `stream()` block, which is why `stream_file` is a plain method
    returning an async iterator rather than an `async def` generator.
    """
    async with stream_ctx as response:
        async for chunk in response.aiter_bytes(_STREAM_CHUNK_BYTES):
            yield chunk


class HttpFileProxy(FileProxyProvider):
    """Shared file proxy implementation for HTTP-based provider containers."""

    def __init__(self, provider_id: str, config: dict[str, Any], base_url: str):
        # Was not inheriting FileProxyProvider at all, so the ABC's method set was
        # documentation rather than a contract and nothing verified it. Every
        # provider type uses this class, so there is only one implementation to
        # satisfy — including `stream_file`, which is the point.
        super().__init__(provider_id, config)
        self.base_url = base_url.rstrip("/")

    def stream_file(self, path: str):
        """Yield the provider's file in chunks, never materialising it.

        `get_file` was the only way to read a file, and it returned `bytes`. For a
        model that is 7 GB in the worker, 7 GB in the response object, and — on the
        base64 JSON path the engines still use for small payloads — a 9.3 GB string
        on top. This is the path a large file should take.
        """
        client = get_http_client()
        encoded_path = urllib.parse.quote(path, safe="/")
        url = f"{self.base_url}/get-file/{encoded_path}"

        @asynccontextmanager
        async def _open():
            async with client.stream("GET", url, timeout=_STREAM_TIMEOUT_SECONDS) as response:
                if response.status_code != 200:
                    raise Exception(f"Failed to get file: {response.status_code}")
                yield response

        return _iter_chunks(_open())

    async def get_file(self, path: str) -> bytes:
        """Retrieve a small file as bytes.

        Refuses anything past `MAX_INLINE_FILE_BYTES`. A caller that genuinely wants
        a large file should use `stream_file`; returning bytes for one would either
        exhaust memory or silently truncate, and neither is a useful failure.
        """
        client = get_http_client()
        encoded_path = urllib.parse.quote(path, safe="/")
        url = f"{self.base_url}/get-file/{encoded_path}"
        response = await client.get(url)
        if response.status_code == 200:
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_INLINE_FILE_BYTES:
                raise FileTooLargeError(
                    f"{path} is {int(declared)} bytes, past the {MAX_INLINE_FILE_BYTES} byte "
                    "inline limit. Use stream_file() for a file this size."
                )
            content_type = response.headers.get("content-type", "") or ""
            if not isinstance(content_type, str):
                content_type = str(content_type)
            if "json" in content_type.lower() or response.content[:1] in (b"{", b"["):
                try:
                    payload = response.json()
                except Exception:
                    payload = None
                if isinstance(payload, dict):
                    content_base64 = payload.get("content_base64")
                    if isinstance(content_base64, str):
                        if len(content_base64) > MAX_INLINE_FILE_BYTES:
                            raise FileTooLargeError(
                                f"{path} base64 payload is {len(content_base64)} bytes, past the "
                                f"{MAX_INLINE_FILE_BYTES} byte inline limit."
                            )
                        return base64.b64decode(content_base64)
            return response.content
        raise Exception(f"Failed to get file: {response.status_code}")

    async def delete_file(self, path: str) -> bool:
        client = get_http_client()
        url = f"{self.base_url}/delete-file"
        try:
            response = await client.request("DELETE", url, json={"path": path})
            if response.status_code == 200:
                return True
        except Exception as exc:
            logger.warning("remove_file_request_failed", path=path, error=str(exc))
        response = await client.post(url, json={"path": path})
        return response.status_code == 200

    def get_proxy_url(self) -> str:
        return self.base_url


@dataclass
class ProviderTypeConfig:
    """
    Configuration schema for a provider type.
    Each provider type (modal, beam, direct_url, openai_compat, anthropic, google) registers one of these.
    """
    type_name: str
    
    # Credential fields
    required_credentials: list[str] = field(default_factory=list)
    optional_credentials: list[str] = field(default_factory=list)
    
    # Config fields
    required_config: list[str] = field(default_factory=list)
    optional_config: list[str] = field(default_factory=list)
    
    # Environment variable builder function
    # Signature: (credentials: Dict, config: Dict) -> Dict[str, str]
    env_builder: Callable[[dict, dict], dict[str, str]] | None = None
    
    # Worker image name for this provider type
    worker_image: str = "comfy-provider"
    
    # Default port for worker container
    default_port: int = 8000
    
    # The ServerlessProvider class for API interactions
    client_class: type[Any] | None = None
    
    def build_env_vars(self, credentials: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
        """
        Build container environment variables from credentials and config.
        
        Args:
            credentials: Provider credentials dict
            config: Provider config dict
            
        Returns:
            Environment variables dict for container
        """
        if self.env_builder:
            return self.env_builder(credentials, config)
        return {}
    
    def validate_credentials(self, credentials: dict[str, Any]) -> list[str]:
        """
        Validate that required credentials are present.
        
        Returns:
            List of missing required credential fields
        """
        missing = []
        for field_name in self.required_credentials:
            if not credentials.get(field_name):
                missing.append(field_name)
        return missing
    
    def validate_config(self, config: dict[str, Any]) -> list[str]:
        """
        Validate that required config fields are present.
        
        Returns:
            List of missing required config fields
        """
        missing = []
        for field_name in self.required_config:
            if not config.get(field_name):
                missing.append(field_name)
        return missing


class ProviderRegistry:
    """
    Registry of available provider types.
    
    Provider types register themselves on import, making the system extensible.
    The backend uses this registry to handle provider-specific logic without
    knowing about specific providers.
    
    Usage:
        # Registration (in modal_config.py or beam_config.py)
        ProviderRegistry.register(MODAL_PROVIDER_CONFIG)
        
        # Usage (in main.py or container_manager.py)
        env_vars = ProviderRegistry.build_container_env(provider)
    """
    _types: dict[str, ProviderTypeConfig] = {}
    
    @classmethod
    def register(cls, config: ProviderTypeConfig) -> None:
        """Register a provider type configuration."""
        cls._types[config.type_name] = config
        logger.info("provider_type_registered", type_name=config.type_name)
    
    @classmethod
    def get(cls, type_name: str) -> ProviderTypeConfig | None:
        """Get configuration for a provider type."""
        return cls._types.get(type_name)
    
    @classmethod
    def get_all(cls) -> dict[str, ProviderTypeConfig]:
        """Get all registered provider types."""
        return cls._types.copy()
    
    @classmethod
    def is_registered(cls, type_name: str) -> bool:
        """Check if a provider type is registered."""
        return type_name in cls._types
    
    @classmethod
    def build_container_env(cls, provider: Any) -> dict[str, str]:
        """
        Build container environment variables for a provider.
        
        This is the main abstraction point - the backend calls this method
        without knowing what type of provider it is.
        
        Args:
            provider: Provider entity (with type, credentials, config attributes)
            
        Returns:
            Environment variables dict for the provider's container
        """
        type_config = cls.get(provider.type)
        if not type_config:
            logger.warning("unknown_provider_type", provider_type=provider.type)
            return {}
        
        credentials = provider.credentials or {}
        config = provider.config or {}
        
        return type_config.build_env_vars(credentials, config)
    
    @classmethod
    def validate_provider(cls, provider_type: str, credentials: dict, config: dict) -> dict[str, list[str]]:
        """
        Validate a provider's credentials and config.
        
        Returns:
            Dict with 'credentials' and 'config' keys, each containing list of missing fields
        """
        type_config = cls.get(provider_type)
        if not type_config:
            return {"error": [f"Unknown provider type: {provider_type}"]}
        
        return {
            "credentials": type_config.validate_credentials(credentials),
            "config": type_config.validate_config(config)
        }
    
    @classmethod
    def get_worker_image(cls, provider_type: str, worker_type: str | None = None) -> str:
        """Get the worker image name for a provider type.

        `worker_type` overrides the type-derived image. A TTS provider is
        `type="modal"`, so the type alone resolves to the *image* worker's image
        — and a deploy built that Dockerfile, which does not copy `tts_worker/`
        at all, so it produced an image whose entrypoint did not exist. The
        worker kind is the thing that actually selects the Dockerfile
        (`container_manager.build_worker_image`), so it has to select the image
        tag here too or the two disagree.
        """
        if worker_type in {"tts"}:
            return "tnhcomfy/tts-worker:latest"
        type_config = cls.get(provider_type)
        if type_config:
            worker_image = type_config.worker_image
            if ":" in worker_image:
                return worker_image
            return f"{worker_image}:latest"
        return f"comfy-provider-{provider_type}:latest"
    
    @classmethod
    def get_default_port(cls, provider_type: str) -> int:
        """Get the default worker port for a provider type."""
        type_config = cls.get(provider_type)
        return type_config.default_port if type_config else 8000
