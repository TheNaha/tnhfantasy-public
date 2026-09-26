FROM python:3.13-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    httpx \
    aiohttp \
    websockets \
    pydantic \
    requests \
    aiofiles \
    tenacity \
    modal

# Copy provider_core shared library
COPY provider_core/ /app/provider_core/

# Copy the LLM worker code
COPY llm_worker/ /app/llm_worker/

# Same unprivileged user as image_worker, and for the same reason this image
# matters more than that one: compose's `user: "1000:1000"` is the only thing
# that was keeping this image off root, and this image is the one whose /deploy
# shells out to `modal deploy` (llm_worker/engines/modal/client.py). A root
# worker writing to a bind-mounted ./data and spawning a deploy subprocess is a
# much worse failure than a permission error.
RUN useradd -r -u 1000 -s /bin/false worker && \
    chown -R worker:worker /app

USER worker

# Health check. /live, not /health, and $PORT, not a literal 8000 — see
# image_worker/Dockerfile for why both matter.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:%s/live' % os.environ.get('PORT', '8000'))"

# Run the unified worker app
CMD ["python", "-m", "uvicorn", "llm_worker.worker:app", "--host", "0.0.0.0", "--port", "8000"]
