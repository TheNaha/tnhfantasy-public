# Repository exports
#
# All repository classes are re-exported from this package so callers can
# use a single import:
#
#   from infrastructure.repositories import JobRepository, ProviderRepository
#
# Repository classes are session-scoped – create a new instance per request
# using the FastAPI dependency in `api/deps.py`.
from .job_repo import JobRepository
from .model_repo_v2 import ModelRepositoryV2
from .provider_repo import LoadBalancingRepository, ProviderRepository

__all__ = [
    "JobRepository",
    "LoadBalancingRepository",
    "ModelRepositoryV2",
    "ProviderRepository",
]
