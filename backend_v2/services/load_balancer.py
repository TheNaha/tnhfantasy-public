# Load Balancer - Distributes jobs across multiple providers.
import asyncio
import os
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from cachetools import TTLCache
from sqlalchemy import func
from sqlmodel import Session, select

from core.entities import (
    ACTIVE_JOB_STATUSES,
    COMFY_CATEGORIES,
    Job,
    LoadBalancerState,
    Provider,
)
from core.config_utils import parse_positive_float, parse_positive_int
from core.provider_capabilities import (
    provider_supports_sampler,
    provider_supports_scheduler,
)
from infrastructure.background_tasks import start_background_task
from infrastructure.logging import get_logger
from infrastructure.repositories.provider_repo import ProviderRepository
logger = get_logger("load_balancer")



MODEL_AVAILABILITY_CACHE_TTL_SECONDS = parse_positive_float(
    os.getenv("COMFY_MODEL_AVAILABILITY_CACHE_TTL_SECONDS"),
    3.0,
)
MODEL_AVAILABILITY_CACHE_MAX_ENTRIES = parse_positive_int(
    os.getenv("COMFY_MODEL_AVAILABILITY_CACHE_MAX_ENTRIES"),
    256,
)

_model_availability_cache = TTLCache(
    maxsize=MODEL_AVAILABILITY_CACHE_MAX_ENTRIES,
    ttl=MODEL_AVAILABILITY_CACHE_TTL_SECONDS
)

_provider_health_cache = TTLCache(
    maxsize=100,
    ttl=15.0
)

# Capability dicts per provider, fetched lazily from the engine's object_info
# and cached with a TTL. Used for sampler/scheduler hard-block checks so a
# provider that cannot run a job's sampler or scheduler is never selected.
# A TTLCache (not a bare dict) so entries age out even when a provider row is
# deleted without going through `engine_factory.invalidate_engine`, and the
# size is bounded by configuration rather than provider churn.
_CAPABILITY_CACHE_TTL_SECONDS = parse_positive_float(
    os.getenv("COMFY_PROVIDER_CAPABILITY_CACHE_TTL_SECONDS"), 60.0
)
_CAPABILITY_CACHE_MAX_ENTRIES = parse_positive_int(
    os.getenv("COMFY_PROVIDER_CAPABILITY_CACHE_MAX_ENTRIES"), 128
)
_capability_cache: TTLCache[str, tuple[float, dict[str, Any] | None]] = TTLCache(
    maxsize=_CAPABILITY_CACHE_MAX_ENTRIES,
    ttl=_CAPABILITY_CACHE_TTL_SECONDS,
)


# Circuit-breaker: after N consecutive failures a provider is skipped until
# its failure streak is reset by a successful job.
_FAILURE_STREAK_THRESHOLD = parse_positive_int(
    os.getenv("COMFY_FAILURE_STREAK_THRESHOLD"),
    3,
)

# LLM workers are always-running API endpoints (OpenAI-compat, Anthropic, Google,
# Modal direct URLs) — NOT ComfyUI containers, so the HTTP /health + cold-start
# path in the image branch does not apply to them. We still skip providers that
# are in a failure streak before honouring the configured strategy, mirroring the
# failure-aware selection used by the preferred/warm-cold routing paths.
LLM_FAILURE_STREAK_THRESHOLD = parse_positive_int(
    os.getenv("COMFY_LLM_FAILURE_STREAK_THRESHOLD"),
    3,
)


def streak_threshold_for(task_type: str) -> int:
    """Circuit-breaker threshold for a task modality.

    LLM providers are always-running API endpoints, so transient blips are
    cheaper to ride out than a cold ComfyUI container start; each modality
    gets its own knob (`COMFY_LLM_FAILURE_STREAK_THRESHOLD` vs
    `COMFY_FAILURE_STREAK_THRESHOLD`). Centralized here so the health probe,
    the LLM fast path, and the stats rollup can never disagree.
    """
    if task_type == "llm":
        return LLM_FAILURE_STREAK_THRESHOLD
    return _FAILURE_STREAK_THRESHOLD

# Bound for the in-process engine health probe in `_check_provider_health`.
# The 15s health cache means this only applies to the first caller to miss.
_ENGINE_HEALTH_PROBE_TIMEOUT_SECONDS = parse_positive_float(
    os.getenv("COMFY_LB_ENGINE_HEALTH_TIMEOUT_SECONDS"),
    5.0,
)


