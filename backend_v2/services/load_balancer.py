# Load Balancer - Distributes jobs across multiple providers.
import asyncio
import os
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from cachetools import TTLCache
from sqlmodel import Session, select

from core.entities import LoadBalancerState, Provider, Job, JobStatus
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from infrastructure.providers.runtime import get_provider_worker_base_url, provider_container_name
from infrastructure.repositories import ProviderRepository

logger = get_logger("load_balancer")


def _parse_positive_float(raw_value: str | None, default: float) -> float:
    try:
        parsed = float(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else default


def _parse_positive_int(raw_value: str | None, default: int) -> int:
    try:
        parsed = int(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else default


MODEL_AVAILABILITY_CACHE_TTL_SECONDS = _parse_positive_float(
    os.getenv("COMFY_MODEL_AVAILABILITY_CACHE_TTL_SECONDS"),
    3.0,
)
MODEL_AVAILABILITY_CACHE_MAX_ENTRIES = _parse_positive_int(
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

# Circuit-breaker: after N consecutive failures a provider is skipped until
# its failure streak is reset by a successful job.
_FAILURE_STREAK_THRESHOLD = _parse_positive_int(
    os.getenv("COMFY_FAILURE_STREAK_THRESHOLD"),
    3,
)

# LLM workers are always-running API endpoints (OpenAI-compat, Anthropic, Google,
# Modal direct URLs) — NOT ComfyUI containers, so the HTTP /health + cold-start
# path in the image branch does not apply to them. We still skip providers that
# are in a failure streak before honouring the configured strategy, mirroring the
# failure-aware selection used by the preferred/warm-cold routing paths.
LLM_FAILURE_STREAK_THRESHOLD = _parse_positive_int(
    os.getenv("COMFY_LLM_FAILURE_STREAK_THRESHOLD"),
    3,
)


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
    if state_id not in _runtime_states:
        _runtime_states[state_id] = LoadBalancerRuntimeState()
    return _runtime_states[state_id]

def get_global_runtime_state() -> LoadBalancerRuntimeState:
    return get_runtime_state(1)

class LoadBalancer:
    """Load balances jobs across multiple serverless providers."""

    @classmethod
    def invalidate_model_availability_cache(
        cls,
        provider_id: str | None = None,
        runtime_state: LoadBalancerRuntimeState | None = None,
    ) -> None:
        """Clear cached model-availability lookups after model status changes."""
        cleared_entries = len(_model_availability_cache)
        _model_availability_cache.clear()

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
            for state in _runtime_states.values():
                state.reset()
        _model_availability_cache.clear()
        _provider_health_cache.clear()
    
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
            state = session.exec(select(LoadBalancerState).where(LoadBalancerState.id == state_id)).first()

            # Calculate actual running job counts from database.
            active_states = [JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING]
            running_jobs = session.exec(
                select(Job).where(Job.status.in_(active_states))
            ).all()

            active_job_counts: dict[str, int] = {}
            for job in running_jobs:
                if job.provider_id:
                    active_job_counts[job.provider_id] = active_job_counts.get(job.provider_id, 0) + 1

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
                running_jobs=len(running_jobs),
            )
        except Exception as e:
            state_store.provider_job_counts = {}
            with _load_state_lock:
                state_store.initialized = True
                state_store.initializing = False
            logger.warning("lb_state_load_failed", error=str(e))
    
    @classmethod
    def save_state_to_db(cls, session: Session, runtime_state: LoadBalancerRuntimeState | None = None, state_id: int = 1):
        """Persist state to database (best-effort, never holds locks)."""
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
        """Remove a provider's job counts and failures when the provider is deleted."""
        state_store = runtime_state or get_global_runtime_state()
        
        # If runtime_state is provided explicitly, only clean that one up.
        # Otherwise, clean up all known runtime states.
        stores_to_clean = [(None, runtime_state)] if runtime_state else list(_runtime_states.items())
        
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
                    cls.save_state_to_db(session, runtime_state=store, state_id=state_id)
    
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
    
    async def _check_provider_health(self, provider: Provider) -> bool:
        """Probe the container's status or health endpoint, caching the result for 15 seconds."""
        cache_key = provider.id
        
        # Circuit-breaker: skip providers with a long failure streak.
        if self.runtime_state.provider_failures.get(cache_key, 0) >= _FAILURE_STREAK_THRESHOLD:
            return False
        
        # Check cache
        if cache_key in _provider_health_cache:
            return _provider_health_cache[cache_key]

        is_healthy = False
        
        # 1. First try container_manager container status (if containerized)
        if provider.container_config:
            try:
                from api.deps import get_container_manager
                cm = get_container_manager()
                if cm and cm.client:
                    container_name = provider_container_name(provider.id)
                    try:
                        container = cm.client.containers.get(container_name)
                        if container.status != "running":
                            _provider_health_cache[cache_key] = False
                            return False
                    except Exception:
                        pass
            except Exception:
                pass

        # 2. Probe /health endpoint via HTTP
        try:
            port = 8000
            if provider.container_config and "port" in provider.container_config:
                port = provider.container_config["port"]
            
            # Default target name (inside Docker network / container DNS)
            url = f"{get_provider_worker_base_url(provider.id, port)}/health"
            
            client = get_http_client()
            response = await client.get(url, timeout=2.0)
            if response.status_code == 200:
                is_healthy = True
        except Exception:
            # Try localhost fallback via Docker host port mapping
            try:
                from api.deps import get_container_manager
                cm = get_container_manager()
                if cm and cm.client:
                    container_name = provider_container_name(provider.id)
                    container = cm.client.containers.get(container_name)
                    ports = container.ports
                    tcp_port_info = ports.get(f"{port}/tcp") or ports.get("8000/tcp")
                    if tcp_port_info:
                        host_port = tcp_port_info[0].get("HostPort")
                        if host_port:
                            client = get_http_client()
                            response = await client.get(f"http://localhost:{host_port}/health", timeout=2.0)
                            if response.status_code == 200:
                                is_healthy = True
            except Exception:
                pass

        _provider_health_cache[cache_key] = is_healthy
        return is_healthy

    async def get_next_provider(
        self, 
        preferred_provider_id: str | None = None,
        required_models: dict[str, list[str]] | None = None,
        exclude_provider_ids: set[str] | None = None,
        task_type: str = "image",
    ) -> Provider | None:
        """
        Get the next provider to handle a job.
        
        Args:
            preferred_provider_id: Optional specific provider to use
            required_models: Optional dict of {directory: [filenames]} for model-aware routing
            
        Returns:
            Provider or None if no providers available
        """
        providers = self.repo.get_enabled()
        # Filter by worker_type matching the task_type
        providers = [p for p in providers if p.worker_type == task_type]
        
        excluded = exclude_provider_ids or set()
        if excluded:
            providers = [p for p in providers if p.id not in excluded]
        
        if not providers:
            return None

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
                and self.runtime_state.provider_failures.get(p.id, 0) < LLM_FAILURE_STREAK_THRESHOLD
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
                return None

        # Check health and separate candidates into warm and cold
        warm_candidates = []
        cold_candidates = []
        for p in candidates:
            if await self._check_provider_health(p):
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
            
            # Since the selected provider is cold, trigger container startup and poll/wait
            if selected_provider:
                try:
                    from api.deps import get_container_manager
                    from services.provider_lifecycle_service import (
                        ProviderLifecycleService,
                    )
                    
                    lifecycle_service = ProviderLifecycleService(
                        self.session,
                        container_manager=get_container_manager(),
                        invalidate_caches=self.invalidate_model_availability_cache,
                    )
                    # Trigger startup
                    await lifecycle_service.start_container(selected_provider.id)
                except Exception as start_err:
                    logger.warning("lb_cold_start_trigger_failed", provider_id=selected_provider.id, error=str(start_err))
                
                # Poll health up to 30 seconds
                start_time = time.monotonic()
                poll_success = False
                while time.monotonic() - start_time < 30.0:
                    is_now_healthy = False
                    try:
                        port = 8000
                        if selected_provider.container_config and "port" in selected_provider.container_config:
                            port = selected_provider.container_config["port"]
                        
                        url = f"{get_provider_worker_base_url(selected_provider.id, port)}/health"
                        client = get_http_client()
                        res = await client.get(url, timeout=1.0)
                        if res.status_code == 200:
                            is_now_healthy = True
                    except Exception:
                        try:
                            # Local fallback
                            from api.deps import get_container_manager
                            cm = get_container_manager()
                            if cm and cm.client:
                                container_name = provider_container_name(selected_provider.id)
                                container = cm.client.containers.get(container_name)
                                ports = container.ports
                                tcp_port_info = ports.get(f"{port}/tcp") or ports.get("8000/tcp")
                                if tcp_port_info:
                                    host_port = tcp_port_info[0].get("HostPort")
                                    if host_port:
                                        client = get_http_client()
                                        res = await client.get(f"http://localhost:{host_port}/health", timeout=1.0)
                                        if res.status_code == 200:
                                            is_now_healthy = True
                        except Exception:
                            pass
                    
                    if is_now_healthy:
                        poll_success = True
                        # Cache the success
                        _provider_health_cache[selected_provider.id] = True
                        break
                    
                    await asyncio.sleep(1.0)
                
                logger.info(
                    "lb_cold_start_polled",
                    provider_id=selected_provider.id,
                    success=poll_success,
                    duration=time.monotonic() - start_time,
                )

        if selected_provider:
            await self._track_job(selected_provider.id)
            return selected_provider
        return None

    
    async def _track_job(self, provider_id: str):
        """Track that a job was assigned to a provider."""
        async with self.runtime_state.get_lock():
            if provider_id not in self.runtime_state.provider_job_counts:
                self.runtime_state.provider_job_counts[provider_id] = 0
            self.runtime_state.provider_job_counts[provider_id] += 1
                
            # Persist state periodically (every 20 jobs)
            total_jobs = sum(self.runtime_state.provider_job_counts.values())
            if total_jobs % 20 == 0:
                LoadBalancer.save_state_to_db(self.session, self.runtime_state, state_id=self.state_id)
    
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
                "jobs_assigned": job_counts.get(p.id, 0),
                "failures": failure_counts.get(p.id, 0),
            })
        
        return {
            "strategy": self.strategy,
            "total_providers": len(providers),
            "current_index": current_index,
            "total_jobs_assigned": total_jobs_assigned,
            "provider_stats": provider_stats,
        }
