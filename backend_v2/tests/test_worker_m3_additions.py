import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session


from core.entities import Provider
from services.load_balancer import LoadBalancer


# -----------------------------------------------------------------------------
# Test Load Balancer Health check routing and engine warm-up
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_load_balancer_health_checks(session: Session, monkeypatch):
    # Setup two mock providers
    p1 = Provider(
        id="warm-provider",
        type="modal",
        enabled=True,
        priority=1,
        credentials={},
        config={},
    )
    p2 = Provider(
        id="cold-provider",
        type="modal",
        enabled=True,
        priority=1,
        credentials={},
        config={},
    )
    session.add(p1)
    session.add(p2)
    session.commit()

    # Create LoadBalancer and force health checks enabled
    lb = LoadBalancer(session, strategy="round-robin")
    lb.health_check_enabled = True
    monkeypatch.setenv("COMFY_PROVIDER_AUTOSTART_ENABLED", "1")

    # Mock health check function (task_type param added with the
    # per-modality circuit-breaker thresholds).
    async def mock_check_health(self_lb, provider, task_type="image"):
        # p1 is warm, p2 is cold
        return provider.id == "warm-provider"

    monkeypatch.setattr(LoadBalancer, "_check_provider_health", mock_check_health)

    # When both exist, we route only to the warm provider
    selected = await lb.get_next_provider()
    assert selected is not None
    assert selected.id == "warm-provider"

    # Now test what happens when only cold providers exist
    session.delete(p1)
    session.commit()

    # Mock engine factory: the cold provider's engine reports healthy, so the
    # fire-and-forget warm-up fills the health cache keyed by in_process:{id}.
    mock_engine = MagicMock()
    mock_engine.check_health = AsyncMock(return_value={"status": "healthy"})

    with patch("services.engines.engine_factory.can_create_engine", return_value=True), \
         patch("services.engines.engine_factory.get_engine", return_value=mock_engine):
        selected = await lb.get_next_provider()
        assert selected is not None
        assert selected.id == "cold-provider"

        # Cold-start warmup runs fire-and-forget in a background task:
        # selection returns immediately, so pump the loop (real sleeps so the
        # event loop processes the pending background task) until the task
        # fills the health cache.
        from services import load_balancer as lb_module
        for _ in range(50):
            if f"in_process:{selected.id}" in lb_module._provider_health_cache:
                break
            await asyncio.sleep(0.01)
        assert lb_module._provider_health_cache.get(f"in_process:{selected.id}") is True
