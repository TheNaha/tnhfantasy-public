# Services module exports
#
# The `services` package contains application business logic.
# Each service class is session-scoped (receives a SQLModel Session in __init__)
# and coordinates repositories, events, and external provider calls.
#
#   JobService       – Job CRUD, status transitions, ETA calculation
#   JobQueue         – Async in-process queue (worker pool)
#   ProviderService  – Provider CRUD and load-balancer config
#   ModelService     – Model metadata management (V1 flat schema)
#   ContainerManager – Docker/Podman container lifecycle
#   LoadBalancer     – Route jobs across providers (round-robin, least-conn, etc.)
#   ModelAvailabilityService – Pre-flight check: are required models ready?
from .job_service import JobService
from .provider_service import ProviderService
from .model_service import ModelService
from .job_queue import JobQueue, job_queue
from .container_manager import ContainerManager
from .load_balancer import LoadBalancer
from .model_availability_service import ModelAvailabilityService

__all__ = [
    "JobService",
    "ProviderService",
    "ModelService",
    "JobQueue",
    "job_queue",
    "ContainerManager",
    "LoadBalancer",
    "ModelAvailabilityService",
]

