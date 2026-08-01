from sqlmodel import Session

from core.entities import Provider
from services.load_balancer import LoadBalancerRuntimeState
from services.load_balancer_factory import (
    create_load_balancer,
    get_load_balancing_strategy,
)


def test_get_load_balancing_strategy_defaults(session: Session):
    strategy = get_load_balancing_strategy(session)
    assert strategy == "round-robin"


def test_create_load_balancer_uses_explicit_runtime_state(session: Session):
    runtime_state = LoadBalancerRuntimeState()
    balancer = create_load_balancer(session, runtime_state=runtime_state)

    assert balancer.runtime_state is runtime_state


def test_create_load_balancer_uses_persisted_strategy(session: Session):
    provider = Provider(
        id="provider-1",
        type="modal",
        enabled=True,
        priority=1,
        credentials={},
        config={},
        container_config={"port": 8000},
    )
    session.add(provider)
    session.commit()

    balancer = create_load_balancer(session)

    assert balancer.strategy == "round-robin"