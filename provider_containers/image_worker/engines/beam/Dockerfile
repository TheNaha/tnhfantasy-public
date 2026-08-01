# Dockerfile for Beam Provider Worker
# This container runs isolated Beam SDK calls with its own credentials
# Build context: provider_containers/ (to access shared provider_core package)

FROM python:3.13-slim

WORKDIR /app

# Install Beam SDK and FastAPI for HTTP server
RUN pip install --no-cache-dir \
    beta9 \
    fastapi \
    uvicorn \
    aiohttp \
    python-multipart \
    httpx \
    websockets \
    aiofiles \
    tenacity \
    requests \
 && ln -sf /usr/local/bin/beta9 /usr/local/bin/beam

# Copy shared provider_core package (available since build context is provider_containers/)
COPY provider_core/ /app/provider_core/

# Copy worker script
COPY beam_worker/worker.py .

# Copy client script
COPY beam_worker/client.py .

# Copy beam_app.py for deployment
COPY beam_worker/beam_app.py .

# Create unprivileged user matching host UID for shared volume access
RUN useradd -r -u 1000 -s /bin/false worker && \
    chown -R worker:worker /app

USER worker

# Expose HTTP port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run worker HTTP server
CMD ["uvicorn", "worker:app", "--host", "0.0.0.0", "--port", "8000"]
