# Load Balancer - Distributes jobs across multiple providers.
import random
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set
from datetime import datetime

from sqlmodel import Session, select

from core.entities import Provider, LoadBalancerState
from infrastructure.repositories import ProviderRepository
from infrastructure.logging import get_logger

logger = get_logger("load_balancer")


@dataclass
class LoadBalancerRuntimeState:
    """Shared in-memory runtime state for load balancing decisions."""

    round_robin_index: int = 0
    provider_failures: Dict[str, int] = field(default_factory=dict)
    provider_job_counts: Dict[str, int] = field(default_factory=dict)
    initialized: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "round_robin_index": self.round_robin_index,
                "provider_failures": dict(self.provider_failures),
                "provider_job_counts": dict(self.provider_job_counts),
                "initialized": self.initialized,
            }

    def reset(self) -> None:
        with self.lock:
            self.round_robin_index = 0
            self.provider_failures = {}
            self.provider_job_counts = {}
            self.initialized = False


_runtime_state = LoadBalancerRuntimeState()


class LoadBalancer:
    """Load balances jobs across multiple serverless providers."""

    _runtime_state = _runtime_state

    @classmethod
    def _get_state_snapshot(cls) -> Dict[str, Any]:
        """Return a copy of current in-memory balancer state."""
        snapshot = cls._runtime_state.snapshot()
        snapshot.pop("initialized", None)
        return snapshot

    @classmethod
    def reset_state(cls):
        """Reset in-memory state. Intended for tests and controlled startup flows."""
        cls._runtime_state.reset()
    
    @classmethod
    def load_state_from_db(cls, session: Session):
        """Load persisted state from database on startup."""
        try:
            state = session.exec(select(LoadBalancerState).where(LoadBalancerState.id == 1)).first()

            # Calculate actual running job counts from database.
            from core.entities import Job, JobStatus

            running_jobs = session.exec(
                select(Job).where(Job.status == JobStatus.RUNNING)
            ).all()

            active_job_counts: Dict[str, int] = {}
            for job in running_jobs:
                if job.provider_id:
                    active_job_counts[job.provider_id] = active_job_counts.get(job.provider_id, 0) + 1

            with cls._runtime_state.lock:
                cls._runtime_state.round_robin_index = state.round_robin_index if state else 0
                cls._runtime_state.provider_failures = dict(state.provider_failures or {}) if state else {}
                # DON'T load persisted job counts - they represent historical totals.
                # On startup, reset to the actual currently running jobs only.
                cls._runtime_state.provider_job_counts = active_job_counts
                cls._runtime_state.initialized = True

            logger.info(
                "lb_state_loaded",
                index=state.round_robin_index if state else 0,
                active_jobs=active_job_counts,
                running_jobs=len(running_jobs),
            )
        except Exception as e:
            with cls._runtime_state.lock:
                cls._runtime_state.provider_job_counts = {}
                cls._runtime_state.initialized = True
            logger.warning("lb_state_load_failed", error=str(e))
    
    @classmethod
    def save_state_to_db(cls, session: Session):
        """Persist state to database."""
        snapshot = cls._get_state_snapshot()
        try:
            state = session.exec(select(LoadBalancerState).where(LoadBalancerState.id == 1)).first()
            if not state:
                state = LoadBalancerState(id=1)
                session.add(state)

            state.round_robin_index = snapshot["round_robin_index"]
            state.provider_failures = snapshot["provider_failures"]
            state.provider_job_counts = snapshot["provider_job_counts"]
            state.updated_at = datetime.utcnow()
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("lb_state_save_failed", error=str(e))
    
    def __init__(self, session: Session, strategy: str = "round-robin"):
        """
        Initialize load balancer.
        
        Args:
            session: Database session
            strategy: Load balancing strategy (round-robin, random, priority)
        """
        self.session = session
        self.repo = ProviderRepository(session)
        self.strategy = strategy
        
        # Load state from DB if not initialized
        if not LoadBalancer._runtime_state.initialized:
            LoadBalancer.load_state_from_db(session)
    
    def get_next_provider(
        self, 
        preferred_provider_id: Optional[str] = None,
        required_models: Optional[Dict[str, List[str]]] = None,
        exclude_provider_ids: Optional[Set[str]] = None,
    ) -> Optional[Provider]:
        """
        Get the next provider to handle a job.
        
        Args:
            preferred_provider_id: Optional specific provider to use
            required_models: Optional dict of {directory: [filenames]} for model-aware routing
            
        Returns:
            Provider or None if no providers available
        """
        providers = self.repo.get_enabled()
        excluded = exclude_provider_ids or set()
        if excluded:
            providers = [p for p in providers if p.id not in excluded]
        
        if not providers:
            return None
        
        # Filter by model availability if required
        if required_models:
            from .model_availability_service import ModelAvailabilityService
            availability_service = ModelAvailabilityService(self.session)
            eligible_ids = availability_service.get_providers_with_models(required_models)
            
            if not eligible_ids:
                # No provider has all required models
                return None
            
            # Filter to only eligible providers
            providers = [p for p in providers if p.id in eligible_ids]
            
            if not providers:
                return None
        
        # If specific provider requested, try to use it
        if preferred_provider_id:
            provider = self.repo.get(preferred_provider_id)
            if provider and provider.enabled and provider.id not in excluded:
                # Check if preferred provider is in eligible list (if filtering)
                if required_models and provider.id not in [p.id for p in providers]:
                    # Preferred provider doesn't have required models
                    return None
                self._track_job(provider.id)
                return provider
        
        # Apply load balancing strategy
        if self.strategy == "round-robin":
            provider = self._round_robin(providers)
        elif self.strategy == "random":
            provider = self._random(providers)
        elif self.strategy == "priority":
            provider = self._priority(providers)
        elif self.strategy == "least-connections":
            provider = self._least_connections(providers)
        elif self.strategy == "priority-round-robin":
            provider = self._priority_round_robin(providers)
        elif self.strategy == "priority-least-connections":
            provider = self._priority_least_connections(providers)
        else:
            provider = self._round_robin(providers)
        
        # Track job assigned to this provider
        self._track_job(provider.id)
        
        return provider

    
    def _track_job(self, provider_id: str):
        """Track that a job was assigned to a provider."""
        with LoadBalancer._runtime_state.lock:
            if provider_id not in LoadBalancer._runtime_state.provider_job_counts:
                LoadBalancer._runtime_state.provider_job_counts[provider_id] = 0
            LoadBalancer._runtime_state.provider_job_counts[provider_id] += 1
            
            # Persist state periodically (every 5 jobs)
            total_jobs = sum(LoadBalancer._runtime_state.provider_job_counts.values())

        if total_jobs % 5 == 0:
            LoadBalancer.save_state_to_db(self.session)
    
    def _round_robin(self, providers: List[Provider]) -> Provider:
        """Round-robin selection."""
        with LoadBalancer._runtime_state.lock:
            provider = providers[LoadBalancer._runtime_state.round_robin_index % len(providers)]
            LoadBalancer._runtime_state.round_robin_index += 1
            index = LoadBalancer._runtime_state.round_robin_index
        logger.debug("lb_round_robin_selected", provider_id=provider.id, index=index)
        return provider
    
    def _random(self, providers: List[Provider]) -> Provider:
        """Random selection."""
        return random.choice(providers)
    
    def _priority(self, providers: List[Provider]) -> Provider:
        """
        Priority-based selection.
        Lower priority number = higher priority.
        """
        sorted_providers = sorted(providers, key=lambda p: p.priority)
        return sorted_providers[0]
    
    def _least_connections(self, providers: List[Provider]) -> Provider:
        """
        Least-connections selection.
        Selects the provider with fewest active jobs.
        When tied, uses round-robin among tied providers for fair distribution.
        """
        # Get job counts
        with LoadBalancer._runtime_state.lock:
            counts = {p.id: LoadBalancer._runtime_state.provider_job_counts.get(p.id, 0) for p in providers}
            min_count = min(counts.values())
        
        # Find all providers with minimum count (tied)
        tied_providers = [p for p in providers if counts[p.id] == min_count]
        
        if len(tied_providers) == 1:
            selected = tied_providers[0]
        else:
            # Use round-robin among tied providers for fair distribution
            with LoadBalancer._runtime_state.lock:
                selected = tied_providers[LoadBalancer._runtime_state.round_robin_index % len(tied_providers)]
                LoadBalancer._runtime_state.round_robin_index += 1

        logger.debug("lb_least_conn_selected", provider_id=selected.id, active_jobs=counts[selected.id], tied=len(tied_providers))
        return selected
    
    def _get_best_priority_tier(self, providers: List[Provider]) -> List[Provider]:
        """Get providers in the highest priority tier (lowest priority number)."""
        if not providers:
            return []
        best_priority = min(p.priority for p in providers)
        return [p for p in providers if p.priority == best_priority]
    
    def _priority_round_robin(self, providers: List[Provider]) -> Provider:
        """
        Priority + Round-Robin: Among providers with the best priority,
        use round-robin selection.
        """
        best_tier = self._get_best_priority_tier(providers)
        if len(best_tier) == 1:
            return best_tier[0]
        
        # Round-robin within the best priority tier
        with LoadBalancer._runtime_state.lock:
            provider = best_tier[LoadBalancer._runtime_state.round_robin_index % len(best_tier)]
            LoadBalancer._runtime_state.round_robin_index += 1
        logger.debug("lb_priority_rr_selected", provider_id=provider.id, priority=provider.priority, tier_size=len(best_tier))
        return provider
    
    def _priority_least_connections(self, providers: List[Provider]) -> Provider:
        """
        Priority + Least-Connections: Among providers with the best priority,
        select the one with fewest active jobs. Uses round-robin for ties.
        """
        best_tier = self._get_best_priority_tier(providers)
        if len(best_tier) == 1:
            return best_tier[0]
        
        # Get job counts for best tier
        with LoadBalancer._runtime_state.lock:
            counts = {p.id: LoadBalancer._runtime_state.provider_job_counts.get(p.id, 0) for p in best_tier}
            min_count = min(counts.values())
        
        # Find all providers with minimum count (tied)
        tied_providers = [p for p in best_tier if counts[p.id] == min_count]
        
        if len(tied_providers) == 1:
            selected = tied_providers[0]
        else:
            # Use round-robin among tied providers
            with LoadBalancer._runtime_state.lock:
                selected = tied_providers[LoadBalancer._runtime_state.round_robin_index % len(tied_providers)]
                LoadBalancer._runtime_state.round_robin_index += 1

        logger.debug("lb_priority_lc_selected", provider_id=selected.id, priority=selected.priority, active_jobs=counts[selected.id], tied=len(tied_providers))
        return selected
    
    def report_success(self, provider_id: str):
        """Report successful job completion for a provider."""
        with LoadBalancer._runtime_state.lock:
            if provider_id in LoadBalancer._runtime_state.provider_failures:
                LoadBalancer._runtime_state.provider_failures[provider_id] = 0
    
    def report_failure(self, provider_id: str):
        """Report job failure for a provider."""
        with LoadBalancer._runtime_state.lock:
            if provider_id not in LoadBalancer._runtime_state.provider_failures:
                LoadBalancer._runtime_state.provider_failures[provider_id] = 0
            
            LoadBalancer._runtime_state.provider_failures[provider_id] += 1
            failures = LoadBalancer._runtime_state.provider_failures[provider_id]
        logger.warning("lb_provider_failure", provider_id=provider_id, total_failures=failures)
    
    def release_job(self, provider_id: str):
        """
        Release a job slot for a provider when job completes.
        This decrements the active job count for least-connections tracking.
        Should be called after every job completion (success or failure).
        """
        with LoadBalancer._runtime_state.lock:
            if provider_id in LoadBalancer._runtime_state.provider_job_counts:
                LoadBalancer._runtime_state.provider_job_counts[provider_id] = max(
                    0, LoadBalancer._runtime_state.provider_job_counts[provider_id] - 1
                )
                active_jobs = LoadBalancer._runtime_state.provider_job_counts[provider_id]
            else:
                active_jobs = 0
        logger.debug("lb_job_released", provider_id=provider_id, active_jobs=active_jobs)
    
    def get_fallback_provider(self, failed_provider_id: str, exclude_provider_ids: Optional[Set[str]] = None) -> Optional[Provider]:
        """
        Get a fallback provider when one fails.
        
        Args:
            failed_provider_id: ID of provider that failed
            
        Returns:
            Alternative provider or None
        """
        providers = self.repo.get_enabled()
        excluded = set(exclude_provider_ids or set())
        excluded.add(failed_provider_id)
        
        # Filter out the failed provider
        available = [p for p in providers if p.id not in excluded]
        
        if not available:
            return None
        
        # Return provider with fewest failures
        with LoadBalancer._runtime_state.lock:
            best = min(
                available,
                key=lambda p: (LoadBalancer._runtime_state.provider_failures.get(p.id, 0), p.priority, p.id)
            )
        
        return best
    
    def get_stats(self) -> Dict[str, Any]:
        """Get load balancer statistics including per-provider job counts."""
        providers = self.repo.get_enabled()
        with LoadBalancer._runtime_state.lock:
            current_index = LoadBalancer._runtime_state.round_robin_index
            total_jobs_assigned = sum(LoadBalancer._runtime_state.provider_job_counts.values())
            failure_counts = dict(LoadBalancer._runtime_state.provider_failures)
            job_counts = dict(LoadBalancer._runtime_state.provider_job_counts)
        
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

