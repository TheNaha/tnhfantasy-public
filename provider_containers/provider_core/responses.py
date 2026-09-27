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
    "config_fault_detail",
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
    retryable, and a provider with no ``PROVIDER_WORKER_TOKEN`` answers 503 on
    every protected route: the dispatcher read that as "try this elsewhere",
    failed the job over to a second provider, and spent real money on a request
    that could not succeed.

    5xx stays retryable by default — an unreachable upstream genuinely is
    transient — but a raiser that knows the fault is permanent says so by
    putting ``"retryable": False`` in a dict detail (see
    :func:`config_fault_detail`). 4xx is never retryable.
    """
    if isinstance(detail, dict) and detail.get("retryable") is not None:
        return bool(detail["retryable"])
    return status_code >= 500


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
