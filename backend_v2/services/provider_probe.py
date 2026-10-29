"""Best-effort Modal management-plane metadata probe (P4 spike).

Warm-window inference (P1) is the guaranteed readiness signal for Modal/Beam;
this module is the bonus: metadata RPCs on the Modal management plane, which
are FREE — they never schedule a container, never cold-boot, never bill.

Two calls:

* ``modal.App.lookup(app_name, create_if_missing=False)`` — one real metadata
  RPC. It answers three questions the config-only health check cannot: does
  the app exist, is the token still valid, is the workspace reachable.
* ``app.info()`` — a second metadata RPC returning deployment/function
  topology (``AppInfo`` with functions/servers/lifecycle). Note the known
  limitation: NO live container counts.

Anything that goes wrong is caught and summarised — a revoked token, a
deleted app or a network outage all end up as ``{"reachable": False,
"error": "..."}`` rather than raised, because this is a spike bolted next to
a guaranteed primary signal, not a gate.

Optionally (``COMFY_MODAL_CONTAINER_STATS=1``, default OFF) one best-effort
attempt at the undocumented webapp app-stats REST endpoints is made to look
for live container counts. Failures are logged once per process and ignored.
Zero function invocations anywhere in this module — ever.
"""

import asyncio
import os
import time
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("provider_probe")

#: Off unless explicitly enabled: the endpoints are undocumented and the spike
#: may find nothing usable — the warm window is the approved fallback anyway.
CONTAINER_STATS_ENABLED = os.getenv("COMFY_MODAL_CONTAINER_STATS", "0") in (
    "1", "true", "yes",
)

MANAGEMENT_TIMEOUT_SECONDS = 15.0
CONTAINER_STATS_TIMEOUT_SECONDS = 5.0
#: Results older than this may be re-fetched by the poller. The poller runs
#: every 30s and passes by freely, so this only throttles on-demand callers.
MANAGEMENT_CACHE_TTL_SECONDS = 30.0

_webapp_stats_failure_logged = False


class _ModalUnavailableError(RuntimeError):
    """The modal SDK is not importable in this process."""


def _require_modal():
    try:
        import modal  # bundled in the container at /data/modal_pkg
        return modal
    except ImportError as exc:
        raise _ModalUnavailableError(str(exc)) from exc


