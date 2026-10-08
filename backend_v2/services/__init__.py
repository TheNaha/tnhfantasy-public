# Services module exports
#
# The `services` package contains application business logic.
# Each service class is session-scoped (receives a SQLModel Session in __init__)
# and coordinates repositories, events, and external provider calls.
#
#   JobService       – Job CRUD, status transitions, ETA calculation
#   JobQueue         – Async in-process queue (worker pool)
#   ProviderService  – Provider CRUD and load-balancer config
#   LoadBalancer     – Route jobs across providers (round-robin, least-conn, etc.)
#   ModelAvailabilityService – Pre-flight check: are required models ready?

__all__ = [
    "JobQueue",
    "JobService",
    "LoadBalancer",
    "ModelAvailabilityService",
    "ProviderService",
]

