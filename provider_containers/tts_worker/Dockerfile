# Dockerfile for the TTS Worker
# Build context: provider_containers/
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

# Unprivileged user matching the host UID, as the other two workers do: the
# deploy step reads the mounted source and the deploy runs as this user.
RUN useradd -r -u 1000 -s /bin/false worker && \
    chown -R worker:worker /app

USER worker

ENV ENGINE=modal
ENV MODAL_TTS_APP_NAME=comfy-modal-tts

EXPOSE 8000

# Not a serving container — it exists to run one `modal deploy` and exit. The
# orchestrator overrides the command with `sleep <n>`, so there is no CMD here on
# purpose: a stray CMD would be a foot-gun for anyone running the image directly.
