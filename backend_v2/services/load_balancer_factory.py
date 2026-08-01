
from sqlmodel import Session

from infrastructure.repositories import LoadBalancingRepository
from services.load_balancer import LoadBalancer, LoadBalancerRuntimeState


def get_load_balancing_strategy(session: Session, default: str = "round-robin") -> str:
    """Read the configured load balancing strategy from persistence."""
    config = LoadBalancingRepository(session).get()
    return config.strategy if config else default


def create_load_balancer(
    session: Session,
    *,
    strategy: str | None = None,
    runtime_state: LoadBalancerRuntimeState | None = None,
) -> LoadBalancer:
    """Create a load balancer with either an explicit or persisted strategy."""
    return LoadBalancer(
        session,
        strategy=strategy or get_load_balancing_strategy(session),
        runtime_state=runtime_state,
    )