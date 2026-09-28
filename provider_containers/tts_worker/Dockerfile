# Dockerfile for the TTS Worker
# Build context: provider_containers/
#
# BOTH a provider container and a deploy container. Started normally it serves
# the provider (CMD below, `tts_worker.worker:app`); the deploy orchestrator
# overrides the command with `sleep <n>` and runs `modal deploy` inside it,
# which is how `POST /api/v2/providers/{id}/deploy` builds `comfy-modal-tts`.
# So the modal CLI has to be in the image, which is why it is installed here
# even though a running TTS worker never shells out.
#
# Same shape as image_worker/Dockerfile and llm_worker/Dockerfile, because
# `ProviderDeployOrchestrator.start_attempt_container` builds its deploy container
# with `dockerfile=f"{worker_kind}_worker/Dockerfile"` against this directory as
# the build context, and the deploy target then runs
# `modal deploy /app/tts_worker/engines/modal/modal_app.py` inside it. A new
# worker kind is therefore "a directory with this file in it" — no change to the
# orchestrator, no new provider type, no new credentials.
#
# What is deliberately absent versus image_worker: beta9 (unused for the Modal
# TTS app), and nothing image-related at all. The ComfyUI image and its TTS node
# pack are built by Modal itself inside `modal_app.py`; this image only has to
# carry the CLI, the app source, and enough runtime to drive a Modal deploy.

FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    modal \
    fastapi \
    uvicorn \
    httpx \
    websockets \
    aiofiles \
    tenacity \
    requests \
 && ln -sf /usr/local/bin/beta9 /usr/local/bin/beam

# Shared utilities. `modal_app.py` imports `provider_core` for nothing today,
# but the FileStorage helpers and the retryable-payload shapes live there and
# the TTS client is expected to converge on them, so shipping it now avoids a
# second image build later.
COPY provider_core/ /app/provider_core/

# TTS worker source
COPY tts_worker/ /app/tts_worker/

# Unprivileged user matching the host UID, so the shared volume is writable. The
# worker reads `/mnt/data/models` for the TTS model; it writes nothing else.
RUN useradd -r -u 1000 -s /bin/false worker && \
    chown -R worker:worker /app

USER worker

# Set by the compose service. Read at module import, so a bare `ENGINE=` would
# raise before uvicorn binds — hence the `.strip()` + fallback in worker.py.
ENV ENGINE=modal
ENV MODAL_TTS_APP_NAME=comfy-modal-tts
# The Modal app, not the image one. Deployed by
# `POST /api/v2/providers/{id}/deploy` on THIS provider row, so the image
# provider's deploy target no longer builds it.
ENV MODAL_TTS_TIMEOUT=1800

# $PORT is the single source of truth for the listen port, and BOTH the healthcheck
# and the CMD read it. `image_worker/Dockerfile` learned that the hard way: its
# CMD hardcoded 8000 while its healthcheck read $PORT, so a provider on another
# port bound 8000 and probed 8001 and was permanently UNHEALTHY.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:%s/live' % os.environ.get('PORT', '8000'))"

# Shell form, not exec form, so the CMD can read $PORT — exec form cannot expand
# it, which is how the two disagreed in the first place.
CMD python -m uvicorn tts_worker.worker:app --host 0.0.0.0 --port ${PORT:-8000}
