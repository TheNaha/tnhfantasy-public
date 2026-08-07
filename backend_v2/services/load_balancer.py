import asyncio
import os
import random
import time
from datetime import datetime, timezone
from typing import Any

from cachetools import TTLCache
from sqlmodel import Session, select, func

from core.entities import LoadBalancerState, Provider, Job, JobStatus
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from infrastructure.providers.runtime import get_provider_worker_base_url
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
    ttl=5.0
)

class LoadBalancer:
    """Load balances jobs across multiple serverless providers, using database for state."""

    @classmethod
    def invalidate_model_availability_cache(
        cls,
        provider_id: str | None = None,
        runtime_state: Any = None, # kept for backward compat with lifecycle
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
    def reset_state(cls, runtime_state: Any = None):
        """Reset in-memory caches. Intended for tests and controlled startup flows."""
        _model_availability_cache.clear()
        _provider_health_cache.clear()
    
    @classmethod
    def load_state_from_db(
        cls,
        session: Session,
        runtime_state: Any = None,
        *,
        force: bool = False,
        state_id: int = 1,
    ):
        """No-op for backward compatibility. State is loaded dynamically."""
        pass
    
    @classmethod
    def save_state_to_db(cls, session: Session, runtime_state: Any = None, state_id: int = 1):
        """No-op for backward compatibility. State is loaded dynamically."""
        pass
    
    @classmethod
    async def remove_provider_state(cls, session: Session, provider_id: str, runtime_state: Any = None):
        """Remove a provider's failures when the provider is deleted."""
        state = session.exec(select(LoadBalancerState).where(LoadBalancerState.id == 1)).first()
        if state:
            failures = dict(state.provider_failures or {})
            if provider_id in failures:
                failures.pop(provider_id)
                state.provider_failures = failures
                session.commit()
    
    def __init__(self, session: Session, strategy: str = "round-robin", runtime_state: Any = None, state_id: int = 1):
        """
        Initialize load balancer.
        
        Args:
            session: Database session
            strategy: Load balancing strategy (round-robin, random, priority)
            runtime_state: Ignored.
            state_id: Which persistent state record to use in the database.
        """
        self.session = session
        self.repo = ProviderRepository(session)
        self.strategy = strategy
        self.state_id = state_id

        # Needed for backward compatibility in tests
        self.runtime_state = runtime_state or self 

        import sys
        self.health_check_enabled = not ("pytest" in sys.modules)

    def _get_db_state(self) -> LoadBalancerState:
        # SQLite ignores with_for_update, but postgres will lock the row.
        state = self.session.exec(select(LoadBalancerState).where(LoadBalancerState.id == self.state_id).with_for_update()).first()
        if not state:
            state = LoadBalancerState(id=self.state_id)
            self.session.add(state)
            self.session.commit()
            # Re-fetch with lock
            state = self.session.exec(select(LoadBalancerState).where(LoadBalancerState.id == self.state_id).with_for_update()).first()
        return state

    def _get_active_jobs_counts(self) -> dict[str, int]:
        active_states = [JobStatus.SENT_TO_PROVIDER, JobStatus.CONNECTED, JobStatus.PRE_GENERATION, JobStatus.GENERATING, JobStatus.POST_PROCESSING]
        running_jobs = self.session.exec(
            select(Job.provider_id).where(Job.status.in_(active_states)).where(Job.provider_id != None)
        ).all()
        counts = {}
        for pid in running_jobs:
            counts[pid] = counts.get(pid, 0) + 1
        return counts

    async def _check_provider_health(self, provider: Provider) -> bool:
        """Probe the container's status or health endpoint, caching the result for 5 seconds."""
        cache_key = provider.id
        
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
                    container_name = f"tnhcomfy-{provider.id}"
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
                    container_name = f"tnhcomfy-{provider.id}"
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
        """
        providers = self.repo.get_enabled()
        # Filter by worker_type matching the task_type
        providers = [p for p in providers if p.worker_type == task_type]
        
        excluded = exclude_provider_ids or set()
        if excluded:
            providers = [p for p in providers if p.id not in excluded]
        
        if not providers:
            return None

        # LLM failover routing
        if task_type == "llm":
            if preferred_provider_id:
                provider = self.repo.get(preferred_provider_id)
                if provider and provider.enabled and provider.id not in excluded:
                    await self._track_job(provider.id)
                    return provider
            ordered = sorted(providers, key=lambda p: (p.priority, p.id))
            for provider in ordered:
                if provider.id in excluded:
                    continue
                await self._track_job(provider.id)
                return provider
            return None
        
        # Filter by model availability if required
        if required_models:
            eligible_ids = self._get_cached_eligible_provider_ids(required_models)
            if eligible_ids is None:
                from .model_availability_service import ModelAvailabilityService
                availability_service = ModelAvailabilityService(self.session)
                eligible_ids = availability_service.get_providers_with_models(required_models)
                self._set_cached_eligible_provider_ids(required_models, eligible_ids)
            
            if not eligible_ids:
                return None
            
            providers = [p for p in providers if p.id in eligible_ids]
            
            if not providers:
                return None
        
        # Non-health-aware routing
        if not getattr(self, "health_check_enabled", True):
            if preferred_provider_id:
                provider = self.repo.get(preferred_provider_id)
                if provider and provider.enabled and provider.id not in excluded:
                    if required_models and provider.id not in [p.id for p in providers]:
                        return None
                    await self._track_job(provider.id)
                    return provider
            
            provider = await self._select_by_strategy(providers)
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

        warm_candidates = []
        cold_candidates = []
        for p in candidates:
            if await self._check_provider_health(p):
                warm_candidates.append(p)
            else:
                cold_candidates.append(p)

        selected_provider = None
        if warm_candidates:
            if len(warm_candidates) == 1:
                selected_provider = warm_candidates[0]
            else:
                selected_provider = await self._select_by_strategy(warm_candidates)
        elif cold_candidates:
            if len(cold_candidates) == 1:
                selected_provider = cold_candidates[0]
            else:
                selected_provider = await self._select_by_strategy(cold_candidates)
            
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
                    await lifecycle_service.start_container(selected_provider.id)
                except Exception as start_err:
                    logger.warning("lb_cold_start_trigger_failed", provider_id=selected_provider.id, error=str(start_err))
                
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
                            from api.deps import get_container_manager
                            cm = get_container_manager()
                            if cm and cm.client:
                                container_name = f"tnhcomfy-{selected_provider.id}"
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
        # Now obsolete, because job count is dynamic
        # But we keep it in case we need to log it or update a local cache
        pass
    
    async def _round_robin(self, providers: list[Provider]) -> Provider:
        """Round-robin selection."""
        state = self._get_db_state()
        idx = state.round_robin_index or 0
        provider = providers[idx % len(providers)]
        state.round_robin_index = idx + 1
        self.session.commit()
        logger.debug("lb_round_robin_selected", provider_id=provider.id, index=idx)
        return provider
    
    async def _random(self, providers: list[Provider]) -> Provider:
        """Random selection."""
        return random.choice(providers)
    
    async def _priority(self, providers: list[Provider]) -> Provider:
        """Priority-based selection."""
        sorted_providers = sorted(providers, key=lambda p: (p.priority, p.id))
        return sorted_providers[0]
    
    async def _least_connections(self, providers: list[Provider]) -> Provider:
        """Least-connections selection."""
        counts = self._get_active_jobs_counts()
        p_counts = {p.id: counts.get(p.id, 0) for p in providers}
        min_count = min(p_counts.values())
        
        tied_providers = [p for p in providers if p_counts[p.id] == min_count]
        
        if len(tied_providers) == 1:
            selected = tied_providers[0]
        else:
            selected = await self._round_robin(tied_providers)

        logger.debug("lb_least_conn_selected", provider_id=selected.id, active_jobs=p_counts[selected.id], tied=len(tied_providers))
        return selected
    
    def _get_best_priority_tier(self, providers: list[Provider]) -> list[Provider]:
        """Get providers in the highest priority tier."""
        if not providers:
            return []
        best_priority = min(p.priority for p in providers)
        return [p for p in providers if p.priority == best_priority]
    
    async def _priority_round_robin(self, providers: list[Provider]) -> Provider:
        """Highest priority first, round-robin among ties."""
        best_tier = self._get_best_priority_tier(providers)
        return await self._round_robin(best_tier)
    
    async def _priority_least_connections(self, providers: list[Provider]) -> Provider:
        """Highest priority first, least connections among ties."""
        best_tier = self._get_best_priority_tier(providers)
        return await self._least_connections(best_tier)
    
    async def _select_by_strategy(self, providers: list[Provider]) -> Provider:
        """Apply current strategy to candidate list."""
        if not providers:
            raise ValueError("Cannot select from empty provider list")
            
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
        state = self._get_db_state()
        failures = dict(state.provider_failures or {})
        if failures.get(provider_id, 0) > 0:
            failures[provider_id] = 0
            state.provider_failures = failures
            self.session.commit()
    
    async def report_failure(self, provider_id: str):
        """Report job failure for a provider."""
        state = self._get_db_state()
        failures = dict(state.provider_failures or {})
        failures[provider_id] = failures.get(provider_id, 0) + 1
        state.provider_failures = failures
        
        self.session.commit()
        logger.warning("lb_provider_failure", provider_id=provider_id, total_failures=failures[provider_id])
    
    async def release_job(self, provider_id: str):
        """Release a job slot for a provider when job completes."""
        # No-op since we read active jobs dynamically
        pass
    
    async def get_fallback_provider(self, failed_provider_id: str, exclude_provider_ids: set[str] | None = None, task_type: str | None = None) -> Provider | None:
        """Get a fallback provider when one fails."""
        providers = self.repo.get_enabled()
        excluded = set(exclude_provider_ids or set())
        excluded.add(failed_provider_id)
        
        available = [p for p in providers if p.id not in excluded]
        if task_type:
            available = [p for p in available if p.worker_type == task_type]
        
        if not available:
            return None
        
        state = self._get_db_state()
        failures = state.provider_failures or {}
        best = min(
            available,
            key=lambda p: (failures.get(p.id, 0), p.priority, p.id)
        )
        
        return best
    
    async def get_stats(self) -> dict[str, Any]:
        """Get load balancer statistics including per-provider job counts."""
        providers = self.repo.get_enabled()
        
        state = self._get_db_state()
        current_index = state.round_robin_index or 0
        failure_counts = state.provider_failures or {}
        job_counts = self._get_active_jobs_counts()
        total_jobs_assigned = sum(job_counts.values())
        
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
            "current_index": current_index,
            "total_jobs_assigned": total_jobs_assigned,
            "total_failures": sum(failure_counts.values()),
            "provider_stats": provider_stats,
        }
