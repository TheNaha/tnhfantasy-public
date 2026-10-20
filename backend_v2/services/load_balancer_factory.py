
from sqlmodel import Session

from infrastructure.repositories import LoadBalancingRepository
from services.load_balancer import (
    LoadBalancer,
    LoadBalancerRuntimeState,
    MODALITY_STATE_IDS,
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
    """Create a load balancer with either an explicit or persisted strategy.

    Each task type gets its OWN runtime state, and therefore its own
    `provider_failures`, `provider_job_counts` and `round_robin_index`.

    TTS used to share the image state (`state_id=1`). That is wrong because a
    single provider can serve both modalities — the same ComfyUI container
    serves `image` and `tts` — so a TTS outage incremented the failure count
    on a provider that was perfectly healthy for images, and the image path's
    circuit breaker then took it out of rotation. The failure counts crossed
    modalities, and `get_stats` reported the shared counters as if they were
    a per-modality breakdown.

    No migration is needed: `LoadBalancerState` rows are keyed by `id` and
    created on demand by `save_state_to_db`, and each `LoadBalancer` loads
    its own row on construction.
    """
    if task_type == "llm":
        return LoadBalancer(
            session,
            strategy=strategy or "priority",
            runtime_state=runtime_state or get_runtime_state(MODALITY_STATE_IDS["llm"]),
            state_id=MODALITY_STATE_IDS["llm"],
        )
    if task_type == "tts":
        return LoadBalancer(
            session,
            strategy=strategy or get_load_balancing_strategy(session),
            runtime_state=runtime_state or get_runtime_state(MODALITY_STATE_IDS["tts"]),
            state_id=MODALITY_STATE_IDS["tts"],
        )
    return LoadBalancer(
        session,
        strategy=strategy or get_load_balancing_strategy(session),
        runtime_state=runtime_state or get_runtime_state(MODALITY_STATE_IDS["image"]),
        state_id=MODALITY_STATE_IDS["image"],
    )