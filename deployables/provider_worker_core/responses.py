"""One response dialect for every provider engine.

Four shapes were live across nine engine methods, all answering HTTP 200, so a
caller could not distinguish success from failure by status code:

  {"success": bool, ...}                    modal / beam / remote_comfy / direct_url
  {"status": "error", ...} with 200         direct_url.upload_file
  bare {"files": [...]} with no status      every LLM engine's list_models
  raw ``response.json()`` pass-through      beam / remote_comfy (setup, upload,
                                           delete, validate)

Every engine now builds its answers here, so the dialect is stated once and a
fifth variant cannot appear by accident.

Canonical shapes
----------------
success::

    {"status": "success" | "queued", "success": True, "message": str,
     "provider": str, "files": [...], "result": Any, **extra}

failure::

    {"status": "error", "success": False, "message": str,
     "retryable": bool, "code": int, "provider": str, **extra}

``files`` is always present as a list (empty when there are none) and ``message``
is always a human-readable string, because those are the two keys the backend
actually reads: ``data.get("files")`` in ``api/routes/world_vault/llm_config.py``
and ``api/routes/models/maintenance.py``, and
``response_body.get("status") == "error"`` in ``api/routes/files.py``.
``success`` is a bool *alongside* ``status`` rather than instead of it, so the
nine call sites that used to answer with only that bool keep answering with it.

The envelope is strictly additive over the shapes it replaces, and
``build_status_response`` / ``build_error_response`` (the pydantic models in
``provider_core/models.py``) remain the source of every declared field, so a
field the backend depends on cannot drift out from under it. Keys the envelope
owns can never be overwritten by an ``extra`` value or by an adopted upstream
body: merging is envelope-last, so an upstream cannot downgrade a success to a
failure by omission.

Not every response goes through here, on purpose:

* ``get_object_info`` is a pass-through of ComfyUI's own ``/object_info``
  document, which ``api/routes/nodes.py`` returns verbatim to the UI. Wrapping
  it would corrupt the payload.
* ``get_health`` / ``get_info`` / ``get_storage_stats`` /
  ``get_reconciliation_status`` / ``get_config`` are state snapshots read by key
  name, not operation results, and are already consistent between engines.
* the NDJSON ``/inference`` stream speaks ``TaskEvent`` (see ``TaskEvent`` in
  ``provider_core/models.py``), which is a different contract by design.
"""

from typing import Any, Dict, Iterable, List, Optional

from provider_core.models import build_error_response, build_status_response

__all__ = [
    "ok",
    "failed",
    "outcome",
    "files_response",
    "files_from",
    "model_file_entries",
    "from_upstream",
    "retryable_for_status",
    "retryable_for_exception",
    "config_fault_detail",
    "llm_healthy",
    "llm_unhealthy",
]

# Keys the envelope owns. An adopted upstream body or an ``extra`` keyword can
# never overwrite one of these.
_ENVELOPE_KEYS = frozenset(
    {"status", "success", "message", "provider", "files", "result", "retryable", "code"}
)


