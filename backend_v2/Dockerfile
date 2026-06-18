FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create unprivileged user
RUN useradd -r -s /bin/false comfy && \
    mkdir -p /data/db /data/input /data/output && \
    chown -R comfy:comfy /app /data

USER comfy
# Expose port
EXPOSE 8002

# Run without reload by default to avoid extra watcher/child-process memory.
# Set COMFY_UVICORN_RELOAD=1 (or true) to re-enable reload when needed.
CMD ["sh", "-c", "if [ \"${COMFY_UVICORN_RELOAD:-0}\" = \"1\" ] || [ \"${COMFY_UVICORN_RELOAD:-false}\" = \"true\" ]; then exec uvicorn api.main:app --host 0.0.0.0 --port 8002 --reload; else exec uvicorn api.main:app --host 0.0.0.0 --port 8002; fi"]
