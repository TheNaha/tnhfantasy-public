FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create unprivileged user
RUN useradd -r -u 1000 -s /bin/false comfy && \
    mkdir -p /data/db /data/input /data/output /data/hf-cache /data/cache && \
    chown -R comfy:comfy /app /data

USER comfy
# Expose port
EXPOSE 8002

# Run without reload by default to avoid extra watcher/child-process memory.
# Set COMFY_UVICORN_RELOAD=1 (or true) to re-enable reload when needed.
#
# The reload watcher covers all of /app, which in dev is a bind mount of the
# whole backend_v2 tree. So editing a test, a one-off script, or a helper copy
# used to tear the whole application down and bring it back up: WebSocket
# connections dropped, the job queue and scheduler stopped, background tasks
# cancelled. That is a full shutdown for a change that cannot affect the
# running app, which makes editing tests actively hostile.
#
# The excludes below cover trees the app never imports at runtime:
#   tests/                  the suite (nothing in api/core/services imports it)
#   scripts/                one-off CLIs; not even a package (no __init__.py)
#   memory_snapshot_helper/ a byte-identical copy that only the Modal image
#                           consumes; the backend copy is test-only
# Patterns are matched by uvicorn with pathlib.Path.match, which matches a
# relative pattern from the right, so '**/tests/**' hits /app/tests/** at any
# depth while leaving api/, core/, services/ and infrastructure/ watched.
# Only *.py can trigger a reload, so non-Python caches (.pytest_cache,
# .ruff_cache) never caused a restart and are deliberately not listed.
CMD ["sh", "-c", "if [ \"${COMFY_UVICORN_RELOAD:-0}\" = \"1\" ] || [ \"${COMFY_UVICORN_RELOAD:-false}\" = \"true\" ]; then exec uvicorn api.main:app --host 0.0.0.0 --port 8002 --reload --reload-exclude '**/tests/**' --reload-exclude '**/scripts/**' --reload-exclude '**/memory_snapshot_helper/**'; else exec uvicorn api.main:app --host 0.0.0.0 --port 8002; fi"]