def _merge(payload: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """Merge caller-supplied keys in, without letting them clobber the envelope."""
    for key, value in extra.items():
        if key not in _ENVELOPE_KEYS:
            payload.setdefault(key, value)
    return payload


def ok(
    message: str,
    *,
    provider: Optional[str] = None,
    files: Optional[Iterable[Dict[str, Any]]] = None,
    result: Any = None,
    status: str = "success",
    **extra: Any,
) -> Dict[str, Any]:
    """Build the canonical success payload.

    ``files`` is always emitted (as ``[]`` when empty) because it is the key the
    backend reads on ``/list-models``; the other optional keys are dropped when
    unset, matching ``StatusResponse.model_dump(exclude_none=True)``.
    """
    payload = build_status_response(
        status,  # type: ignore[arg-type]
        message,
        provider=provider,
        result=result,
        files=list(files) if files is not None else None,
    )
    payload["success"] = True
    payload.setdefault("files", [])
    return _merge(payload, extra)


def failed(
    message: str,
    *,
    code: Optional[int] = None,
    retryable: bool = False,
    provider: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build the canonical failure payload.

    ``retryable`` defaults to ``False``: a failure is treated as permanent until
    a caller says otherwise, because the backend turns a retryable failure into
    a dispatch to a *second* provider (see ``services/provider_client.py``),
    which spends real money re-running a request that cannot succeed.
    """
    payload = build_error_response(message, retryable=retryable, code=code)
    payload["success"] = False
    if provider is not None:
        payload["provider"] = provider
    return _merge(payload, extra)


def outcome(
    succeeded: bool,
    message: str,
    *,
    provider: Optional[str] = None,
    code: Optional[int] = None,
    retryable: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    """Bridge a boolean result into the dialect.

    Replaces the nine ``{"success": bool, "message": ...}`` returns, which were
    distinguishable from success by nothing but that one bool.
    """
    if succeeded:
        return ok(message, provider=provider, **extra)
    return failed(
        message,
        code=code,
        retryable=retryable,
        provider=provider,
        **extra,
    )


def files_response(
    files: Iterable[Any],
    *,
    message: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap a bare ``{"files": [...]}`` body (the LLM engines' old shape)."""
    entries = model_file_entries(files)
    return ok(
        message if message is not None else f"Listed {len(entries)} models",
        provider=provider,
        files=entries,
    )


def files_from(response_json: Any) -> List[Any]:
    """Pull the file list out of a `/list-models` body, whatever shape it is.

    This is the `response.json().get("files", [])` that three call sites used to
    inline. That expression raises ``AttributeError`` the moment the body is not a
    dict — a proxy in front of the storage app answering a bare JSON array, or a
    401 HTML page, becomes an unhandled 500 that discards the real status and
    makes an odd response look like a worker bug instead of the empty listing it
    effectively is.

    Lives here rather than in one client so the storage dialect and the worker
    that adopts it cannot disagree about what an unexpected body means.
    """
    if isinstance(response_json, dict):
        files = response_json.get("files")
        return files if isinstance(files, list) else []
    if isinstance(response_json, list):
        return response_json
    return []


def model_file_entries(files: Iterable[Any]) -> List[Dict[str, Any]]:
    """Normalise a model listing into dict entries.

    The LLM engines return ``{"path": name, "name": name}`` (there is no
    directory or size on a hosted model), and the backend accepts both dicts and
    bare strings (``llm_config.py`` handles either), so plain strings are
    wrapped rather than dropped.
    """
    entries: List[Dict[str, Any]] = []
    for item in files or []:
        if isinstance(item, dict):
            entries.append(item)
        elif isinstance(item, str) and item:
            entries.append({"path": item, "name": item})
    return entries


def from_upstream(
    payload: Any,
    *,
    provider: Optional[str] = None,
    message: Optional[str] = None,
    code: Optional[int] = None,
    retryable: Optional[bool] = None,
    files: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Put a third-party response body inside the dialect.

    The upstream's own keys are preserved verbatim — a Beam ``/setup`` returns
    ``directories``, a remote agent's ``/upload-file`` returns ``path`` and
    ``size``, a validation returns ``total_invalid`` — so adopting a pass-through
    does not lose the payload. An upstream that reports failure itself
    (``status == "error"`` or ``success is False``) produces a failure envelope
    rather than a success one, and its ``retryable``/``code`` are honoured when
    it supplied them.
    """
    body: Dict[str, Any] = dict(payload) if isinstance(payload, dict) else {}
    upstream_failed = body.get("status") == "error" or body.get("success") is False
    default_message = (
        body.get("message")
        or ("Upstream reported failure" if upstream_failed else "Upstream call completed")
    )
    upstream_files = files if files is not None else body.get("files")

    if upstream_failed:
        return _merge(
            failed(
                str(default_message),
                code=code if code is not None else body.get("code"),
                retryable=(
                    bool(body["retryable"])
                    if body.get("retryable") is not None
                    else bool(retryable)
                ),
                provider=provider,
            ),
            body,
        )

    return _merge(
        ok(
            message if message is not None else str(default_message),
            provider=provider,
            files=upstream_files,
        ),
        body,
    )


def retryable_for_status(status_code: int, detail: Any = None) -> bool:
    """Decide the ``retryable`` flag for an HTTP status.

    A blanket ``status_code >= 500`` is what made a 503 advertise itself as
    retryable, and a provider with no ``COMFY_PROVIDER_TOKEN`` answers 503 on
    every protected route: the dispatcher read that as "try this elsewhere",
    failed the job over to a second provider, and spent real money on a request
    that could not succeed.

    5xx stays retryable by default — an unreachable upstream genuinely is
    transient — but a raiser that knows the fault is permanent says so by
    putting ``"retryable": False`` in a dict detail (see
    :func:`config_fault_detail`).

    4xx is otherwise permanent, with two deliberate exceptions: **429** and
    **408**. Both are the server asking for a retry rather than reporting a
    mistake — 429 is a rate limit and 408 is a request timeout — so failing the
    job outright over either discards work the provider explicitly invited us to
    repeat. Every other 4xx (400, 401, 403, 404, 409, 413, 422 …) means the
    request itself is wrong, and re-dispatching it reproduces the failure
    exactly, on every provider in the pool, for the same money.
    """
    if isinstance(detail, dict) and detail.get("retryable") is not None:
        return bool(detail["retryable"])
    if status_code in (408, 429):
        return True
    return status_code >= 500


def retryable_for_exception(exc: BaseException) -> bool:
    """Decide the ``retryable`` flag for a caught exception.

    Every LLM engine used a hardcoded ``retryable=True`` on its failure event.
    A malformed ``messages`` array or a 400 from the upstream cannot succeed on a
    second attempt, so the flag made the backend's reducer raise
    ``ProviderCallError(is_retryable=True)`` and the dispatcher re-ran the request
    across every other provider — real GPU/token spend on a request that can
    never work.

    The rule, in order:

    1. An explicit marker wins. ``httpx.HTTPStatusError`` carries the upstream
       status, so 4xx is permanent and 5xx / 429 are transient.
    2. ``TimeoutException`` and ``ConnectError`` are transient by nature.
    3. Anything else (a parsing bug, a TypeError, a programming error) is
       permanent: retrying it just spends the same money for the same failure.

    The ComfyUI image path already gets this right by accident — its
    ``_queue_prompt`` errors carry no ``retryable`` key, so
    ``comfy_status_to_task_event`` leaves it ``None`` and the backend treats it
    as ``False``.
    """
    marker = getattr(exc, "retryable", None)
    if isinstance(marker, bool):
        return marker

    try:
        import httpx
    except Exception:  # pragma: no cover - httpx is a hard dependency
        httpx = None  # type: ignore[assignment]

    if httpx is not None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return retryable_for_status(status)
        # A bare status on the exception, for raisers that attach one directly.
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            return retryable_for_status(status)
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
            return True

    return False


def config_fault_detail(message: str, **extra: Any) -> Dict[str, Any]:
    """Build a 503 detail that is explicitly not retryable.

    For faults that cannot fix themselves by waiting: a missing worker token, a
    missing Modal app name, a missing Beam API key or URL. The provider is not
    coming back on its own, so the job must fail where it is instead of being
    re-dispatched to another provider.
    """
    detail: Dict[str, Any] = {"message": message, "retryable": False}
    detail.update(extra)
    return detail


# ── LLM health ──────────────────────────────────────────────────────────────
#
# All four LLM engines used to return a hardcoded `{"status": "healthy"}` without
# touching the network. The backend's `_check_provider_health`
# (`services/load_balancer.py`) requires HTTP 200, so it counted a dead endpoint
# as a usable target and dispatched paid LLM jobs at it; the first job then
# failed, and because every error in those files was also marked
# `retryable=True`, the balancer re-dispatched across every other provider.
#
# `direct_url` and `remote_comfy` were already fixed to do a real probe, with the
# failure mode spelled out. The fix was never ported to the LLM side, and each
# engine that got it separately grew its own response shape — which is how
# `openai_compat` came to differ from its three siblings with nothing to explain
# the difference. These two builders are the one shape all four use.
#
# A "healthy" verdict is never a constant: either something was actually
# contacted, or a configuration prerequisite was checked. There is no third
# option.


def llm_healthy(engine: str, provider_id: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": "healthy",
        "provider_id": provider_id,
        "engine": engine,
        "ready": True,
    }
    payload.update(extra)
    return payload


def llm_unhealthy(
    engine: str,
    provider_id: str,
    detail: str,
    *,
    retryable: bool = False,
    **extra: Any,
) -> Dict[str, Any]:
    """A health verdict the backend can act on.

    `retryable` is the field that matters operationally. `False` — the default —
    marks a fault that will not fix itself by waiting: a missing key, a name that
    resolves to nothing, a 4xx. `True` is for a connection that failed or a 5xx,
    which genuinely can come back.

    The prefix is `config_fault:` when nothing about waiting will help and
    `probe_failed:` when it might, so an operator reading a provider panel can
    tell "this needs a person" from "this is having a moment" without cross-
    referencing the status code.
    """
    prefix = "probe_failed:" if retryable else "config_fault:"
    payload: Dict[str, Any] = {
        "status": "unhealthy",
        "provider_id": provider_id,
        "engine": engine,
        "ready": False,
        "detail": f"{prefix} {detail}",
        "retryable": retryable,
    }
    payload.update(extra)
    return payload
