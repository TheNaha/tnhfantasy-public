# Every provider container MUST be named `tnhcomfy-{PROVIDER_ID}` so the
# backend can detect it and attach the provider auth header. This constant is
# the single source of truth: `provider_container_name` builds the name, and
# `infrastructure/http_client.py` matches the hostname against this prefix.
# Do not re-spell the literal.
PROVIDER_CONTAINER_PREFIX = "tnhcomfy-"


def provider_container_name(provider_id: str) -> str:
    return f"{PROVIDER_CONTAINER_PREFIX}{provider_id}"


def get_provider_worker_base_url(provider_id: str, port: int = 8000) -> str:
    return f"http://{provider_container_name(provider_id)}:{port}"


def resolve_provider_health_url(provider, port: int = 8000) -> str:
    """Best-effort ``/health`` URL for a provider.

    Prefers the provider's configured ``worker_url`` (serverless deployments
    like Modal/Beam have no Docker-DNS name), falling back to the container
    network hostname for containerized workers.
    """
    config = getattr(provider, "config", {}) or {}
    container_config = getattr(provider, "container_config", {}) or {}
    worker_url = (
        getattr(provider, "worker_url", None)
        or config.get("worker_url")
        or config.get("discovery_url")
        or container_config.get("internal_url")
    )
    base = worker_url or get_provider_worker_base_url(provider.id, port)
    return f"{base.rstrip('/')}/health"
