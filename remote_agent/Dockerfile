FROM python:3.13-slim

WORKDIR /app

# Install runtime dependencies.
COPY remote_agent/requirements.txt /app/remote_agent/requirements.txt
RUN pip install --no-cache-dir -r /app/remote_agent/requirements.txt

# Copy shared provider_core (NOT pip-installed — it is a local source package,
# exactly like the worker image). It ships on PYTHONPATH so the agent can reuse
# the same download/validation/path-safety primitives.
COPY provider_containers/provider_core/ /app/provider_core/

# Copy the agent source.
COPY remote_agent/ /app/remote_agent/

# DATA_DIR should be a bind-mount to the ComfyUI models directory on the host
# (e.g. -v /opt/comfy/ComfyUI/models:/app/remote_agent/models:ro with a
# writable /downloads subdir). It is the single storage root the agent manages.
# provider_core lives at /app/provider_core and is imported as a package
# (from provider_core import ...), so only /app (its parent) belongs on
# PYTHONPATH. Putting /app/provider_core itself on the path would shadow the
# stdlib `logging` module with provider_core/logging.py.
# DATA_DIR is the STORAGE ROOT (mirroring Modal's /mnt/data), not ComfyUI's
# `models/` subdir. Provider storage paths look like "models/checkpoints/x.safetensors",
# "output/...", "input/...". Mount the ComfyUI repo root here, read-write, with
# `output`/`downloads` writable (the GPU rig user must be able to write).
ENV PYTHONPATH=/app:/app/remote_agent \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/remote_agent/data \
    PORT=8001

EXPOSE 8001

CMD ["python", "/app/remote_agent/server.py"]
