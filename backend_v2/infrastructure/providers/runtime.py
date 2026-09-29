# Every provider container MUST be named `tnhcomfy-{PROVIDER_ID}` so the
# backend can detect it and attach the provider auth header. Re-exported from
# `infrastructure.provider_naming`, which is a leaf module precisely so
# `infrastructure/http_client.py` can import it without running this package's
# `__init__` — which imports `beam_provider`, which imports `http_client` back,
# so the order of the first import decided whether the process started.
from infrastructure.provider_naming import (  # noqa: F401 - re-exported
    PROVIDER_CONTAINER_PREFIX,
    provider_container_name,
)


def _publish_provider_host(base: str) -> None:
    """Record the host we are about to talk to as one of ours.

    The token allowlist used by `infrastructure.http_client` is built from the
    provider rows, but the address actually dialled here can be a Docker container
    id — which changes every time the container is recreated, and is written back
    to `discovery_url` by the worker's own discovery loop only once its next
    heartbeat lands.

    That gap is a real outage: a recreated provider is dispatched to for up to a
    heartbeat, the host is not in the allowlist, the shared worker token is not
    attached, and the worker answers 401 — which is reported as "the provider
    rejected or crashed on this job", with nothing pointing at auth.

    So the resolver publishes what it resolved. This is the point at which the
    backend knows with certainty that the host IS one of our providers, which is
    strictly more information than the database has.
    """
    try:
        from urllib.parse import urlparse

        from infrastructure.http_client import publish_provider_host

        host = (urlparse(base).hostname or "").lower()
        if host:
            publish_provider_host(host)
    except Exception:  # pragma: no cover - never let this break a dispatch
        pass


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
    _publish_provider_host(base)
    return f"{base.rstrip('/')}/health"