def set_poller_health(
    provider_id: str,
    healthy: bool,
    task_types: Sequence[str] = ("image", "llm", "tts"),
) -> None:
    """Write the telemetry poller's liveness verdict into the health cache.

    The aging poller (`services/provider_telemetry_service`) already probes
    every remote/direct provider on a 30s cadence, so duplicating a real
    round trip at dispatch is wasted work: the poller records each
    online/offline transition here and dispatch reads it through the existing
    15s TTL path (`_check_provider_health`'s first cache hit). An offline
    provider is skipped without any probe, let alone a wake ping.

    Same cache, same keys as the dispatch path:

    * ``healthy=False`` → one entry per task type, so every modality is
      skipped. The bare ``in_process:<id>`` key is deliberately not written
      when offline — per-the-empty-set does not mean "some task is ready".
    * ``healthy=True`` → entries per task type, valid for the TTL. If the
      provider is not in fact ready for a specific modality, the next cache
      miss lands back on the normal engine probe, which answers honestly.

    The TTL is what keeps a stale verdict from setting into a permanent
    position: the poller only writes on transitions, so after 15s dispatch
    returns to its own evidence. There is no reset mechanism and none is
    needed — writes into a TTL máp age out by themselves.
    """
    base = f"in_process:{provider_id}"
    if healthy:
        _provider_health_cache[base] = True
    for task_type in task_types:
        if not task_type:
            continue
        _provider_health_cache[f"{base}:{task_type}"] = bool(healthy)


@dataclass
class LoadBalancerRuntimeState:
    """Shared in-memory runtime state for load balancing decisions."""

    round_robin_index: int = 0
    provider_failures: dict[str, int] = field(default_factory=dict)
    provider_job_counts: dict[str, int] = field(default_factory=dict)
    initialized: bool = False
    initializing: bool = False
    _lock: asyncio.Lock | None = None

    def get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def snapshot(self) -> dict[str, Any]:
        return {
            "round_robin_index": self.round_robin_index,
            "provider_failures": dict(self.provider_failures),
            "provider_job_counts": dict(self.provider_job_counts),
            "initialized": self.initialized,
        }

    def reset(self) -> None:
        self.round_robin_index = 0
        self.provider_failures = {}
        self.provider_job_counts = {}
        self.initialized = False
        self.initializing = False


_runtime_states: dict[int, LoadBalancerRuntimeState] = {}
_load_state_lock = threading.Lock()

def get_runtime_state(state_id: int = 1) -> LoadBalancerRuntimeState:
    # The membership test and the insert have to be one critical section. Split
    # across an unlocked window, two callers can both miss and both assign — the
    # loser silently replaces the winner's state, so whichever store the caller
    # then mutates is not the one the other one is mutating.
    with _load_state_lock:
        if state_id not in _runtime_states:
            _runtime_states[state_id] = LoadBalancerRuntimeState()
        return _runtime_states[state_id]

def get_global_runtime_state() -> LoadBalancerRuntimeState:
    return get_runtime_state(1)


# Which runtime state keeps each modality's counters.
#
# Each modality needs its own `provider_failures`, `provider_job_counts` and
# `round_robin_index`. TTS shared the image state, which was wrong: a single
# provider can serve both (the same ComfyUI box serves `image` and `tts`), so
# a TTS outage incremented the failure count on a provider that was perfectly
# healthy for images, and the image path's circuit breaker then took it out of
# image rotation. The failure counts crossed modalities, and `get_stats`
# reported the shared counters as if they were a per-modality breakdown.
#
# This mapping is the single place that knows it; `load_balancer_factory`
# builds the per-modality balancers from it.
MODALITY_STATE_IDS: dict[str, int] = {
    "image": 1,
    "llm": 2,
    "tts": 3,
}

