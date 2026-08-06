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
    tenacity

# Copy provider_core shared library
COPY provider_core/ /app/provider_core/

# Copy the LLM worker code
COPY llm_worker/ /app/llm_worker/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run the unified worker app
CMD ["python", "-m", "uvicorn", "llm_worker.worker:app", "--host", "0.0.0.0", "--port", "8000"]