async def _call_aio_or_thread(fn, *args, **kwargs):
    """Run a Modal SDK call whichever way the installed SDK supports.

    Modal methods grow an ``.aio`` twin (see the engine's
    ``Client.from_credentials.aio`` handling); when present use it, otherwise
    run the sync call off the event loop.
    """
    aio = getattr(fn, "aio", None)
    if callable(aio):
        return await aio(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


def _summarize_error(exc: Exception) -> str:
    return str(exc)[:200]


def _looks_missing_app(exc: Exception) -> bool:
    """Heuristic on the exception text: did lookup fail because of the app?"""
    text = str(exc).lower()
    markers = ("not found", "does not exist", "no app", "invalid app", "deleted")
    return any(m in text for m in markers)


def _looks_revoked_token(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = ("unauthorized", "forbidden", "invalid token", "credentials")
    return any(m in text for m in markers)


async def probe_modal_management(engine) -> dict[str, Any]:
    """Free metadata probe: does the configured Modal app exist and respond?

    Returns a small opaque payload for the provider page's telemetry block:

    ``{reachable, app_exists, app_name, function_names?, function_count?,
       token_valid?, error?, managed_check: True}``
    """
    result: dict[str, Any] = {
        "managed_check": True,  # distinguishes this from warm-window inference
        "reachable": False,
        "app_exists": None,  # None = unknown, False = confirmed gone
        "app_name": getattr(engine, "app_name", "") or "",
    }

    try:
        modal = _require_modal()
        client = await engine.get_client_async()
    except Exception as exc:
        result["error"] = _summarize_error(exc)
        return result

    app_name = result["app_name"]
    if not app_name:
        result["error"] = "no app_name configured"
        return result

    try:
        app = await asyncio.wait_for(
            _call_aio_or_thread(
                modal.App.lookup, app_name, create_if_missing=False, client=client
            ),
            timeout=MANAGEMENT_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        result["app_exists"] = False if _looks_missing_app(exc) else None
        if _looks_revoked_token(exc):
            result["token_valid"] = False
        result["error"] = _summarize_error(exc)
        logger.info(
            "modal_management_probe_failed",
            provider_id=getattr(engine, "provider_id", "?"),
            app_name=app_name,
            error=result["error"],
        )
        return result

    result["reachable"] = True
    result["app_exists"] = True

    # Function topology. `info()` is metadata-only; if the SDK changes shape
    # around it, degrade to the lookup-only answer above.
    try:
        info = await asyncio.wait_for(
            _call_aio_or_thread(app.info),
            timeout=MANAGEMENT_TIMEOUT_SECONDS,
        )
        functions = getattr(info, "functions", None)
        if functions is None and isinstance(info, dict):
            functions = info.get("functions")
        names: list[str] = []
        if isinstance(functions, dict):
            names = sorted(str(key) for key in functions.keys())
        elif isinstance(functions, list):
            for entry in functions:
                if isinstance(entry, dict):
                    name = entry.get("function_name") or entry.get("name") or entry
                    names.append(str(name))
                else:
                    names.append(str(entry))
        result["function_count"] = len(names)
        result["function_names"] = names[:20]
    except Exception as exc:
        result["info_error"] = _summarize_error(exc)

    return result


async def probe_modal_container_stats(engine) -> dict[str, Any] | None:
    """Undocumented webapp container-count REST, behind the env flag.

    Default OFF (``COMFY_MODAL_CONTAINER_STATS=1`` enables). Expected to
    answer nothing usable; failures are logged once per process and ignored.
    NEVER schedules a function.
    """
    global _webapp_stats_failure_logged
    if not CONTAINER_STATS_ENABLED:
        return None

    import httpx

    app_name = getattr(engine, "app_name", "") or ""
    if not app_name:
        return None
    token = f"{getattr(engine, 'token_id', '')}:{getattr(engine, 'token_secret', '')}"
    headers = {"Authorization": f"Basic Modal {token}"}
    urls = (
        f"https://api.modal.com/api/webapp/apps/{app_name}",
        f"https://api.modal.com/api/webapp/app/{app_name}/servers",
    )
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=CONTAINER_STATS_TIMEOUT_SECONDS) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return {"container_stats": data if isinstance(data, dict) else {"raw": data}}
            logger.debug(
                "modal_container_stats_endpoint_unavailable",
                url=url.split("?")[0],
                status_code=resp.status_code,
            )
        except Exception as exc:
            if not _webapp_stats_failure_logged:
                _webapp_stats_failure_logged = True
                logger.info(
                    "modal_container_stats_probe_failed",
                    error=_summarize_error(exc),
                )
    return None


# --------------------------------------------------------------------------
# Cached façade for the telemetry poller
# --------------------------------------------------------------------------

_probe_cache: dict[str, tuple[float, dict[str, Any]]] = {}


async def probe_modal_management_cached(provider_id: str, engine) -> dict[str, Any]:
    """Cache the per-pass probe so on-demand callers reuse the poller's result."""
    cached = _probe_cache.get(provider_id)
    if cached is not None and time.monotonic() - cached[0] < MANAGEMENT_CACHE_TTL_SECONDS:
        return dict(cached[1])
    result = await probe_modal_management(engine)
    if CONTAINER_STATS_ENABLED:
        extra = await probe_modal_container_stats(engine)
        if extra:
            result.update(extra)
    _probe_cache[provider_id] = (time.monotonic(), result)
    return dict(result)


def get_cached_management(provider_id: str) -> dict[str, Any] | None:
    """The most recent probe result for a provider, if any."""
    cached = _probe_cache.get(provider_id)
    return dict(cached[1]) if cached else None


def forget_probe(provider_id: str) -> None:
    _probe_cache.pop(provider_id, None)
