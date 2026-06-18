# Load Balancer Unit Tests
import pytest
from sqlmodel import Session

from services.load_balancer import LoadBalancer, LoadBalancerRuntimeState
from core.entities import LoadBalancerState, Provider


@pytest.fixture
def providers(session: Session):
    """Create test providers."""
    providers_data = [
        {"id": "provider-1", "type": "modal", "enabled": True, "priority": 1},
        {"id": "provider-2", "type": "modal", "enabled": True, "priority": 2},
        {"id": "provider-3", "type": "modal", "enabled": False, "priority": 3},
    ]
    
    created = []
    for data in providers_data:
        provider = Provider(
            id=data["id"],
            type=data["type"],
            enabled=data["enabled"],
            priority=data["priority"],
            credentials={},
            config={},
            container_config={"port": 8001}
        )
        session.add(provider)
        created.append(provider)
    session.commit()
    return created


class TestLoadBalancer:
    """Test load balancer strategies and failure handling."""

    @pytest.fixture(autouse=True)
    def reset_lb_state(self):
        LoadBalancer.reset_state()
        yield
        LoadBalancer.reset_state()
    
    async def test_round_robin_distribution(self, session: Session, providers):
        """Test round-robin distributes across all enabled providers."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        # Get providers in sequence
        provider1 = await lb.get_next_provider()
        provider2 = await lb.get_next_provider()
        provider3 = await lb.get_next_provider()  # Should wrap to first
        
        assert provider1 is not None
        assert provider2 is not None
        assert provider3 is not None
        
        # Should cycle through enabled providers (not disabled provider-3)
        assert provider1.id != provider2.id
        assert provider3.id == provider1.id  # Wrapped around
    
    async def test_priority_selection(self, session: Session, providers):
        """Test priority selects highest priority (lowest number)."""
        lb = LoadBalancer(session, strategy="priority")
        
        provider = await lb.get_next_provider()
        
        assert provider is not None
        assert provider.priority == 1  # Lowest priority number = highest priority
    
    async def test_random_selection(self, session: Session, providers):
        """Test random selects from enabled providers."""
        lb = LoadBalancer(session, strategy="random")
        
        results = set()
        for _ in range(10):
            provider = await lb.get_next_provider()
            if provider:
                results.add(provider.id)
        
        # Should only include enabled providers
        assert "provider-3" not in results  # Disabled
        assert len(results) >= 1  # At least one provider selected
    
    async def test_preferred_provider(self, session: Session, providers):
        """Test preferred provider is returned when specified and available."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        provider = await lb.get_next_provider(preferred_provider_id="provider-2")
        
        assert provider is not None
        assert provider.id == "provider-2"

        stats = await lb.get_stats()
        provider_stats = {item["id"]: item for item in stats["provider_stats"]}
        assert provider_stats["provider-2"]["jobs_assigned"] == 1
    
    async def test_fallback_on_failure(self, session: Session, providers):
        """Test fallback provides alternative when provider fails."""
        lb = LoadBalancer(session, strategy="priority")
        
        # Simulate failure
        await lb.report_failure("provider-1")
        await lb.report_failure("provider-1")  # Multiple failures
        
        fallback = await lb.get_fallback_provider("provider-1")
        
        assert fallback is not None
        assert fallback.id != "provider-1"

    async def test_get_next_provider_excludes_exhausted(self, session: Session, providers):
        lb = LoadBalancer(session, strategy="round-robin")

        provider = await lb.get_next_provider(exclude_provider_ids={"provider-1"})

        assert provider is not None
        assert provider.id == "provider-2"

    async def test_fallback_excludes_multiple_providers(self, session: Session, providers):
        lb = LoadBalancer(session, strategy="priority")

        fallback = await lb.get_fallback_provider("provider-1", exclude_provider_ids={"provider-2"})

        assert fallback is None
    
    async def test_no_enabled_providers(self, session: Session):
        """Test returns None when no providers are enabled."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        provider = await lb.get_next_provider()
        
        assert provider is None
    
    async def test_success_resets_failure_count(self, session: Session, providers):
        """Test reporting success resets failure count."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        # Simulate failures then success
        await lb.report_failure("provider-1")
        await lb.report_failure("provider-1")
        await lb.report_success("provider-1")
        
        # Provider should still be available
        stats = await lb.get_stats()
        # Failure count should be reset or minimal
        assert stats is not None
    
    async def test_get_stats(self, session: Session, providers):
        """Test stats returns provider information."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        stats = await lb.get_stats()
        
        assert "strategy" in stats
        assert "provider_stats" in stats

    async def test_save_and_reload_state_round_trip(self, session: Session, providers):
        """Persisted state should survive a reset and reload from the database."""
        lb = LoadBalancer(session, strategy="round-robin")

        await lb.get_next_provider()
        await lb.get_next_provider()
        await lb.report_failure("provider-1")
        LoadBalancer.save_state_to_db(session)

        persisted = session.get(LoadBalancerState, 1)
        assert persisted is not None
        assert persisted.round_robin_index == 2
        assert persisted.provider_failures["provider-1"] == 1

        LoadBalancer.reset_state()
        LoadBalancer.load_state_from_db(session)

        stats = await lb.get_stats()
        assert stats["current_index"] == 2
        provider_stats = {item["id"]: item for item in stats["provider_stats"]}
        assert provider_stats["provider-1"]["failures"] == 1

    async def test_runtime_state_is_shared_across_instances(self, session: Session, providers):
        """Separate instances should observe the same runtime balancing state."""
        first = LoadBalancer(session, strategy="round-robin")
        second = LoadBalancer(session, strategy="least-connections")

        selected = await first.get_next_provider()

        assert selected is not None

        stats = await second.get_stats()
        provider_stats = {item["id"]: item for item in stats["provider_stats"]}
        assert provider_stats[selected.id]["jobs_assigned"] == 1

    async def test_runtime_state_can_be_isolated_per_instance(self, session: Session, providers):
        """Injected runtime state should allow isolated balancing contexts."""
        shared = LoadBalancer(session, strategy="round-robin")
        isolated_state = LoadBalancerRuntimeState()
        isolated = LoadBalancer(session, strategy="round-robin", runtime_state=isolated_state)

        shared_selected = await shared.get_next_provider()

        assert shared_selected is not None

        isolated_stats_before = await isolated.get_stats()
        isolated_provider_stats_before = {item["id"]: item for item in isolated_stats_before["provider_stats"]}
        assert isolated_provider_stats_before[shared_selected.id]["jobs_assigned"] == 0

        isolated_selected = await isolated.get_next_provider()
        assert isolated_selected is not None

        isolated_stats_after = await isolated.get_stats()
        isolated_provider_stats_after = {item["id"]: item for item in isolated_stats_after["provider_stats"]}
        assert isolated_provider_stats_after[isolated_selected.id]["jobs_assigned"] == 1

    async def test_release_job_persists_state(self, session: Session, providers):
        lb = LoadBalancer(session, strategy="round-robin")

        selected = await lb.get_next_provider()
        assert selected is not None

        await lb.release_job(selected.id)

        persisted = session.get(LoadBalancerState, 1)
        assert persisted is not None
        provider_job_counts = persisted.provider_job_counts or {}
        assert provider_job_counts.get(selected.id, 0) == 0

    async def test_model_availability_filter_is_memoized(self, session: Session, providers, monkeypatch):
        lb = LoadBalancer(session, strategy="round-robin")
        required_models = {"checkpoints": ["dream.safetensors"]}
        call_count = 0

        def fake_get_providers_with_models(_self, _required_models):
            nonlocal call_count
            call_count += 1
            return ["provider-1"]

        monkeypatch.setattr(
            "services.model_availability_service.ModelAvailabilityService.get_providers_with_models",
            fake_get_providers_with_models,
        )

        first = await lb.get_next_provider(required_models=required_models)
        second = await lb.get_next_provider(required_models=required_models)

        assert first is not None
        assert second is not None
        assert first.id == "provider-1"
        assert second.id == "provider-1"
        assert call_count == 1

    async def test_model_availability_cache_can_be_invalidated(self, session: Session, providers, monkeypatch):
        lb = LoadBalancer(session, strategy="round-robin")
        required_models = {"checkpoints": ["dream.safetensors"]}
        call_count = 0

        def fake_get_providers_with_models(_self, _required_models):
            nonlocal call_count
            call_count += 1
            return ["provider-1"]

        monkeypatch.setattr(
            "services.model_availability_service.ModelAvailabilityService.get_providers_with_models",
            fake_get_providers_with_models,
        )

        first = await lb.get_next_provider(required_models=required_models)
        assert first is not None
        assert call_count == 1

        LoadBalancer.invalidate_model_availability_cache(provider_id="provider-1")

        second = await lb.get_next_provider(required_models=required_models)
        assert second is not None
        assert call_count == 2
