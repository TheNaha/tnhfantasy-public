import time
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response as FastAPIResponse

from api.error_handlers import register_exception_handlers
from api.routes import (
    collections,
    files,
    gallery,
    generation,
    health,
    jobs,
    models,
    models_external,
    nodes,
    prompts,
    providers,
    statistics,
    worker_ws,
    world_vault,
)
from api.routes import settings as settings_routes
from api.routes.websocket import socket_app
from config import get_cors_origins, get_gzip_minimum_size
from infrastructure.logging import api_logger
from infrastructure.metrics import metrics


def configure_app(app: FastAPI):
    cors_origins = get_cors_origins()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials="*" not in cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        # Export responses report skipped files through these headers; without
        # exposing them a cross-origin UI cannot tell a partial download apart
        # from a complete one.
        expose_headers=["X-Missing-Count", "X-Missing-Files", "Content-Disposition"],
    )

    app.add_middleware(
        GZipMiddleware,
        minimum_size=get_gzip_minimum_size(),
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Fix redirect Location headers that use internal hostnames (e.g. localhost:8002)
        # which are unreachable from the browser. Convert to relative paths.
        if response.status_code in (301, 302, 307, 308):
            location = response.headers.get("location", "")
            if location and "://" in location:
                parsed = urlparse(location)
                if parsed.path:
                    response.headers["location"] = parsed.path
        return response

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log all HTTP requests with timing and request ID for tracing."""
        request_id = str(uuid4())[:8]
        start_time = time.time()

        response = await call_next(request)

        duration_seconds = time.time() - start_time
        duration_ms = round(duration_seconds * 1000, 2)
        path = request.url.path
        # `/api/live`, `/api/ready`, and `/metrics` are probed on tight
        # intervals by the orchestrator/load balancer. Logging every probe
        # drowns out real request traffic with 200 OK noise.
        skip_paths = ["/api/live", "/api/ready", "/metrics"]

        if not any(path.startswith(skip) for skip in skip_paths):
            route = request.scope.get("route")
            metric_path = getattr(route, "path", None) or "unmatched"
            log = api_logger()
            log.info(
                "http_request",
                request_id=request_id,
                method=request.method,
                path=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            metrics.track_request(request.method, metric_path, response.status_code, duration_seconds)

        response.headers["X-Request-ID"] = request_id
        return response

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(providers.router)
    app.include_router(files.router)
    app.include_router(settings_routes.router)
    app.include_router(statistics.router)
    app.include_router(generation.router)
    app.include_router(models_external.router)
    app.include_router(models.router)
    app.include_router(prompts.router)
    app.include_router(collections.router)
    app.include_router(nodes.router)
    app.include_router(worker_ws.router)
    app.include_router(world_vault.router)
    # The gallery routes (asset tagging, image sessions) used to be mounted
    # from `world_vault`, where they were neither about the World Vault nor
    # anywhere near the other 24% of that package they sat beside. The URLs
    # are unchanged: `/api/v2/sessions`, `/api/v2/asset/{id}/tags`,
    # `/api/v2/tags`, `/api/v2/assets/auto-tag`, `/api/v2/assets/facet`.
    app.include_router(gallery.router)

    app.mount("/socket.io", socket_app)

    @app.get("/")
    async def root():
        return {"message": "ComfyUI Modal Stack Backend V2", "version": "2.0.0"}

    @app.get("/metrics")
    async def prometheus_metrics():
        """Expose Prometheus metrics for scraping."""
        return FastAPIResponse(
            content=metrics.generate_metrics(),
            media_type=metrics.get_content_type(),
        )