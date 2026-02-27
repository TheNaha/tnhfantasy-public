# Load Balancer - Distributes jobs across multiple providers.
import random
import threading
from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlmodel import Session, select

from core.entities import Provider, LoadBalancerState
from infrastructure.repositories import ProviderRepository
from infrastructure.logging import get_logger

logger = get_logger("load_balancer")


class LoadBalancer:
    """Load balances jobs across multiple serverless providers."""
    
    # Class-level state for round-robin (persists across instances in-memory)
    _round_robin_index: int = 0
    _provider_failures: Dict[str, int] = {}
    _provider_job_counts: Dict[str, int] = {}  # Track jobs per provider
    _initialized: bool = False
    _lock = threading.Lock()  # Thread-safe state updates
    
    @classmethod
    def load_state_from_db(cls, session: Session):
        """Load persisted state from database on startup."""
        with cls._lock:
            try:
                state = session.exec(select(LoadBalancerState).where(LoadBalancerState.id == 1)).first()
                if state:
                    cls._round_robin_index = state.round_robin_index
                    cls._provider_failures = state.provider_failures or {}
                    # DON'T load persisted job counts - they represent historical totals
                    # On startup, reset to 0 and calculate from actually running jobs
                
                # Calculate actual running job counts from database
                from core.entities import Job, JobStatus
                running_jobs = session.exec(
                    select(Job).where(Job.status == JobStatus.RUNNING)
                ).all()
                
                cls._provider_job_counts = {}
                for job in running_jobs:
                    if job.provider_id:
                        cls._provider_job_counts[job.provider_id] = \
                            cls._provider_job_counts.get(job.provider_id, 0) + 1
                
                print(f"[LoadBalancer] Loaded state: index={cls._round_robin_index}, active_jobs={cls._provider_job_counts} (from {len(running_jobs)} running jobs)")
                logger.info("lb_state_loaded", index=cls._round_robin_index, active_jobs=cls._provider_job_counts, running_jobs=len(running_jobs))
                cls._initialized = True
            except Exception as e:
                print(f"[LoadBalancer] Warning: Could not load state from DB: {e}")
                logger.warning("lb_state_load_failed", error=str(e))
                cls._provider_job_counts = {}  # Reset on error
                cls._initialized = True
    
    @classmethod
    def save_state_to_db(cls, session: Session):
        """Persist state to database."""
        with cls._lock:
            try:
                state = session.exec(select(LoadBalancerState).where(LoadBalancerState.id == 1)).first()
                if not state:
                    state = LoadBalancerState(id=1)
                    session.add(state)
                
                state.round_robin_index = cls._round_robin_index
                state.provider_failures = cls._provider_failures
                state.provider_job_counts = cls._provider_job_counts
                state.updated_at = datetime.utcnow()
                session.commit()
            except Exception as e:
                print(f"[LoadBalancer] Warning: Could not save state to DB: {e}")
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
        if not LoadBalancer._initialized:
            LoadBalancer.load_state_from_db(session)
    
    def get_next_provider(
        self, 
        preferred_provider_id: Optional[str] = None,
        required_models: Optional[Dict[str, List[str]]] = None
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
            if provider and provider.enabled:
                # Check if preferred provider is in eligible list (if filtering)
                if required_models and provider.id not in [p.id for p in providers]:
                    # Preferred provider doesn't have required models
                    return None
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
        with LoadBalancer._lock:
            if provider_id not in LoadBalancer._provider_job_counts:
                LoadBalancer._provider_job_counts[provider_id] = 0
            LoadBalancer._provider_job_counts[provider_id] += 1
            
            # Persist state periodically (every 5 jobs)
            total_jobs = sum(LoadBalancer._provider_job_counts.values())
        
        if total_jobs % 5 == 0:
            LoadBalancer.save_state_to_db(self.session)
    
    def _round_robin(self, providers: List[Provider]) -> Provider:
        """Round-robin selection."""
        with LoadBalancer._lock:
            provider = providers[LoadBalancer._round_robin_index % len(providers)]
            LoadBalancer._round_robin_index += 1
            index = LoadBalancer._round_robin_index
        print(f"[LoadBalancer] Round-robin selected: {provider.id} (index={index})")
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
        counts = {p.id: LoadBalancer._provider_job_counts.get(p.id, 0) for p in providers}
        min_count = min(counts.values())
        
        # Find all providers with minimum count (tied)
        tied_providers = [p for p in providers if counts[p.id] == min_count]
        
        if len(tied_providers) == 1:
            selected = tied_providers[0]
        else:
            # Use round-robin among tied providers for fair distribution
            selected = tied_providers[LoadBalancer._round_robin_index % len(tied_providers)]
            LoadBalancer._round_robin_index += 1
        
        print(f"[LoadBalancer] Least-connections selected: {selected.id} (active_jobs={counts[selected.id]}, tied={len(tied_providers)})")
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
        provider = best_tier[LoadBalancer._round_robin_index % len(best_tier)]
        LoadBalancer._round_robin_index += 1
        print(f"[LoadBalancer] Priority-RR selected: {provider.id} (priority={provider.priority}, tier_size={len(best_tier)})")
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
        counts = {p.id: LoadBalancer._provider_job_counts.get(p.id, 0) for p in best_tier}
        min_count = min(counts.values())
        
        # Find all providers with minimum count (tied)
        tied_providers = [p for p in best_tier if counts[p.id] == min_count]
        
        if len(tied_providers) == 1:
            selected = tied_providers[0]
        else:
            # Use round-robin among tied providers
            selected = tied_providers[LoadBalancer._round_robin_index % len(tied_providers)]
            LoadBalancer._round_robin_index += 1
        
        print(f"[LoadBalancer] Priority-LC selected: {selected.id} (priority={selected.priority}, active_jobs={counts[selected.id]}, tied={len(tied_providers)})")
        logger.debug("lb_priority_lc_selected", provider_id=selected.id, priority=selected.priority, active_jobs=counts[selected.id], tied=len(tied_providers))
        return selected
    
    def report_success(self, provider_id: str):
        """Report successful job completion for a provider."""
        with LoadBalancer._lock:
            if provider_id in LoadBalancer._provider_failures:
                LoadBalancer._provider_failures[provider_id] = 0
    
    def report_failure(self, provider_id: str):
        """Report job failure for a provider."""
        with LoadBalancer._lock:
            if provider_id not in LoadBalancer._provider_failures:
                LoadBalancer._provider_failures[provider_id] = 0
            
            LoadBalancer._provider_failures[provider_id] += 1
            failures = LoadBalancer._provider_failures[provider_id]
        print(f"[LoadBalancer] Provider {provider_id} failures: {failures}")
        logger.warning("lb_provider_failure", provider_id=provider_id, total_failures=failures)
    
    def release_job(self, provider_id: str):
        """
        Release a job slot for a provider when job completes.
        This decrements the active job count for least-connections tracking.
        Should be called after every job completion (success or failure).
        """
        with LoadBalancer._lock:
            if provider_id in LoadBalancer._provider_job_counts:
                LoadBalancer._provider_job_counts[provider_id] = max(
                    0, LoadBalancer._provider_job_counts[provider_id] - 1
                )
                active_jobs = LoadBalancer._provider_job_counts[provider_id]
            else:
                active_jobs = 0
        print(f"[LoadBalancer] Released job from {provider_id}, active_jobs={active_jobs}")
        logger.debug("lb_job_released", provider_id=provider_id, active_jobs=active_jobs)
    
    def get_fallback_provider(self, failed_provider_id: str) -> Optional[Provider]:
        """
        Get a fallback provider when one fails.
        
        Args:
            failed_provider_id: ID of provider that failed
            
        Returns:
            Alternative provider or None
        """
        providers = self.repo.get_enabled()
        
        # Filter out the failed provider
        available = [p for p in providers if p.id != failed_provider_id]
        
        if not available:
            return None
        
        # Return provider with fewest failures
        best = min(
            available,
            key=lambda p: LoadBalancer._provider_failures.get(p.id, 0)
        )
        
        return best
    
    def get_stats(self) -> Dict[str, Any]:
        """Get load balancer statistics including per-provider job counts."""
        providers = self.repo.get_enabled()
        
        # Build detailed per-provider stats
        provider_stats = []
        for p in providers:
            provider_stats.append({
                "id": p.id,
                "enabled": p.enabled,
                "priority": p.priority,
                "jobs_assigned": LoadBalancer._provider_job_counts.get(p.id, 0),
                "failures": LoadBalancer._provider_failures.get(p.id, 0),
            })
        
        return {
            "strategy": self.strategy,
            "total_providers": len(providers),
            "current_index": LoadBalancer._round_robin_index,
            "total_jobs_assigned": sum(LoadBalancer._provider_job_counts.values()),
            "provider_stats": provider_stats,
        }

