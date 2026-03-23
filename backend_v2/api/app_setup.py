import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response as FastAPIResponse

from api.error_handlers import register_exception_handlers
from api.routes import jobs, providers, health, files, downloads, settings as settings_routes, statistics, generation
from api.routes import models_v2, prompts, collections
from api.routes import worker_ws, kaggle
from api.routes.websocket import socket_app
from config import settings, get_cors_origins
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
    )

    app.add_middleware(
        GZipMiddleware,
        minimum_size=settings.gzip_minimum_size,
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log all HTTP requests with timing and request ID for tracing."""
        request_id = str(uuid4())[:8]
        start_time = time.time()

        response = await call_next(request)

        duration_seconds = time.time() - start_time
        duration_ms = round(duration_seconds * 1000, 2)
        path = request.url.path
        skip_paths = ["/health", "/api/files/events", "/metrics"]

        if not any(path.startswith(skip) for skip in skip_paths):
            log = api_logger()
            log.info(
                "http_request",
                request_id=request_id,
                method=request.method,
                path=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            metrics.track_request(request.method, path, response.status_code, duration_seconds)

        response.headers["X-Request-ID"] = request_id
        return response

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(providers.router)
    app.include_router(files.router)
    app.include_router(downloads.router)
    app.include_router(settings_routes.router)
    app.include_router(statistics.router)
    app.include_router(generation.router)
    app.include_router(models_v2.router)
    app.include_router(prompts.router)
    app.include_router(collections.router)
    app.include_router(worker_ws.router)
    app.include_router(kaggle.router)

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