# Dockerfile for Image Worker
# Supports Modal, Beam, and Direct URL engines via ENGINE env var.
# Build context: provider_containers/

FROM python:3.13-slim

WORKDIR /app

# Install dependencies for all engines
RUN pip install --no-cache-dir \
    modal \
    beta9 \
    fastapi \
    uvicorn \
    httpx \
    aiohttp \
    websockets \
    python-multipart \
    aiofiles \
    tenacity \
    requests \
 && ln -sf /usr/local/bin/beta9 /usr/local/bin/beam

# Copy shared provider_core package
COPY provider_core/ /app/provider_core/

# Copy image_worker source
COPY image_worker/ /app/image_worker/

# Create unprivileged user matching host UID for shared volume access
RUN useradd -r -u 1000 -s /bin/false worker && \
    chown -R worker:worker /app

USER worker

# Set default engine, can be overridden at runtime
ENV ENGINE=modal

# Expose HTTP port
# $PORT is the single source of truth for the listen port. Compose sets it per
# service, so the healthcheck and the CMD both have to read it: the CMD
# hardcoded 8000 while the healthcheck read $PORT, which meant any provider on
# another port bound 8000 and probed 8001 and was permanently UNHEALTHY.
ENV PORT=8000
EXPOSE 8000

# Health check
# /live, not /health: this reports whether the worker process is serving, so an
# unreachable third-party ComfyUI does not turn a perfectly healthy worker
# container red (and cascade out of anything that depends_on it). The upstream
# signal is on /health, which the backend's dispatcher reads.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:%s/live' % os.environ.get('PORT', '8000'))"

# Run worker HTTP server. Shell form, not exec form, so the CMD can read $PORT —
# exec form cannot expand it, and that is exactly how the two disagreed.
CMD python -m uvicorn image_worker.worker:app --host 0.0.0.0 --port ${PORT:-8000}