class LoadBalancer:
    """Load balances jobs across multiple serverless providers."""

    @classmethod
    def invalidate_model_availability_cache(
        cls,
        provider_id: str | None = None,
        runtime_state: LoadBalancerRuntimeState | None = None,
    ) -> None:
        """Clear cached model-availability lookups after model status changes.

        Clears *both* availability caches through this one entry point. The
        `ModelAvailabilityService` cache had no production caller at all —
        its own docstring named the model-install and provider-toggle paths
        that would call it and none did — so a just-deleted model stayed
        servable, and a just-installed one invisible, for the 30 s TTL. Every
        writer now comes through here.
        """
        from services.model_availability_service import clear_available_models_cache

        cleared_entries = len(_model_availability_cache)
        _model_availability_cache.clear()
        clear_available_models_cache()

        if cleared_entries:
            logger.debug(
                "lb_model_availability_cache_invalidated",
                provider_id=provider_id,
                cleared_entries=cleared_entries,
            )

    @classmethod
    def _get_state_snapshot(cls, runtime_state: LoadBalancerRuntimeState | None = None) -> dict[str, Any]:
        """Return a copy of current in-memory balancer state."""
        snapshot = (runtime_state or get_global_runtime_state()).snapshot()
        snapshot.pop("model_availability_cache", None)
        snapshot.pop("initialized", None)
        return snapshot

    @staticmethod
    def _build_model_availability_cache_key(required_models: dict[str, list[str]]) -> Any:
        """Create stable hashable key for required-model lookup payload."""
        return tuple(
            (directory, tuple(sorted(set(filenames))))
            for directory, filenames in sorted(required_models.items())
            if filenames
        )

    def _get_cached_eligible_provider_ids(self, required_models: dict[str, list[str]]) -> list[str] | None:
        cache_key = self._build_model_availability_cache_key(required_models)
        return list(_model_availability_cache[cache_key]) if cache_key in _model_availability_cache else None

    def _set_cached_eligible_provider_ids(self, required_models: dict[str, list[str]], eligible_provider_ids: list[str]) -> None:
        cache_key = self._build_model_availability_cache_key(required_models)
        _model_availability_cache[cache_key] = tuple(eligible_provider_ids)

    @classmethod
    def reset_state(cls, runtime_state: LoadBalancerRuntimeState | None = None):
        """Reset in-memory state. Intended for tests and controlled startup flows."""
        if runtime_state:
            runtime_state.reset()
        else:
            # Iterating `_runtime_states.values()` while another thread inserts
            # into it raises `RuntimeError: dictionary changed size during
            # iteration` — the same window as `get_runtime_state`, and reachable
            # from the same place.
            with _load_state_lock:
                states = list(_runtime_states.values())
            for state in states:
                state.reset()
        _model_availability_cache.clear()
        _provider_health_cache.clear()
        _capability_cache.clear()
    
    @classmethod
    def load_state_from_db(
        cls,
        session: Session,
        runtime_state: LoadBalancerRuntimeState | None = None,
        *,
        force: bool = False,
        state_id: int = 1,
    ):
        """Load persisted state from database on startup."""
        state_store = runtime_state or get_global_runtime_state()

        if not force:
            with _load_state_lock:
                if state_store.initialized or state_store.initializing:
                    return
                state_store.initializing = True

        try:
            state = session.exec(
                select(LoadBalancerState)
                .where(LoadBalancerState.id == state_id)
                .limit(1)
            ).first()

            # Calculate actual running job counts from database.
            #
            # Counted in SQL, not by loading rows. This used to
            # `select(Job).where(active).limit(1000)` and iterate in Python,
            # which materialised the `workflow` and `metadata_` jsonb of up to a
            # thousand whole Job rows to read one string field off each — and past
            # a thousand active jobs the counts were silently wrong, with nothing
            # anywhere saying the number was a floor rather than a total.
            # The shared tuple. This copy omitted `RETRYING`, so a job in retry
            # backoff counted as zero in-flight on its provider and
            # `least-connections` could hand that provider a second job while the
            # first was still occupying it.
            active_states = ACTIVE_JOB_STATUSES
            counted = session.exec(
                select(Job.provider_id, func.count(Job.id))
                .where(Job.status.in_(active_states), Job.provider_id.is_not(None))
                .group_by(Job.provider_id)
            ).all()

            active_job_counts: dict[str, int] = {
                provider_id: int(count) for provider_id, count in counted if provider_id
            }

            state_store.round_robin_index = (state.round_robin_index or 0) if state else 0
            state_store.provider_failures = dict(state.provider_failures or {}) if state else {}
            # DON'T load persisted job counts - they represent historical totals.
            # On startup, reset to the actual currently running jobs only.
            state_store.provider_job_counts = active_job_counts
            with _load_state_lock:
                state_store.initialized = True
                state_store.initializing = False

            logger.info(
                "lb_state_loaded",
                index=state.round_robin_index if state else 0,
                active_jobs=active_job_counts,
                running_jobs=sum(active_job_counts.values()),
            )
        except Exception as e:
            state_store.provider_job_counts = {}
            with _load_state_lock:
                state_store.initialized = True
                state_store.initializing = False
            logger.warning("lb_state_load_failed", error=str(e))
    
    @classmethod
    def save_state_to_db(
        cls,
        session: Session,
        runtime_state: LoadBalancerRuntimeState | None = None,
        state_id: int = 1,
        snapshot: dict[str, Any] | None = None,
    ):
        """Persist state to database (best-effort, never holds locks).

        `snapshot` lets a caller capture the counters while it still holds the
        asyncio lock and then persist them later (or off-thread) without
        re-reading live state.
        """
        if snapshot is None:
            snapshot = cls._get_state_snapshot(runtime_state)
        try:
            state = session.exec(select(LoadBalancerState).where(LoadBalancerState.id == state_id)).first()
            if not state:
                state = LoadBalancerState(id=state_id)
                session.add(state)

            state.round_robin_index = snapshot["round_robin_index"]
            state.provider_failures = snapshot["provider_failures"]
            state.provider_job_counts = snapshot["provider_job_counts"]
            state.updated_at = datetime.now(timezone.utc)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("lb_state_save_failed", error=str(e))
    
    @classmethod
    async def remove_provider_state(cls, session: Session, provider_id: str, runtime_state: LoadBalancerRuntimeState | None = None):
        """Remove a provider's job counts and failures when the provider is deleted.

        The state mutation happens under the asyncio lock; the DB write happens
        after it is released. `save_state_to_db` is a synchronous SELECT +
        `session.commit()`, and its own docstring says it never holds locks —
        the caller used to violate that, so every concurrent `get_next_provider`
        awaiting the lock stalled for the length of a blocking commit. Same bug
        `_track_job` had.
        """
        # If runtime_state is provided explicitly, only clean that one up.
        # Otherwise, clean up all known runtime states.
        #
        # The `list()` snapshot is taken under the module lock: iterating
        # `_runtime_states` while `get_runtime_state` inserts into it raises
        # `RuntimeError: dictionary changed size during iteration`. The lock is
        # released immediately — the per-store asyncio lock below is what guards
        # the mutation, and holding a threading lock across an `async with` would
        # block the whole event loop for its duration.
        if runtime_state:
            stores_to_clean = [(None, runtime_state)]
        else:
            with _load_state_lock:
                stores_to_clean = list(_runtime_states.items())

        pending_persist: list[tuple[LoadBalancerRuntimeState, int, dict[str, Any]]] = []

        for state_id, store in stores_to_clean:
            async with store.get_lock():
                persist_needed = False
                if provider_id in store.provider_job_counts:
                    store.provider_job_counts.pop(provider_id, None)
                    persist_needed = True
                if provider_id in store.provider_failures:
                    store.provider_failures.pop(provider_id, None)
                    persist_needed = True
                if persist_needed and state_id is not None:
                    pending_persist.append((store, state_id, cls._get_state_snapshot(store)))

        # Lock released: blocking commit off the critical section.
        for store, state_id, snapshot in pending_persist:
            cls.save_state_to_db(session, runtime_state=store, state_id=state_id, snapshot=snapshot)
    
    def __init__(self, session: Session, strategy: str = "round-robin", runtime_state: LoadBalancerRuntimeState | None = None, state_id: int = 1):
        """
        Initialize load balancer.
        
        Args:
            session: Database session
            strategy: Load balancing strategy (round-robin, random, priority)
            runtime_state: Optional runtime state container for tests or isolated coordinators
            state_id: Which persistent state record to use in the database.
        """
        self.session = session
        self.repo = ProviderRepository(session)
        self.strategy = strategy
        self.state_id = state_id
        self.runtime_state = runtime_state or get_global_runtime_state()

        # Health checks are opt-out via env flag (tests set COMFY_LB_HEALTH_CHECKS_ENABLED=0).
        self.health_check_enabled = os.environ.get("COMFY_LB_HEALTH_CHECKS_ENABLED", "1") != "0"

        # Load shared state once per process/runtime container.
        LoadBalancer.load_state_from_db(session, self.runtime_state, state_id=self.state_id)
    
    async def _check_provider_health(self, provider: Provider, task_type: str = "image") -> bool:
        """Probe the provider's in-process engine health, caching the result for 15 seconds."""
        cache_key = f"in_process:{provider.id}:{task_type}" if task_type else f"in_process:{provider.id}"

        # Circuit-breaker: skip providers with a long failure streak. The
        # threshold is per-modality — an LLM endpoint mid-blip must not be
        # judged by the image cold-start budget, and vice versa.
        if self.runtime_state.provider_failures.get(provider.id, 0) >= streak_threshold_for(task_type):
            return False

        # In-process compute engine health probe
        from services.engines.engine_factory import can_create_engine, get_engine
        if not can_create_engine(provider):
            return False
        if cache_key in _provider_health_cache:
            return _provider_health_cache[cache_key]
        try:
            engine = get_engine(provider.id, provider)
            if engine is None:
                return False
            res = await asyncio.wait_for(engine.check_health(), timeout=_ENGINE_HEALTH_PROBE_TIMEOUT_SECONDS)
            ready_for = res.get("ready_for")
            if isinstance(ready_for, list) and task_type:
                is_healthy = task_type in ready_for
            else:
                is_healthy = bool(res.get("ready") or res.get("status") in ("healthy", "ok"))
        except Exception as exc:
            logger.warning("in_process_health_failed", provider_id=provider.id, error=str(exc))
            is_healthy = False
            ready_for = None

        _provider_health_cache[cache_key] = is_healthy
        if isinstance(ready_for, list):
            for m in ("image", "llm", "tts"):
                _provider_health_cache[f"in_process:{provider.id}:{m}"] = m in ready_for
        return is_healthy

    async def _get_provider_capabilities(
        self, provider: Provider
    ) -> dict[str, Any] | None:
        """Fetch and cache a provider's capability dict from its object_info graph.

        Calls the engine's `get_object_info()` and runs `derive_capabilities()`
        on the result. Cached with a TTL so repeated dispatches don't re-fetch.

        Returns None when the provider's capabilities cannot be determined
        (engine doesn't implement `get_object_info`, or the fetch failed).
        Callers treat None as "unknown" — the provider is not blocked on that
        basis.
        """
        import time

        now = time.monotonic()
        cached = _capability_cache.get(provider.id)
        if cached and (now - cached[0]) < _CAPABILITY_CACHE_TTL_SECONDS:
            return cached[1]

        try:
            from services.engines.engine_factory import get_engine

            engine = get_engine(provider.id, provider)
            if engine is None:
                _capability_cache[provider.id] = (now, None)
                return None

            get_object_info = getattr(engine, "get_object_info", None)
            if get_object_info is None:
                _capability_cache[provider.id] = (now, None)
                return None

            graph = await get_object_info()
        except Exception:
            _capability_cache[provider.id] = (now, None)
            return None

        if not isinstance(graph, dict) or not graph:
            _capability_cache[provider.id] = (now, None)
            return None

        try:
            from core.provider_capabilities import derive_capabilities

            caps = derive_capabilities(graph, provider.id)
        except Exception:
            _capability_cache[provider.id] = (now, None)
            return None

        _capability_cache[provider.id] = (now, caps)
        return caps

    async def get_next_provider(
        self, 
        preferred_provider_id: str | None = None,
        required_models: dict[str, list[str]] | None = None,
        sampler_name: str | None = None,
        scheduler_name: str | None = None,
        exclude_provider_ids: set[str] | None = None,
        task_type: str = "image",
    ) -> Provider | None:
        """
        Get the next provider to handle a job.
        
        Args:
            preferred_provider_id: Optional specific provider to use
            required_models: Optional dict of {directory: [filenames]} for model-aware routing
            sampler_name: Optional sampler name the job requires; providers that
                          don't advertise it are excluded (hard block).
            scheduler_name: Optional scheduler name the job requires; providers
                          that don't advertise it are excluded (hard block).
            
        Returns:
            Provider or None if no providers available
        """
        providers = self.repo.get_enabled()
        # Filter by capability, not by `worker_type` equality.
        #
        # This was `p.worker_type == task_type`, which works only because
        # `worker_type` is a single value and every task type happened to be
        # served by exactly one kind of worker. TTS breaks that: the same ComfyUI
        # container serves `image` and `tts`, and the difference is the workflow
        # graph rather than the machine, so a provider has to be able to say
        # both. `Provider.serves()` resolves the empty-capabilities case back to
        # `worker_type`, so every provider that has not been edited behaves
        # exactly as it did before this column existed.
        providers = [p for p in providers if p.serves(task_type)]

        excluded = exclude_provider_ids or set()
        if excluded:
            providers = [p for p in providers if p.id not in excluded]

        if not providers:
            return None

        # A ComfyUI-engine task type (`image`, `tts`) that nobody can serve.
        # Returning None here is indistinguishable from "no provider is healthy",
        # so the failure is reported as an empty pool by the caller. Log the
        # capability sets so the cause is visible in the log rather than
        # inferred — this is the failure the whole column exists to prevent,
        # since before it a `tts` job was simply handed to an image worker that
        # has no TTS nodes and failed inside the graph.
        if task_type in COMFY_CATEGORIES:
            capable = [
                p.id
                for p in self.repo.get_enabled()
                if p.serves(task_type)
            ]
            if not capable:
                logger.warning(
                    "no_provider_declares_capability",
                    task_type=task_type,
                    providers=[
                        {"id": p.id, "worker_type": p.worker_type, "capabilities": p.capabilities}
                        for p in self.repo.get_enabled()
                    ],
                    hint=(
                        f"set providers.capabilities to include {task_type!r} on a provider "
                        "whose worker image actually has the node pack installed"
                    ),
                )

        # LLM failover routing: API-endpoint providers are always-running
        # endpoints (not ComfyUI containers), so the container cold-start/health
        # machinery below does not apply. We still skip providers in a failure
        # streak and honour the configured strategy instead of blindly returning
        # the first-priority provider (issue #3). Failover between providers is
        # handled by job_runner with a stagger delay between attempts.
        if task_type == "llm":
            eligible = [
                p for p in providers
                if p.id not in excluded
                and self.runtime_state.provider_failures.get(p.id, 0) < streak_threshold_for(task_type)
            ]
            if not eligible:
                # Every non-excluded provider is in a failure streak — fall back
                # to all of them so failover still progresses (stagger-retry in
                # job_runner will report failure again if truly dead).
                eligible = [p for p in providers if p.id not in excluded]
            if not eligible:
                return None

            # Honour an explicit user/provider override even if currently failing.
            if preferred_provider_id:
                preferred = next((p for p in eligible if p.id == preferred_provider_id), None)
                if preferred:
                    selected_provider = preferred
                else:
                    selected_provider = await self._select_by_strategy(eligible)
            else:
                selected_provider = await self._select_by_strategy(eligible)

            await self._track_job(selected_provider.id)
            return selected_provider
        
        # Filter by model availability if required
        if required_models:
            eligible_ids = self._get_cached_eligible_provider_ids(required_models)
            if eligible_ids is None:
                from .model_availability_service import ModelAvailabilityService
                availability_service = ModelAvailabilityService(self.session)
                eligible_ids = availability_service.get_providers_with_models(required_models)
                self._set_cached_eligible_provider_ids(required_models, eligible_ids)
            
            if not eligible_ids:
                # No provider has all required models
                return None
            
            # Filter to only eligible providers
            providers = [p for p in providers if p.id in eligible_ids]
            
            if not providers:
                return None
        
        # Filter by sampler/scheduler capability (hard block).
        # A provider that does not advertise the job's sampler or scheduler
        # cannot run it — never select it, fail over instead.
        if sampler_name or scheduler_name:
            capped_providers = []
            for p in providers:
                caps = await self._get_provider_capabilities(p)
                if sampler_name is not None:
                    supported = provider_supports_sampler(caps, sampler_name)
                    if supported is False:
                        logger.debug(
                            "lb_sampler_unsupported",
                            provider_id=p.id,
                            sampler=sampler_name,
                        )
                        continue
                if scheduler_name is not None:
                    supported = provider_supports_scheduler(caps, scheduler_name)
                    if supported is False:
                        logger.debug(
                            "lb_scheduler_unsupported",
                            provider_id=p.id,
                            scheduler=scheduler_name,
                        )
                        continue
                capped_providers.append(p)
            providers = capped_providers
            if not providers:
                return None
        
        # Non-health-aware routing
        if not getattr(self, "health_check_enabled", True):
            # If specific provider requested, try to use it
            if preferred_provider_id:
                provider = self.repo.get(preferred_provider_id)
                if provider and provider.enabled and provider.id not in excluded:
                    # Check if preferred provider is in eligible list (if filtering)
                    if required_models and provider.id not in [p.id for p in providers]:
                        # Preferred provider doesn't have required models
                        return None
                    await self._track_job(provider.id)
                    return provider
            
            # Apply load balancing strategy
            provider = await self._select_by_strategy(providers)
            
            # Track job assigned to this provider
            await self._track_job(provider.id)
            return provider

        # Health-aware routing
        candidates = providers
        if preferred_provider_id:
            provider = self.repo.get(preferred_provider_id)
            if provider and provider.enabled and provider.id not in excluded:
                if required_models and provider.id not in [p.id for p in providers]:
                    return None
                candidates = [provider]
            else:
                # The pinned provider is disabled, unknown, or already
                # exhausted by an earlier attempt on this job. Returning
                # None here makes `job_runner.select_next_provider` read
                # "all providers failed" and fail the job outright — which
                # is exactly the failover the exhausted-set exists to
                # provide, and which the non-health-aware branch below and
                # the LLM branch above both perform. Fall through to the
                # strategy over what is left instead; `providers` has
                # already dropped disabled and capability-ineligible rows.
                candidates = [p for p in providers if p.id != preferred_provider_id]
                if not candidates:
                    return None

        # Check health and separate candidates into warm and cold
        warm_candidates = []
        cold_candidates = []
        for p in candidates:
            if await self._check_provider_health(p, task_type):
                warm_candidates.append(p)
            else:
                cold_candidates.append(p)

        selected_provider = None
        if warm_candidates:
            # Route only among warm candidates using the strategy
            if len(warm_candidates) == 1:
                selected_provider = warm_candidates[0]
            else:
                selected_provider = await self._select_by_strategy(warm_candidates)
        elif cold_candidates:
            # Route among cold candidates using the strategy
            if len(cold_candidates) == 1:
                selected_provider = cold_candidates[0]
            else:
                selected_provider = await self._select_by_strategy(cold_candidates)
            
            # Since the selected provider is cold, trigger container startup in the
            # background and return immediately. Job selection never blocks here:
            # dispatch failures during the boot window fall through retry backoff,
            # and the warm-up task fills the health cache when ready.
            if selected_provider and os.getenv("COMFY_PROVIDER_AUTOSTART_ENABLED", "0") == "1":
                start_background_task(
                    self._warm_provider_in_background(selected_provider),
                    task_name=f"lb_warm:{selected_provider.id}",
                    timeout=None,
                )

        if selected_provider:
            await self._track_job(selected_provider.id)
            return selected_provider
        return None

    async def _warm_provider_in_background(self, provider: Provider) -> None:
        """Fire-and-forget engine health fill for a cold provider.

        Engines need no startup — this just pre-populates the health cache so
        the next routing decision does not pay for the first probe.
        """
        from services.engines.engine_factory import can_create_engine, get_engine
        if not can_create_engine(provider):
            return
        engine = get_engine(provider.id, provider)
        if engine is None:
            return
        try:
            res = await engine.check_health()
            ready_for = res.get("ready_for")
            is_ready = bool(res.get("ready") or res.get("status") in ("healthy", "ok"))
            _provider_health_cache[f"in_process:{provider.id}"] = is_ready
            if isinstance(ready_for, list):
                for m in ("image", "llm", "tts"):
                    _provider_health_cache[f"in_process:{provider.id}:{m}"] = m in ready_for
            else:
                for m in ("image", "llm", "tts"):
                    _provider_health_cache[f"in_process:{provider.id}:{m}"] = is_ready
        except Exception as e:
            logger.warning("lb_in_process_warm_failed", provider_id=provider.id, error=str(e))

    
    async def _track_job(self, provider_id: str):
        """Track that a job was assigned to a provider."""
        # Snapshot the work to do *inside* the lock, then do it outside. The
        # comment here used to claim the persist happened outside the lock while
        # the `await` sat inside the `async with` — so every twentieth job blocked
        # _round_robin, _select_provider, record_success and report_failure for the
        # duration of a thread hop plus a DB commit.
        #
        # The worker thread gets its OWN session via get_session_sync() because a
        # SQLAlchemy Session is not thread-safe and self.session is shared with the
        # event loop.
        async with self.runtime_state.get_lock():
            if provider_id not in self.runtime_state.provider_job_counts:
                self.runtime_state.provider_job_counts[provider_id] = 0
            self.runtime_state.provider_job_counts[provider_id] += 1

            total_jobs = sum(self.runtime_state.provider_job_counts.values())
            due_for_persist = total_jobs % 20 == 0
            if due_for_persist:
                snapshot = self.runtime_state.snapshot()
                state_id = self.state_id

        if due_for_persist:
            await asyncio.to_thread(LoadBalancer._persist_snapshot, snapshot, state_id)

    @staticmethod
    def _persist_snapshot(snapshot: dict[str, Any], state_id: int) -> None:
        """Worker-thread body for the periodic state write."""
        from infrastructure.database import get_session_sync

        session = get_session_sync()
        try:
            LoadBalancer.save_state_to_db(session, state_id=state_id, snapshot=snapshot)
        except Exception as exc:  # pragma: no cover - save_state_to_db already swallows
            logger.warning("lb_state_persist_failed", error=str(exc))
        finally:
            session.close()
    
    async def _round_robin(self, providers: list[Provider]) -> Provider:
        """Round-robin selection."""
        async with self.runtime_state.get_lock():
            provider = providers[self.runtime_state.round_robin_index % len(providers)]
            self.runtime_state.round_robin_index += 1
            index = self.runtime_state.round_robin_index
        logger.debug("lb_round_robin_selected", provider_id=provider.id, index=index)
        return provider
    
    async def _random(self, providers: list[Provider]) -> Provider:
        """Random selection."""
        return random.choice(providers)
    
    async def _priority(self, providers: list[Provider]) -> Provider:
        """
        Priority-based selection.
        Lower priority number = higher priority.
        Uses provider ID as tiebreaker for deterministic ordering.
        """
        sorted_providers = sorted(providers, key=lambda p: (p.priority, p.id))
        return sorted_providers[0]
    
    async def _least_connections(self, providers: list[Provider]) -> Provider:
        """
        Least-connections selection.
        Selects the provider with fewest active jobs.
        When tied, uses round-robin among tied providers for fair distribution.
        """
        # Get job counts
        async with self.runtime_state.get_lock():
            counts = {p.id: self.runtime_state.provider_job_counts.get(p.id, 0) for p in providers}
            min_count = min(counts.values())
        
        # Find all providers with minimum count (tied)
        tied_providers = [p for p in providers if counts[p.id] == min_count]
        
        if len(tied_providers) == 1:
            selected = tied_providers[0]
        else:
            # Use round-robin among tied providers for fair distribution
            async with self.runtime_state.get_lock():
                selected = tied_providers[self.runtime_state.round_robin_index % len(tied_providers)]
                self.runtime_state.round_robin_index += 1

        logger.debug("lb_least_conn_selected", provider_id=selected.id, active_jobs=counts[selected.id], tied=len(tied_providers))
        return selected
    
    def _get_best_priority_tier(self, providers: list[Provider]) -> list[Provider]:
        """Get providers in the highest priority tier (lowest priority number)."""
        if not providers:
            return []
        best_priority = min(p.priority for p in providers)
        return [p for p in providers if p.priority == best_priority]
    
    async def _priority_round_robin(self, providers: list[Provider]) -> Provider:
        """
        Priority + Round-Robin: Among providers with the best priority,
        use round-robin selection.
        """
        best_tier = self._get_best_priority_tier(providers)
        if len(best_tier) == 1:
            return best_tier[0]
        
        # Round-robin within the best priority tier
        async with self.runtime_state.get_lock():
            provider = best_tier[self.runtime_state.round_robin_index % len(best_tier)]
            self.runtime_state.round_robin_index += 1
        logger.debug("lb_priority_rr_selected", provider_id=provider.id, priority=provider.priority, tier_size=len(best_tier))
        return provider
    
    async def _priority_least_connections(self, providers: list[Provider]) -> Provider:
        """
        Priority + Least-Connections: Among providers with the best priority,
        select the one with fewest active jobs. Uses round-robin for ties.
        """
        best_tier = self._get_best_priority_tier(providers)
        if len(best_tier) == 1:
            return best_tier[0]
        
        # Get job counts for best tier
        async with self.runtime_state.get_lock():
            counts = {p.id: self.runtime_state.provider_job_counts.get(p.id, 0) for p in best_tier}
            min_count = min(counts.values())
        
        # Find all providers with minimum count (tied)
        tied_providers = [p for p in best_tier if counts[p.id] == min_count]
        
        if len(tied_providers) == 1:
            selected = tied_providers[0]
        else:
            # Use round-robin among tied providers
            async with self.runtime_state.get_lock():
                selected = tied_providers[self.runtime_state.round_robin_index % len(tied_providers)]
                self.runtime_state.round_robin_index += 1

        logger.debug("lb_priority_lc_selected", provider_id=selected.id, priority=selected.priority, active_jobs=counts[selected.id], tied=len(tied_providers))
        return selected
    
    async def _select_by_strategy(self, providers: list[Provider]) -> Provider:
        """Dispatch to the configured load-balancing strategy."""
        if self.strategy == "round-robin":
            return await self._round_robin(providers)
        elif self.strategy == "random":
            return await self._random(providers)
        elif self.strategy == "priority":
            return await self._priority(providers)
        elif self.strategy == "least-connections":
            return await self._least_connections(providers)
        elif self.strategy == "priority-round-robin":
            return await self._priority_round_robin(providers)
        elif self.strategy == "priority-least-connections":
            return await self._priority_least_connections(providers)
        else:
            logger.warning("lb_unknown_strategy", strategy=self.strategy, fallback="round-robin")
            return await self._round_robin(providers)
    
    async def report_success(self, provider_id: str):
        """Report successful job completion for a provider."""
        async with self.runtime_state.get_lock():
            if provider_id in self.runtime_state.provider_failures:
                self.runtime_state.provider_failures[provider_id] = 0
    
    async def report_failure(self, provider_id: str):
        """Report job failure for a provider."""
        async with self.runtime_state.get_lock():
            if provider_id not in self.runtime_state.provider_failures:
                self.runtime_state.provider_failures[provider_id] = 0
                
            self.runtime_state.provider_failures[provider_id] += 1
            failures = self.runtime_state.provider_failures[provider_id]
        logger.warning("lb_provider_failure", provider_id=provider_id, total_failures=failures)
    
    async def release_job(self, provider_id: str):
        """
        Release a job slot for a provider when job completes.
        This decrements the active job count for least-connections tracking.
        Should be called after every job completion (success or failure).
        """
        async with self.runtime_state.get_lock():
            if provider_id in self.runtime_state.provider_job_counts:
                self.runtime_state.provider_job_counts[provider_id] = max(
                    0, self.runtime_state.provider_job_counts[provider_id] - 1
                )

        logger.debug("lb_job_released", provider_id=provider_id)
    
    async def get_stats(self) -> dict[str, Any]:
        """Get load balancer statistics including per-provider job counts."""
        providers = self.repo.get_enabled()
        async with self.runtime_state.get_lock():
            current_index = self.runtime_state.round_robin_index
            total_jobs_assigned = sum(self.runtime_state.provider_job_counts.values())
            failure_counts = dict(self.runtime_state.provider_failures)
            job_counts = dict(self.runtime_state.provider_job_counts)
        
        # Build detailed per-provider stats
        provider_stats = []
        for p in providers:
            provider_stats.append({
                "id": p.id,
                "enabled": p.enabled,
                "priority": p.priority,
                "worker_type": p.worker_type,
                "capabilities": list(p.capabilities) if p.capabilities else ([p.worker_type] if p.worker_type else []),
                "jobs_assigned": job_counts.get(p.id, 0),
                "failures": failure_counts.get(p.id, 0),
            })
        
        # Build per-modality routing stats.
        #
        # Each modality's counters come from ITS OWN runtime state. Reading
        # them out of `self.runtime_state` — which is one modality's state —
        # is what made this breakdown a copy of the same numbers three times,
        # and it is why the modality split had to be made before the numbers
        # could mean anything.
        by_modality: dict[str, dict[str, Any]] = {}
        for mod in ("image", "llm", "tts"):
            mod_providers = [p for p in providers if p.serves(mod)]
            threshold = streak_threshold_for(mod)
            state = get_runtime_state(MODALITY_STATE_IDS.get(mod, 1))
            async with state.get_lock():
                mod_job_counts = dict(state.provider_job_counts)
                mod_failure_counts = dict(state.provider_failures)
            by_modality[mod] = {
                "total_providers": len(mod_providers),
                "active_jobs": sum(mod_job_counts.get(p.id, 0) for p in mod_providers),
                "failing_providers": sum(1 for p in mod_providers if mod_failure_counts.get(p.id, 0) >= threshold),
                "provider_ids": [p.id for p in mod_providers],
            }

        return {
            "strategy": self.strategy,
            "total_providers": len(providers),
            "current_index": current_index,
            "total_jobs_assigned": total_jobs_assigned,
            "provider_stats": provider_stats,
            "by_modality": by_modality,
        }
