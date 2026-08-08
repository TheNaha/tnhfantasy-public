
from sqlmodel import Session

from infrastructure.repositories import LoadBalancingRepository
from services.load_balancer import (
    LoadBalancer,
    LoadBalancerRuntimeState,
    get_global_runtime_state,
    get_runtime_state,
)


def get_load_balancing_strategy(session: Session, default: str = "round-robin") -> str:
    """Read the configured load balancing strategy from persistence."""
    config = LoadBalancingRepository(session).get()
    return config.strategy if config else default


def create_load_balancer(
    session: Session,
    *,
    task_type: str = "image",
    strategy: str | None = None,
    runtime_state: LoadBalancerRuntimeState | None = None,
) -> LoadBalancer:
    """Create a load balancer with either an explicit or persisted strategy."""
    if task_type == "llm":
        return LoadBalancer(
            session,
            strategy=strategy or "priority",
            runtime_state=runtime_state or get_runtime_state(2),
            state_id=2
        )
    else:
        return LoadBalancer(
            session,
            strategy=strategy or get_load_balancing_strategy(session),
            runtime_state=runtime_state or get_global_runtime_state(),
            state_id=1
        )