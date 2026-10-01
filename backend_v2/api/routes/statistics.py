# Statistics routes - Analytics and usage data
#
# Provides aggregated statistics computed from the `assets` index and the job
# table. Data is cached for 5 minutes (see `cache_stats`) to avoid re-running
# the aggregations on every request.
#
# The aggregation itself lives in `services/statistics_service.py`; this module
# is only the HTTP surface. It used to hold ~500 lines of aggregation logic
# that loaded every asset row into Python.
#
# KEY ENDPOINTS:
#   GET /api/statistics          – Overall usage summary (job counts, generation stats)
#   GET /api/statistics/detailed – Daily generation counts for chart rendering
#   GET /api/statistics/summary  – Headline numbers derived from the above
import asyncio

from fastapi import APIRouter

from infrastructure.cache import cache_stats
from services import statistics_service

router = APIRouter(prefix="/api/statistics", tags=["statistics"])


@router.get("")
@cache_stats
async def get_statistics():
    """Generate comprehensive statistics from the DB-backed assets index."""
    return await asyncio.to_thread(statistics_service.get_base_statistics)


@router.get("/detailed")
@cache_stats
async def get_detailed_statistics(timeRange: str = "all"):
    """
    Extended statistics with data optimized for charts and visualizations.
    Provides timeline data, distributions, and advanced analytics.
    """
    return await asyncio.to_thread(statistics_service.get_detailed_statistics, timeRange)


@router.get("/summary")
@cache_stats
async def get_stats_summary():
    """Quick summary statistics.

    `get_stats_summary` derives six headline numbers from the *full* base
    aggregate — seven GROUP BYs plus a pass over every asset row's jsonb — so
    without the cache decorator its two siblings carry, this route cost 1.5-3.1 s
    per request and 20 concurrent requests took 38.6 s. It is also called by
    nothing in the frontend, so the cache costs one entry and removes a route
    that could stall the event loop on demand.
    """
    return await asyncio.to_thread(statistics_service.get_stats_summary)
