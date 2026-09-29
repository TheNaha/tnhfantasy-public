"""Provider container naming.

Its own leaf module because `infrastructure/http_client.py` needs
`PROVIDER_CONTAINER_PREFIX` to decide which hosts get the shared worker token,
and importing it from `infrastructure.providers.runtime` runs that package's
`__init__` — which imports `beam_provider`, which imports `get_http_client`
from the half-initialised `http_client`. Order-dependent: the app booted only
because something imported `infrastructure.providers` first, so any new entry
point that reached for the HTTP client first died at import.
"""

PROVIDER_CONTAINER_PREFIX = "tnhcomfy-"


def provider_container_name(provider_id: str) -> str:
    return f"{PROVIDER_CONTAINER_PREFIX}{provider_id}"
