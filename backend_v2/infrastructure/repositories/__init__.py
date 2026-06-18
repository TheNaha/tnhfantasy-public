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
from .provider_repo import ProviderRepository, LoadBalancingRepository
from .model_repo_v2 import ModelRepositoryV2

__all__ = [
    "JobRepository",
    "ProviderRepository",
    "LoadBalancingRepository",
    "ModelRepositoryV2",
]
