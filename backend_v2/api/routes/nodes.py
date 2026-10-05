"""`/api/nodes/*` — the node graph of a provider, fetched from its ComfyUI.

Two measured costs lived on one endpoint, and they are independent:

* **2.7 s and 2.4 MB per call.** `/object-info` on the worker spins ComfyUI up to
  introspect itself, so the answer is expensive to compute and identical for
  every client until the provider's install changes. `/advanced` fetches it on
  first paint — twice, see the note in `get_object_info` — and measured 2.345 /
  3.033 s over three warm runs for 2,388 kB raw / 321 kB gzip.
* **A payload four times larger than what the caller reads.** See
  `node_schema_digest`.

Both are fixed here rather than at the client: the cache is per `provider_id`
with a single flight, and the digest is a projection of the upstream graph.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from cachetools import TTLCache
from fastapi import APIRouter, Depends
from sqlmodel import Session

from api.deps import get_provider_service, get_session
from core.exceptions import (
    NotFoundError,
    ProviderError,
    ProviderTimeoutError,
    ValidationError,
)
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from services.provider_runtime import resolve_provider_runtime_async

logger = get_logger("nodes")

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

# How long one provider's node graph stays usable. The graph only changes when
# the provider's ComfyUI install does — a new custom-node pack, a version bump —
# and the frontend already treats its own copy as stale after five minutes, so a
# backend window longer than that buys nothing and a shorter one would only add
# upstream load. 16 entries is well past the number of providers a deployment
# has; the cache is bounded rather than allowed to grow with provider ids.
#
# Both projections are cached. Projecting 1,301 nodes is ~40 ms, which would
# otherwise be the entire cost of a cache hit — i.e. the cache would replace a
# 2.7 s upstream extraction with a 40 ms CPU pass and still look like a fix.
_OBJECT_INFO_TTL_SECONDS = 600
_OBJECT_INFO_CACHE_MAXSIZE = 16
_object_info_cache: TTLCache[str, tuple[dict[str, Any], dict[str, Any]]] = TTLCache(
    maxsize=_OBJECT_INFO_CACHE_MAXSIZE, ttl=_OBJECT_INFO_TTL_SECONDS
)

# One lock per (provider_id), held across the upstream fetch.
#
# Without it the cache is a stampede waiting for a cold key, and this endpoint
# provably has cold-key stampedes: `/advanced` requests `object_info` twice on
# first paint, so an uncached load is two concurrent 2.7 s upstream extractions
# for one answer. This mirrors `infrastructure.cache._INFLIGHT`; the lock is
# dropped once the result is stored so the map does not grow with the keyspace,
# and the removal is guarded because two waiters can observe the same object.
_object_info_inflight: dict[str, asyncio.Lock] = {}


def invalidate_object_info_cache(provider_id: str | None = None) -> None:
    """Drop cached node graphs, for one provider or all of them.

    Called when a provider's runtime changes — a restart can come back with a
    different install, and serving the pre-restart graph would let a user compose
    against a node that is no longer there.
    """
    if provider_id is None:
        _object_info_cache.clear()
        return
    _object_info_cache.pop(provider_id, None)


# ── the schema digest ────────────────────────────────────────────────────────
#
# The node graph has 1,301 nodes and 2.5 MB on this provider. Reading every
# frontend consumer — `src/utils/NodeRegistry.js`, `src/components/generator/
# NodeSidebar.jsx`, `src/components/generator/ComfyNode.jsx`, and nothing else
# (`rg -l object_info src/` returns only those plus the fetching hook) — the whole
# surface is six node fields and two keys of each input spec.
#
# Dropped, each confirmed absent from every `frontend_v2/src` consumer:
#   node:      input_order, is_input_list, output_is_list, output_tooltips,
#              output_matchtypes, search_aliases, essentials_category,
#              has_intermediate_output, price_badge, api_node, dev_only,
#              experimental, deprecated, python_module
#   input spec: tooltip, min, max, step, round, multiselect, advanced,
#               multiline, control_after_generate, template, display
#
# `description` is kept despite being 79 kB: `NodeSidebar.jsx:79` renders it as
# the palette row's `title`. `min`/`max`/`step` are kept out because
# `ComfyNode.jsx` hard-codes `step="0.01"` / `step="1"` for number inputs and
# reads only `inputDef[1]?.default`; `tooltip` is kept out because nothing
# renders it today, which is a missing feature rather than a contract.
#
# Measured: 2,504,545 B → 1,027,220 B raw (59% smaller), 399,887 B → 224,080 B
# gzipped (44% smaller). `?full=true` still returns the upstream graph
# unmodified for anything that does need the rest of it.
_OBJECT_INFO_NODE_FIELDS = (
    "category",
    "display_name",
    "description",
    "input",
    "output",
    "output_name",
)
_OBJECT_INFO_SPEC_FIELDS = ("default",)


def _spec_digest(spec: Any) -> Any:
    """One input spec reduced to what `ComfyNode` binds: its type/options and `default`.

    A ComfyUI input spec is `[type]` or `[type, {...}]` (or `[[options], {...}]`
    for a combo), and occasionally a bare `{...}`. The list shape is preserved
    exactly, because `ComfyNode.jsx` branches on `inputDef[0]` — `Array.isArray`
    there means "dropdown" — so reordering or flattening the spec would change
    which control a node renders.
    """
    if isinstance(spec, list):
        head = spec[0]
        trimmed = [head]
        for extra in spec[1:]:
            if isinstance(extra, dict):
                kept = {k: v for k, v in extra.items() if k in _OBJECT_INFO_SPEC_FIELDS}
                if kept:
                    trimmed.append(kept)
            else:
                trimmed.append(extra)
        return trimmed
    if isinstance(spec, dict):
        return {k: v for k, v in spec.items() if k in _OBJECT_INFO_SPEC_FIELDS}
    return spec


def node_schema_digest(object_info: dict[str, Any]) -> dict[str, Any]:
    """`object_info` reduced to the fields the node palette and editor bind.

    Anything in the payload that is not a node definition is passed through
    untouched. That is deliberate: `useObjectInfo.js` treats a body carrying
    `status: "error"` as a failure rather than a graph, and a digest that
    silently dropped those keys would turn a diagnosable 200 into an empty
    palette.
    """
    if not isinstance(object_info, dict) or not object_info:
        return object_info

    digest: dict[str, Any] = {}
    for node_name, node in object_info.items():
        if not isinstance(node, dict) or "input" not in node:
            digest[node_name] = node
            continue
        reduced: dict[str, Any] = {}
        for field in _OBJECT_INFO_NODE_FIELDS:
            if field not in node:
                continue
            if field != "input":
                reduced[field] = node[field]
                continue
            declared = node[field] or {}
            reduced["input"] = {
                section: {
                    input_name: _spec_digest(spec)
                    for input_name, spec in (declared.get(section) or {}).items()
                }
                for section in ("required", "optional")
                if declared.get(section)
            }
        digest[node_name] = reduced
    return digest


@router.get("/object_info", response_model=dict[str, Any])
async def get_object_info(
    provider_id: str, full: bool = False, session: Session = Depends(get_session)
):
    """
    The node definition mapping (object_info) for a provider.

    Two things are worth knowing about this endpoint.

    **It is cached per provider, with single flight.** The answer comes from the
    provider's own ComfyUI, which has to spin up to introspect itself, so it cost
    2.345-3.033 s per call for 2,388 kB — and the frontend asks for it *twice*
    on the first paint of `/advanced`, so an uncached load is two concurrent
    upstream extractions for one answer. That duplicate fetch is the frontend's
    to fix, not this endpoint's; the single flight here means the duplicate costs
    one extraction, not two.

    **The response is a digest unless `?full=true`.** The upstream graph is four
    times the size of what the node palette and editor read — see
    `node_schema_digest` for exactly which fields go and how that was confirmed.
    """
    cached = _object_info_cache.get(provider_id)
    if cached is not None:
        return cached[1] if full else cached[0]

    lock = _object_info_inflight.get(provider_id)
    owner = lock is None
    if owner:
        lock = asyncio.Lock()
        _object_info_inflight[provider_id] = lock
    try:
        await lock.acquire()
        try:
            # Re-check: the caller we queued behind has already stored it.
            cached = _object_info_cache.get(provider_id)
            if cached is not None:
                return cached[1] if full else cached[0]

            service = get_provider_service(session)
            provider = await service.get_provider(provider_id)
            if not provider:
                raise NotFoundError("Provider", provider_id)

            runtime = await resolve_provider_runtime_async(provider)
            if not runtime.worker_url:
                raise ValidationError(
                    "Provider does not have a valid worker URL for extraction"
                )

            try:
                # Increase timeout because CPU extraction spins up ComfyUI
                client = get_http_client()
                response = await client.get(
                    f"{runtime.worker_url}/object-info", timeout=120.0
                )
                response.raise_for_status()
                graph = response.json()
            except httpx.TimeoutException:
                raise ProviderTimeoutError(
                    provider_id,
                    "Timeout while waiting for provider to extract node definitions",
                )
            except Exception as e:
                raise ProviderError(
                    provider_id, f"Failed to fetch object_info from provider: {e}"
                )

            # Only an observed answer is cached. A failure leaves the key absent
            # so the next request retries, which is what the frontend's Retry
            # button is for.
            digest = node_schema_digest(graph)
            _object_info_cache[provider_id] = (digest, graph)
            logger.info(
                "object_info_cached",
                provider_id=provider_id,
                nodes=len(graph) if hasattr(graph, "__len__") else None,
            )
            return graph if full else digest
        finally:
            lock.release()
    finally:
        if owner:
            _object_info_inflight.pop(provider_id, None)