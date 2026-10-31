# One image, three worker modes — see remote_agent/README.md for the WORKER_MODE
# table.
#
# `model` and `tts` need only FastAPI and a filesystem. `llm` needs a GPU and a
# llama-server binary, because an LLM worker SERVES its own weights the way the
# Modal app does (`deployables/modal/llm/app.py` launches llama-server from the
# same `models.json`).
#
# Two runtimes from one file, selected by which base the final stage inherits:
#
#     docker build -f remote_agent/Dockerfile -t tnhfantasy-agent ..        # model/tts
#     docker build -f remote_agent/Dockerfile --build-arg CUDA=1 \
#         -t tnhfantasy-agent-llm ..                                        # llm
#
# `FROM ${CUDA_RUNTIME}` with `CUDA_RUNTIME` defaulting to a local stage name is
# the documented Docker form for choosing a base at build time. Two Dockerfiles
# would be the same content twice, and two copies of a build script is exactly
# what drifts.
#
# Why the split rather than one CUDA image for everything: a `model` agent on a
# GPU box does not want to carry a CUDA runtime it never uses, nor the GPU
# allocation it does not need. The Modal app makes the same split — its download
# image is deliberately slim while its server image is CUDA — for the same reason.

# Declared at file scope, before the first FROM: an ARG is only substitutable in
# a `FROM` when it is declared outside any build stage, and one declared inside a
# stage is blank at the point the next FROM resolves.
ARG CUDA_RUNTIME=runtime-slim

FROM python:3.13-slim AS runtime-slim

# Prebuilt llama.cpp server: no compile step, and the SAME image the Modal app
# uses, so the two transports run the same llama.cpp from the same GGUFs.
#
# The entrypoint is cleared, as the Modal app clears it: this container is started
# by the Dockerfile's CMD, not by the image's own. The tag floats — pin it once
# something works, so a rebuild cannot silently change llama.cpp versions under a
# working deployment.
FROM ghcr.io/ggml-org/llama.cpp:server-cuda AS runtime-llama
ENTRYPOINT []

# Which base the agent runs on. The default names the stage above; pass
# `--build-arg CUDA_RUNTIME=runtime-llama` (or `CUDA=1` via the wrapper below) for
# the llama.cpp runtime. An ARG as a FROM target must be resolvable between the
# stages, hence the two lines rather than one.
FROM ${CUDA_RUNTIME} AS runtime

WORKDIR /app

# Install runtime dependencies.
#
# On the llama.cpp base this needs apt, not pip: that image ships a Debian Python
# with no pip AND no `ensurepip` module (Debian splits it out), so each of the
# obvious spellings fails in its own way — `pip install` exits 127 with nothing
# useful in the log, and `python3 -m ensurepip` exits 1 with "No module named
# ensurepip". `apt-get install python3-pip` is the one thing that works.
#
# The `[ ${CUDA_RUNTIME} ]` guard is why this file has one install line instead of
# two: the slim base has pip already and would churn an apt layer for nothing.
# `--break-system-packages` is what Debian bookworm onwards requires for a
# deliberate system-wide install.
COPY remote_agent/requirements.txt /app/remote_agent/requirements.txt
RUN if [ "${CUDA_RUNTIME}" != "runtime-slim" ]; then \
        apt-get update -qq && apt-get install -y -qq --no-install-recommends \
            python3-pip && rm -rf /var/lib/apt/lists/*; \
    fi \
    && python3 -m pip install --no-cache-dir --break-system-packages \
        -r /app/remote_agent/requirements.txt

# Copy shared provider_core (NOT pip-installed — it is a local source package
# living under remote_agent/). It ships on PYTHONPATH so the agent can reuse
# the same download/validation/path-safety primitives.
COPY remote_agent/provider_core/ /app/provider_core/

# Copy the agent source.
COPY remote_agent/ /app/remote_agent/

# The model registry, from the SAME file the Modal app and the backend read. One
# file is the point: `backend_v2/modal_llm/registry.py` says both sides import it
# so a role's model cannot disagree between transports, and a second copy here
# would undo that. It lands at the path `llama_server.BUNDLED_REGISTRY` looks for.
COPY backend_v2/modal_llm/ /app/modal_llm/

# DATA_DIR is the STORAGE ROOT (mirroring Modal's /mnt/data), not a `models/`
# subdir. Provider storage paths look like "models/checkpoints/x.safetensors",
# "output/...", "input/...". For an LLM worker, `LLM_DATA_DIR` is read instead and
# the registry's weights land under `<root>/<model.volume_dir>/<gguf>`.
#
# provider_core lives at /app/provider_core and is imported as a package
# (from provider_core import ...), so only /app (its parent) belongs on
# PYTHONPATH. Putting /app/provider_core itself on the path would shadow the
# stdlib `logging` module with provider_core/logging.py.
ENV PYTHONPATH=/app:/app/remote_agent \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/remote_agent/data \
    PORT=8001

EXPOSE 8001

# The slim base has useradd; the llama.cpp base does not (it ships no `passwd`
# package), so that spelling exits 4 partway through and leaves the image with no
# agent user at all. Guarded, and the guard is the same one the pip line uses, so
# the branch condition lives in one place.
RUN if [ "${CUDA_RUNTIME}" != "runtime-slim" ]; then \
        echo 'llama base: ships no useradd; not running as a dedicated user'; \
    else \
        useradd --create-home --uid 1000 --shell /usr/sbin/nologin agent \
            && chown -R agent:agent /app; \
    fi
USER root

# /health is unauthenticated and answers {"status": "healthy"} (server.py) — the
# one route that answers before the token check, the token check being the thing
# most likely to be misconfigured.
#
# `$PORT`, not a literal. The app reads `os.getenv("PORT", "8001")` (server.py
# `__main__`), so an operator who set PORT to something else — or a compose file
# that does — would otherwise get a container whose healthcheck probed a port
# nothing listened on: reported unhealthy forever while the agent worked.
#
# Shell form, not exec form, so the CMD can expand the variable.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:%s/health' % os.environ.get('PORT', '8001'))"

CMD ["python", "/app/remote_agent/server.py"]
