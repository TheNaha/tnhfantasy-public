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
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run worker HTTP server
CMD ["python", "-m", "uvicorn", "image_worker.worker:app", "--host", "0.0.0.0", "--port", "8000"]
