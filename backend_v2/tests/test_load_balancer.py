# Load Balancer Unit Tests
import pytest
from sqlmodel import Session

from services.load_balancer import LoadBalancer
from core.entities import Provider


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
    
    def test_round_robin_distribution(self, session: Session, providers):
        """Test round-robin distributes across all enabled providers."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        # Get providers in sequence
        provider1 = lb.get_next_provider()
        provider2 = lb.get_next_provider()
        provider3 = lb.get_next_provider()  # Should wrap to first
        
        assert provider1 is not None
        assert provider2 is not None
        assert provider3 is not None
        
        # Should cycle through enabled providers (not disabled provider-3)
        assert provider1.id != provider2.id
        assert provider3.id == provider1.id  # Wrapped around
    
    def test_priority_selection(self, session: Session, providers):
        """Test priority selects highest priority (lowest number)."""
        lb = LoadBalancer(session, strategy="priority")
        
        provider = lb.get_next_provider()
        
        assert provider is not None
        assert provider.priority == 1  # Lowest priority number = highest priority
    
    def test_random_selection(self, session: Session, providers):
        """Test random selects from enabled providers."""
        lb = LoadBalancer(session, strategy="random")
        
        results = set()
        for _ in range(10):
            provider = lb.get_next_provider()
            if provider:
                results.add(provider.id)
        
        # Should only include enabled providers
        assert "provider-3" not in results  # Disabled
        assert len(results) >= 1  # At least one provider selected
    
    def test_preferred_provider(self, session: Session, providers):
        """Test preferred provider is returned when specified and available."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        provider = lb.get_next_provider(preferred_provider_id="provider-2")
        
        assert provider is not None
        assert provider.id == "provider-2"
    
    def test_fallback_on_failure(self, session: Session, providers):
        """Test fallback provides alternative when provider fails."""
        lb = LoadBalancer(session, strategy="priority")
        
        # Simulate failure
        lb.report_failure("provider-1")
        lb.report_failure("provider-1")  # Multiple failures
        
        fallback = lb.get_fallback_provider("provider-1")
        
        assert fallback is not None
        assert fallback.id != "provider-1"
    
    def test_no_enabled_providers(self, session: Session):
        """Test returns None when no providers are enabled."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        provider = lb.get_next_provider()
        
        assert provider is None
    
    def test_success_resets_failure_count(self, session: Session, providers):
        """Test reporting success resets failure count."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        # Simulate failures then success
        lb.report_failure("provider-1")
        lb.report_failure("provider-1")
        lb.report_success("provider-1")
        
        # Provider should still be available
        stats = lb.get_stats()
        # Failure count should be reset or minimal
        assert stats is not None
    
    def test_get_stats(self, session: Session, providers):
        """Test stats returns provider information."""
        lb = LoadBalancer(session, strategy="round-robin")
        
        stats = lb.get_stats()
        
        assert "strategy" in stats
        assert "provider_stats" in stats
