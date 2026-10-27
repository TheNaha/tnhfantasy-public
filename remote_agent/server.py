import os
import asyncio
import atexit
import base64
import json
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from provider_core.auth import bearer_from_header, token_matches
from provider_core.http_client import get_file_size_cap
from provider_core.responses import failed, from_upstream, ok
from provider_core.utils import (
    determine_download_token,
    get_safe_path,
    is_model_candidate,
    is_transient_artifact,
)
from provider_core.downloads import (
    download_model_to_path,
    pending_download_paths,
    pipeline_artifacts,
)
from provider_core.validation import MIN_MODEL_SIZE, validate_downloaded_file
from provider_core.models import MODEL_DIRECTORIES
from provider_core.logging import get_logger

logger = get_logger("server")

app = FastAPI(title="TNHComfy Remote Agent")


@app.middleware("http")
async def log_incoming_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 1)
    if request.url.path not in ("/health",):
        logger.info(
            f"--> {request.method} {request.url.path} "
            f"status={response.status_code} ({duration_ms}ms)"
        )
    return response


TOKEN = os.getenv("REMOTE_AGENT_TOKEN", "").strip()
ALLOW_INSECURE = os.getenv("REMOTE_AGENT_ALLOW_INSECURE", "").lower() in {"1", "true", "yes"}
if not TOKEN and not ALLOW_INSECURE:
    raise RuntimeError("REMOTE_AGENT_TOKEN must be set unless REMOTE_AGENT_ALLOW_INSECURE=1")
HF_TOKEN = os.getenv("HF_TOKEN", "")
CIVITAI_TOKEN = os.getenv("CIVITAI_TOKEN", "")

try:
    DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "1800"))
except ValueError:
    logger.warning("DOWNLOAD_TIMEOUT is not an integer; falling back to 1800")
    DOWNLOAD_TIMEOUT = 1800

# The default bind was 0.0.0.0 (here, agentctl.sh:71, and
# remote_agent/docker-compose.yml publishing 8001 on all interfaces), and
# REMOTE_AGENT_ALLOW_INSECURE makes `verify_token` return True unconditionally —
# so the flag did not just "skip auth on a dev box", it opened
# /delete-model, /delete-file, /upload-file and /download-model to anyone who
# could route to the port, with write access to the ComfyUI models mount. The flag
# still works exactly as documented (local dev, single user, loopback); it just
# refuses to be a remote write API by default.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _resolve_bind_host() -> str:
    """Clamp the insecure bind to loopback unless the operator already chose it.

    Deliberately no "unless they set HOST explicitly" escape: the default was
    0.0.0.0 in three places (here, `agentctl.sh:71`, and the compose that publishes
    8001 on all interfaces), so an explicit-looking HOST is usually just the
    default being echoed back. An operator who genuinely needs the agent reachable
    from another machine sets REMOTE_AGENT_TOKEN; there is no reason to hand out
    an unauthenticated *writer* to get that.

    `os.getenv("HOST", "0.0.0.0")` was not enough on its own. `agentctl.sh` does
    `export HOST="${HOST-}"`, which exports an **empty** HOST when the operator
    set none — so the variable was always set, the default never applied, and the
    empty string reached uvicorn, which binds `""` as INADDR_ANY. The result was
    the exact thing the clamp exists to prevent: `REMOTE_AGENT_ALLOW_INSECURE=1`
    plus no HOST gave an unauthenticated writer on 0.0.0.0:8001. Empty is now
    treated as unset, and `""` is no longer in the loopback set, because an empty
    bind address is a wildcard and not a loopback.
    """
    host = (os.getenv("HOST") or "0.0.0.0").strip()
    if not ALLOW_INSECURE or host in _LOOPBACK_HOSTS:
        return host
    return "127.0.0.1"


def _warn_insecure_bind() -> None:
    if not ALLOW_INSECURE:
        return
    requested = os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0"
    logger.warning(
        "REMOTE_AGENT_ALLOW_INSECURE is set. The agent has NO authentication: "
        "/delete-model, /delete-file, /upload-file and /download-model will accept "
        "any caller that can reach it, and the storage root is read-write. "
        f"HOST={requested!r} -> binding {_resolve_bind_host()!r}. "
        "Set REMOTE_AGENT_TOKEN to open it up; this flag is for local dev only."
    )

# Concurrent /setup seeds. Below the 8 default seed URLs, and well below the
# default executor's worker count, so a rig where several model hosts are slow
# cannot occupy every thread the single-process agent has.
SEED_MAX_CONCURRENT = int(os.getenv("REMOTE_AGENT_SEED_MAX_CONCURRENT", "3"))

# Ceiling on every `asyncio.to_thread` in this file.
#
# `asyncio.to_thread` uses the default executor, whose worker count is bounded
# (and is NOT SEED_MAX_CONCURRENT — that semaphore only covered /setup). So the
# 16 unbounded fan-out of /validate-models, plus a /get-file walk, plus a
# download, could occupy every thread the single-process agent has and queue
# everything else behind it — which is the same failure /setup already had and
# already fixed. Sized like the default executor's worker count rather than
# smaller: the point is not to make the work smaller, it is to stop an unbounded
# number of *pending* work items from ever reaching the executor.
THREAD_MAX_CONCURRENT = int(os.getenv("REMOTE_AGENT_THREAD_MAX_CONCURRENT", "32"))
_thread_semaphore: Optional[asyncio.Semaphore] = None

# Concurrent /download-model requests. Defaults to 1 to protect remote network mounts
# (e.g. Google Drive FUSE on Google Colab) from concurrent write saturation and
# transport disconnects (Errno 107).
DOWNLOAD_MAX_CONCURRENT = int(os.getenv("REMOTE_AGENT_DOWNLOAD_MAX_CONCURRENT", "1"))
_download_semaphore: Optional[asyncio.Semaphore] = None


def _get_download_semaphore() -> asyncio.Semaphore:
    global _download_semaphore
    if _download_semaphore is None:
        _download_semaphore = asyncio.Semaphore(DOWNLOAD_MAX_CONCURRENT)
    return _download_semaphore

# Deadline on a single off-thread call.
#
# `_bounded_to_thread` bounded *concurrency* but not *time*: a thread whose peer
# never answers held its slot, and eventually every one of the 32, so the
# single-process agent stopped answering anything at all — with no error, because
# nothing raised. It has no natural upper bound per call site, so the default is
# derived from the one parameter that does: `DOWNLOAD_TIMEOUT` is the per-request
# HTTP budget for a model transfer, and a download is the longest thing this file
# legitimately does. Six minutes of slack covers retries, the preview fetch and a
# slow `rmtree` on a network volume. `REMOTE_AGENT_THREAD_TIMEOUT_SECONDS=0`
# disables the deadline.
#
# A timed-out thread is NOT reclaimed, and cannot be: `asyncio.to_thread` has no
# way to interrupt a running function, and no Python-level API can. So the gate is
# released and the thread is left to finish on its own, which means the deadline
# bounds how long a *caller* waits, not how long a thread lives. That is the part
# worth having — the agent answers other requests again — and it is logged rather
# than swallowed, because an abandoned thread is a thread the pool no longer knows
# about.
THREAD_CALL_TIMEOUT_SECONDS = int(
    os.getenv("REMOTE_AGENT_THREAD_TIMEOUT_SECONDS", str(DOWNLOAD_TIMEOUT + 600))
)


class ThreadCallTimeout(RuntimeError):
    """An off-thread call exceeded `THREAD_CALL_TIMEOUT_SECONDS`."""


async def _bounded_to_thread(fn, /, *args, timeout_seconds: Optional[float] = None, **kwargs):
    """`asyncio.to_thread` behind a process-wide admission gate, with a deadline.

    The gate is taken around the `await`, not inside the thread body: holding it
    in the body would bound nothing, because the coroutine has already handed the
    work to the executor by then (the same reasoning the seed semaphore above
    documents).

    `timeout_seconds` is consumed here rather than forwarded — every call site in
    this file passes plain positional/keyword arguments to the wrapped function,
    and a keyword of this name reaching user code would be a silent bug.

    The semaphore is created lazily rather than at import, because an
    `asyncio.Semaphore` binds to the loop that is running when it is first
    awaited, and this module is imported before uvicorn has a loop.
    """
    global _thread_semaphore
    if _thread_semaphore is None:
        _thread_semaphore = asyncio.Semaphore(THREAD_MAX_CONCURRENT)
    limit = THREAD_CALL_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    async with _thread_semaphore:
        work = asyncio.to_thread(fn, *args, **kwargs)
        if not limit or limit <= 0:
            return await work
        try:
            return await asyncio.wait_for(work, timeout=limit)
        except asyncio.TimeoutError as exc:
            logger.warning(
                f"[thread] {getattr(fn, '__name__', fn)!r} exceeded {limit}s; "
                f"the thread cannot be cancelled and will finish on its own, but "
                f"this caller stops waiting"
            )
            raise ThreadCallTimeout(
                f"off-thread call {getattr(fn, '__name__', fn)!r} did not finish "
                f"within {limit}s"
            ) from exc


# Ceiling on one /upload-file body, in decoded bytes. 512 MiB is generous for the
# route's real traffic (input images, masks) and still finite. The JSON field is
# checked at the encoded length (4/3 of this plus slack for the rest of the
# document), because that is what Pydantic has in hand.
try:
    UPLOAD_MAX_BYTES = int(os.getenv("REMOTE_AGENT_UPLOAD_MAX_BYTES", str(512 * 1024 * 1024)))
except (TypeError, ValueError):
    logger.warning("REMOTE_AGENT_UPLOAD_MAX_BYTES is not an integer; falling back to 512 MiB")
    UPLOAD_MAX_BYTES = 512 * 1024 * 1024
UPLOAD_MAX_BYTES_ENCODED = (UPLOAD_MAX_BYTES // 3) * 4 + 4096


_SIDECAR_EXTENSIONS = (".json", ".preview.png", ".sha256", ".downloading", ".lock")
# Deliberately NOT provider_core.utils.SIDECAR_SUFFIXES. The shared tuple also
# excludes .txt/.yaml/.yml, which are reported as models here; narrowing it would
# silently stop listing files an operator can see in the directory. The
# pipeline-owned suffixes are NOT duplicated in that tuple on purpose: they come
# from is_transient_artifact, which is the single source of truth for them.


def _ensure_data_dir() -> str:
    os.makedirs(DATA_ROOT, exist_ok=True)
    return DATA_ROOT


async def verify_token(request: Request):
    if TOKEN:
        auth_header = request.headers.get("Authorization")
        provided = bearer_from_header(auth_header)
        # `token_matches`, not a hand-rolled `hmac.compare_digest(provided, TOKEN)`
        # here. `compare_digest` raises `TypeError` on a `str` holding a byte
        # >= 0x80 and Starlette decodes header bytes as latin-1, so one non-ASCII
        # character in `Authorization` raised INSIDE this dependency: an unmapped
        # 500 the caller retried three times, for what is plainly a wrong
        # credential. This file is the sixth copy of the check and the only one
        # outside `provider_core`, which is why the unification missed it.
        # `provider_core/auth.py` documents the bug and is the one comparison.
        if not token_matches(provided, TOKEN):
            raise HTTPException(status_code=401, detail="Unauthorized")
    return True


class DownloadRequest(BaseModel):
    # Optional, not required: `model_id` is a whole second entrypoint into this
    # route, and a required `url`/`path` beside it makes the registry path
    # unusable — FastAPI rejects the body before the handler runs, so the caller
    # sees a validation error naming fields it deliberately did not send. The
    # handler below is what decides which of the two is meaningful.
    url: str = ""
    path: str = ""
    token: Optional[str] = None
    preview_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    info: Optional[Dict[str, Any]] = None
    #: A registry model id, for an LLM worker fetching its own weights.
    #: Mutually exclusive with `url`; when given, the repo and filename come from
    #: `models.json` rather than from the caller, so a typo cannot put a file where
    #: the launcher will not find it.
    model_id: Optional[str] = None
    # Whether to stage the downloaded model into the RAM cache.
    #
    # It was False, and no caller ever set it — so the cache was NEVER
    # populated in the Docker/Modal deployment. The RAM cache is the whole
    # reason ComfyUI, llama.cpp and Laya can share one 24 GB card: the
    # weights come from RAM instead of the volume, which is the difference
    # between a model that loads in ten seconds and one that loads in ten
    # minutes. With the cache never filled, every reload was a disk read
    # from a FUSE volume — the "long wait" complaint, with nothing in the
    # log to explain it.
    #
    # A caller that genuinely does not want the copy can still say so.
    prewarm: bool = True


class PrewarmModelSpec(BaseModel):
    id: Optional[str] = None
    source_path: str
    role: str = "general"
    is_anchor: bool = False


class PrewarmRequest(BaseModel):
    models: List[PrewarmModelSpec] = Field(default_factory=list)
    anchors: Optional[List[str]] = None
    max_spare_gb: Optional[float] = None


class EvictRequest(BaseModel):
    model_id: str
    force: bool = False


class ListModelsRequest(BaseModel):
    directory: str


class DeleteModelRequest(BaseModel):
    path: str


class UploadFileRequest(BaseModel):
    filename: str
    # Bounded in the model, not in the handler. `content_base64` is a JSON string
    # field, so FastAPI/Pydantic had already parsed the entire body into memory
    # before the first line of `upload_file` ran — `base64.b64decode` then made a
    # second copy. The limit is therefore on the *encoded* length, and the
    # Content-Length check below rejects the body before that parse happens at all.
    content_base64: str = Field(..., max_length=UPLOAD_MAX_BYTES_ENCODED)
    directory: str


class ValidateModelsRequest(BaseModel):
    directory: str | List[str]
    delete_invalid: bool = False
    fast: bool = True


class ValidateAllModelsRequest(BaseModel):
    delete_invalid: bool = False
    fast: bool = True


def _data_path(requested_path: str) -> str:
    try:
        return get_safe_path(DATA_ROOT, requested_path)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed directory")


def _is_sidecar(name: str) -> bool:
    return name.lower().endswith(_SIDECAR_EXTENSIONS)


# ---------------------------------------------------------------------------
# Worker-mode endpoints.
#
# The same image is deployed as a MODEL agent (default), an LLM worker, or a TTS
# worker, selected by `WORKER_MODE`. That is deliberate: the provider matrix's
# `remote` transport is "our own container, anywhere with Docker", and one image
# that can be three things is one image to build, ship and run on a GPU box —
# not three. Everything unrelated is already here (bearer auth, /get-file,
# /delete-file), so the mode only decides which pair of inference routes answers.
# ---------------------------------------------------------------------------

WORKER_MODE = os.getenv("WORKER_MODE", "model").strip().lower()
WORKER_MODES = ("model", "llm", "tts", "hybrid", "storage")

if WORKER_MODE not in WORKER_MODES:
    raise RuntimeError(
        f"WORKER_MODE must be one of {WORKER_MODES}, got {WORKER_MODE!r}"
    )

# The storage root for the mode this container runs in.
#
# The three modes want different trees, and the difference is not hypothetical:
# an image worker exposes its ComfyUI repo root — which holds `models/`,
# `output/`, `input/` and nothing else of interest — an LLM worker wants a plain
# weights directory with no ComfyUI structure in it at all, and a TTS worker is
# usually back on a ComfyUI rig because it shares one.
#
# One variable per mode, falling back to `DATA_DIR`, so the mapping is explicit
# at the point of deployment rather than being a shared root someone has to
# reason about. The keys mirror `WORKER_MODES` exactly, so an unknown mode has
# already raised before any path is resolved.
MODE_DATA_ENV = {
    "model": "DATA_DIR",
    "llm": "LLM_DATA_DIR",
    "tts": "TTS_DATA_DIR",
    "hybrid": "DATA_DIR",
    "storage": "DATA_DIR",
}

#: The storage root for THIS worker mode. `MODEL_DIRECTORIES` and every provider
#: path — `models/checkpoints/x.safetensors`, `output/...`, `input/...` — are
#: resolved against it, so setting `LLM_DATA_DIR=/models` on an LLM worker means
#: `models/` is `/models/models` and the ComfyUI root can stay what it is.
DATA_ROOT_ENV = MODE_DATA_ENV[WORKER_MODE]


def _resolve_data_root() -> str:
    """The root for the mode this container runs in, falling back to `DATA_DIR`.

    One `os.getenv` per mode, spelled out, rather than
    `os.getenv(MODE_DATA_ENV[WORKER_MODE])`. The computed key resolves the same
    value, but a dynamic key is invisible to the environment-variable guard that
    walks this tree (`test_env_contracts.py`), so any variable introduced later
    would be unreadable to it as well. Three literals cost three lines and keep
    every variable in this file findable.
    """
    if WORKER_MODE == "llm":
        own = os.getenv("LLM_DATA_DIR")
    elif WORKER_MODE == "tts":
        own = os.getenv("TTS_DATA_DIR")
    else:
        own = os.getenv("DATA_DIR")
    return own or os.getenv("DATA_DIR") or "./data"


DATA_ROOT = _resolve_data_root()

#: Where the actual model server lives, for `WORKER_MODE=llm` only.
#:
#: Declared at module level rather than inside the mode block because `/info`
#: needs it to describe the topology, and a value that describes the system
#: should not be scoped to the branch that happens to consume it.
#:
#: This is the second half of the parity question for a `remote_llm` provider. A
#: `modal_llm` provider serves from the SAME `models/` tree it manages; a
#: `remote_llm` one manages a root AND proxies to wherever this points, which
#: can be a different tree entirely. That is not a bug — fronting an existing
#: llama.cpp is the whole point — but it is invisible, and an operator looking
#: at a populated models tree would reasonably assume it is the one being served.
#: `/info` now reports both, so the assumption is checkable rather than
#: inherited.
UPSTREAM_BASE = (
    os.getenv("LLM_UPSTREAM_BASE", "http://127.0.0.1:8080/v1").rstrip("/")
)
UPSTREAM_OVERRIDE: str = ""
REGISTRY = None
REGISTRY_PATH = None
STACK = None


#: Where a synthesised clip is written under DATA_ROOT, and read back through
#: the existing `/get-file` route.
AUDIO_DIR = os.getenv("TTS_AUDIO_DIR", "audio").strip("/")


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice: Optional[str] = None
    speed: Optional[float] = None
    format: Optional[str] = None
    language: Optional[str] = None
    sample_rate: Optional[int] = None


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "worker_mode": WORKER_MODE,
        "inference_enabled": WORKER_MODE != "storage",
        "ready_for": [] if WORKER_MODE == "storage" else (["image", "llm", "tts"] if WORKER_MODE == "hybrid" else [WORKER_MODE]),
    }


def _detect_gpu() -> dict:
    """Query GPU device info and total VRAM via PyTorch or nvidia-smi."""
    try:
        import torch
        if torch.cuda.is_available():
            count = torch.cuda.device_count()
            name = torch.cuda.get_device_name(0)
            total_bytes = torch.cuda.get_device_properties(0).total_memory
            devices = [
                {
                    "index": i,
                    "name": torch.cuda.get_device_name(i),
                    "vram_total_mb": int(torch.cuda.get_device_properties(i).total_memory / (1024 * 1024)),
                }
                for i in range(count)
            ]
            return {
                "available": True,
                "name": name,
                "vram_total_mb": int(total_bytes / (1024 * 1024)),
                "count": count,
                "devices": devices,
            }
    except Exception:
        pass

    try:
        import subprocess
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        ).decode().strip()
        if out:
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            devices = []
            for l in lines:
                parts = [p.strip() for p in l.split(",")]
                idx = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else len(devices)
                d_name = parts[1] if len(parts) > 1 else "GPU"
                v_mb = int(parts[2]) if len(parts) > 2 else 0
                devices.append({"index": idx, "name": d_name, "vram_total_mb": v_mb})
            primary = devices[0] if devices else {"name": "GPU", "vram_total_mb": 0}
            return {
                "available": True,
                "name": primary["name"],
                "vram_total_mb": primary["vram_total_mb"],
                "count": len(devices),
                "devices": devices,
            }
    except Exception:
        pass

    return {"available": False, "name": "None", "vram_total_mb": 0, "count": 0, "devices": []}


def _topology() -> dict:
    """Where this container reads, writes and serves—the whole picture.

    An LLM worker manages a storage root AND proxies inference to
    `LLM_UPSTREAM_BASE`, and those are two independent settings that can point at
    two different trees. `modal_llm` has no such split—its app serves
    from the volume it manages—so a `remote_llm` provider is where an
    operator can reasonably believe the models tree they see is the one being
    served, and be wrong.

    `upstream_is_local` is the operator-visible half of the signal: a loopback
    upstream is almost certainly a server on this box reading a nearby path,
    while a remote one is certainly a different machine with its own storage.
    Reporting it makes the topology checkable instead of inferred.

    `storage_root` is the real resolved path, which the backend cannot see—it
    only ever had the variable name.
    """
    from urllib.parse import urlparse

    try:
        from vram_manager import get_vram_manager
        vram_info = get_vram_manager().get_vram_info()
    except Exception:
        vram_info = {}

    info: dict = {
        "worker_mode": WORKER_MODE,
        "storage_root": os.path.abspath(DATA_ROOT),
        "storage_root_env": DATA_ROOT_ENV,
        "inference_enabled": WORKER_MODE != "storage",
        "gpu": _detect_gpu(),
        "vram": vram_info,
    }
    if WORKER_MODE in ("llm", "hybrid"):
        info["llm_serving"] = "upstream" if UPSTREAM_OVERRIDE else "local"
        if UPSTREAM_OVERRIDE:
            host = (urlparse(UPSTREAM_OVERRIDE).hostname or "").lower()
            info["llm_upstream_base"] = UPSTREAM_OVERRIDE
            info["upstream_is_local"] = host in ("127.0.0.1", "localhost", "::1", "")
        else:
            # The managed root IS the served root, which is the parity claim. An
            # operator no longer has to assume it.
            info["llm_upstream_base"] = "this worker (llama-server, loopback)"
            info["upstream_is_local"] = True
    return info


@app.get("/info", dependencies=[Depends(verify_token)])
async def info():
    """Deployment topology: storage root, mode, and what llm mode serves.

    Authenticated, unlike `/health`, because it discloses paths. `/health` is the
    one route that answers before the token check precisely so a misconfigured
    token does not look like a dead container; `/info` has the opposite
    requirement.
    """
    payload = _topology()
    if WORKER_MODE in ("llm", "hybrid"):
        # Which models this container actually holds, per role, with the reason a
        # missing one is missing. `modal_llm` answers the same shape, so a caller
        # polling health sees an actionable state on either transport — and a role
        # whose weights were not downloaded reads `not_downloaded` rather than as
        # a crash-loop to infer from retries.
        llm_health = {}
        if REGISTRY is not None and STACK is not None:
            llm_health = STACK.health(REGISTRY)
            llm_health["registry"] = str(REGISTRY_PATH) if REGISTRY_PATH else None
        payload["llm"] = {
            **llm_health,
            "serving": "local" if not UPSTREAM_OVERRIDE else "upstream",
            "upstream": UPSTREAM_OVERRIDE or None,
        }
    return payload


@app.post("/setup", dependencies=[Depends(verify_token)])
async def setup():
    _ensure_data_dir()
    # The first comprehension that used to sit here was dead: line 106 overwrote
    # it, and it would have produced "models/models/checkpoints" for any entry
    # that already carried the prefix. MODEL_DIRECTORIES are all "models/<kind>".
    directories = ["output", "input", "downloads"] + list(MODEL_DIRECTORIES)
    # Seed default upscaler + ADetailer models (mirrors Modal/Beam setup).
    default_models = [
        "https://huggingface.co/lokCX/4x-Ultrasharp/resolve/main/4x-UltraSharp.pth",
        "https://huggingface.co/uwg/upscaler/resolve/main/ESRGAN/4x_foolhardy_Remacri.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8n.pt",
        "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8s.pt",
        "https://huggingface.co/Bingsu/adetailer/resolve/main/hand_yolov8n.pt",
        "https://huggingface.co/Bingsu/adetailer/resolve/main/person_yolov8n-seg.pt",
    ]
    default_paths = [
        "models/upscale_models/4x-Ultrasharp.pth",
        "models/upscale_models/4x_foolhardy_Remacri.pth",
        "models/upscale_models/RealESRGAN_x4plus.pth",
        "models/upscale_models/RealESRGAN_x4plus_anime_6B.pth",
        "models/ultralytics/bbox/face_yolov8n.pt",
        "models/ultralytics/bbox/face_yolov8s.pt",
        "models/ultralytics/bbox/hand_yolov8n.pt",
        "models/ultralytics/seg/person_yolov8n-seg.pt",
    ]
    for d in directories:
        os.makedirs(os.path.join(DATA_ROOT, d), exist_ok=True)

    # Bounded, and with a real HTTP timeout.
    #
    # This used to `asyncio.gather` all 8 seeds with no semaphore and no
    # `request_timeout_seconds`. Both halves mattered: `asyncio.to_thread` uses
    # the default executor, whose worker count is bounded, so 8 stalled peers
    # pinned every thread in the process and every later `to_thread` — including
    # /validate-models and /get-file — queued behind them, stopping a
    # single-process agent outright. And with no HTTP timeout, one `requests.get`
    # that connected and then went quiet blocks its thread forever.
    seed_semaphore = asyncio.Semaphore(SEED_MAX_CONCURRENT)

    async def _seed(url: str, path: str):
        full_path = _data_path(path)
        if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
            return
        token = determine_download_token(url, HF_TOKEN, CIVITAI_TOKEN)

        def _do() -> None:
            download_model_to_path(
                url=url, full_path=full_path, path=path, token=token,
                hf_token=HF_TOKEN, civitai_token=CIVITAI_TOKEN,
                log=print, log_prefix="Setup",
                # Same value /download-model passes (below). A seed that cannot
                # finish inside it gives up instead of holding a thread open
                # indefinitely.
                request_timeout_seconds=DOWNLOAD_TIMEOUT,
            )

        # The semaphore wraps the `await`, not the `to_thread` body: holding it
        # here is what keeps the queued seeds in the coroutine rather than
        # occupying executor threads.
        async with seed_semaphore:
            try:
                await _bounded_to_thread(_do)
            except Exception as e:
                logger.warning(f"[setup] failed to seed {path}: {e}")

    await asyncio.gather(*[_seed(u, p) for u, p in zip(default_models, default_paths)])
    return ok("Setup complete", directories=directories)


def _registry_download_path(model) -> str:
    """The provider path a registry model's GGUFs land on.

    `<root>/<volume_dir>/<gguf>`, which is exactly what `Model.llama_args` points
    `-m` at — so a download that succeeds is a model that launches, with no second
    mapping to keep in step.
    """
    return f"{model.volume_dir}/{model.gguf}"


async def _download_registry_model(model_id: str):
    """Fetch one registry model's weights, on demand.

    The sidecar's `ensure_model`, and what makes "switch model in the UI" work
    without a rebuild: the caller names an id, the weights are pulled, and the
    container is recreated for the new model to load. Returns the same answer
    shape whether it fetched or not, so a second call is free and safe to drive
    from a button.
    """
    if WORKER_MODE not in ("llm", "hybrid") or REGISTRY is None:
        return {"ok": False, "model_id": model_id, "reason": "no_registry"}

    try:
        model = REGISTRY.get(model_id)
    except KeyError:
        return {
            "ok": False,
            "model_id": model_id,
            "reason": "not_in_registry",
            "known": sorted(REGISTRY.models),
        }

    if getattr(model, "engine_type", "gguf") == "system1_laya":
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            return {
                "ok": False,
                "model_id": model_id,
                "reason": "huggingface_hub_not_installed",
                "detail": str(exc),
            }
        target = os.path.join(DATA_ROOT, model.volume_dir)
        os.makedirs(target, exist_ok=True)
        print(f"[{model.id}] {model.repo} (System 1 Laya directory)", flush=True)
        snapshot_download(
            model.repo,
            local_dir=target,
            token=HF_TOKEN or None,
        )
        try:
            from ram_manager import get_ram_manager
            get_ram_manager().ensure_dir_in_ram(target, model_id=model_id, role="decisions", is_anchor=True)
        except Exception as exc:
            logger.warning(f"Could not prewarm Laya directory {model_id} into RAM: {exc}")
        return {"ok": True, "model_id": model_id, "fetched": [target]}

    # The projectors too: a vision model whose mmproj is missing launches and
    # then cannot read an image, which is worse than not launching.
    jobs = [(model.gguf, model.repo)]
    if model.mmproj:
        jobs.append((model.mmproj, model.mmproj_repo or model.repo))

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        # Lazy on purpose — the model and tts modes have no use for the HF
        # client — but a lazy import means a missing dependency surfaces as a
        # bare 500 "Internal Server Error", which names neither the package nor
        # the reason. Name it, and say what image it should be in.
        return {
            "ok": False,
            "model_id": model_id,
            "reason": "huggingface_hub_not_installed",
            "detail": f"{exc}; it is in remote_agent/requirements.txt, so this "
                      "image predates registry downloads — rebuild it",
        }

    fetched = []
    for filename, repo in jobs:
        target = os.path.join(DATA_ROOT, model.volume_dir)
        os.makedirs(target, exist_ok=True)
        print(f"[{model.id}] {repo} :: {filename}", flush=True)
        snapshot_download(
            repo,
            allow_patterns=[filename],
            local_dir=target,
            token=HF_TOKEN or None,
        )
        resolved = os.path.join(target, filename)
        if not os.path.isfile(resolved):
            # The download "succeeded" but the file is not there. That is the
            # glob-matched-nothing case, and reporting success here is how a model
            # becomes permanently un-startable with no error anywhere.
            return {
                "ok": False,
                "model_id": model_id,
                "reason": "download_left_nothing",
                "expected": filename,
            }
        fetched.append(resolved)
    try:
        from ram_manager import get_ram_manager
        mgr = get_ram_manager()
        for f in fetched:
            if f.endswith(".gguf"):
                # Off the event loop. `ensure_in_ram` copies the whole file,
                # and doing that inline stalls the worker for the duration —
                # including the `/health` probe the backend uses for provider
                # status, so a download would make the provider look dead.
                await _bounded_to_thread(
                    mgr.ensure_in_ram,
                    f,
                    model_id=model_id,
                    role=model.role,
                    is_anchor=(model_id in mgr.anchors),
                )
    except Exception as exc:
        logger.warning(f"Could not prewarm registry model {model_id} into RAM: {exc}")
    return {"ok": True, "model_id": model_id, "fetched": fetched}


@app.post("/download-model", dependencies=[Depends(verify_token)])
async def download_model(req: DownloadRequest):
    async with _get_download_semaphore():
        if req.model_id:
            # The registry path: name a model from models.json, and the repo and the
            # destination are both derived rather than supplied.
            return await _download_registry_model(req.model_id)

        full_path = _data_path(req.path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # download_model_to_path resolves HF/CivitAI tokens internally
        # (build_authenticated_download_request), writes a `.downloading` temp file,
        # validates the file (magic bytes / min size), then atomically renames —
        # matching the Modal/Beam storage function semantics.
        token = req.token or determine_download_token(req.url, HF_TOKEN, CIVITAI_TOKEN)

        progress_dir = os.path.join(DATA_ROOT, "downloads")
        os.makedirs(progress_dir, exist_ok=True)
        safe_name = os.path.basename(full_path)
        progress_file = os.path.join(progress_dir, f"{safe_name}.json")

        def progress_callback(payload: Dict[str, Any]):
            try:
                with open(progress_file, "w") as f:
                    json.dump(payload, f)
            except Exception as exc:
                logger.warning(f"progress_callback: could not write {progress_file}: {exc}")

        def _do():
            try:
                return download_model_to_path(
                    url=req.url, full_path=full_path, path=req.path,
                    token=token, hf_token=HF_TOKEN, civitai_token=CIVITAI_TOKEN,
                    preview_url=req.preview_url, metadata=req.metadata,
                    log=print, log_prefix="Download",
                    progress_callback=progress_callback,
                    request_timeout_seconds=DOWNLOAD_TIMEOUT,
                )
            except Exception as e:
                return failed(str(e))

        result = await _bounded_to_thread(_do)
        if os.path.exists(progress_file):
            try:
                os.remove(progress_file)
            except OSError as exc:
                logger.warning(f"could not remove progress file {progress_file}: {exc}")
        # `from_upstream`, not a bare pass-through: `download_model_to_path` answers
        # `{"status": "error", ...}` for a real failure, and forwarding that verbatim is
        # one of the dialects the shared response module exists to remove. A non-dict
        # return is a failure too, rather than an AttributeError three frames up.
        if not isinstance(result, dict):
            return failed("Download failed")
        if req.prewarm and WORKER_MODE != "storage" and result.get("status") in ("success", "exists", "ok"):
            try:
                from ram_manager import get_ram_manager
                mgr = get_ram_manager()
                # Off the event loop: this copies the whole file.
                await _bounded_to_thread(mgr.ensure_in_ram, full_path, model_id=safe_name)
            except Exception as exc:
                logger.warning(f"Could not prewarm model {safe_name} to RAM: {exc}")
        return from_upstream(result)


def _validate_dir(target_dir: str, delete_invalid: bool, fast: bool = True) -> Dict[str, Any]:
    empty = {
        "valid": [], "invalid": [], "partial": [], "indeterminate": [],
        "total_valid": 0, "total_invalid": 0, "total_partial": 0,
        "total_indeterminate": 0,
    }
    if not os.path.isdir(target_dir):
        return empty

    valid, invalid, partial, indeterminate = [], [], [], []
    entries = list(os.walk(target_dir, followlinks=True))
    for root, _, filenames in entries:
        for name in filenames:
            if name.startswith("."):
                continue
            if is_transient_artifact(name):
                # The shared predicate, so a new pipeline-owned suffix is picked up
                # here without a per-engine exclusion list that can drift. Both are
                # "partial": the per-attempt temp and the parked resume slot are a
                # download that has not finished, and a `.lock` is a 0-byte file
                # whose held flock is what makes the download safe.
                #
                # Reported, never deleted: reconciliation runs with delete_invalid
                # true, and removing an in-flight temp file leaves the writer with
                # a live descriptor whose os.replace then fails. The abandoned ones
                # are swept by /delete-model and /delete-file via
                # pending_download_paths, which is the only place that can tell an
                # in-flight attempt from a dead one.
                rel_path = os.path.relpath(os.path.join(root, name), DATA_ROOT).replace("\\", "/")
                try:
                    size = os.path.getsize(os.path.join(root, name))
                except OSError:
                    # Unguarded here, guarded in both Modal validators since
                    # 2026-09-29. A stat that fails is not a verdict on the file,
                    # and it is walked over hundreds of entries on a network mount
                    # where EIO is routine — one raised and the caller lost every
                    # other file's result with it (see /validate-models).
                    indeterminate.append({
                        "name": name, "path": rel_path, "size": None,
                        "issue": "Could not stat file",
                    })
                    continue
                partial.append({"name": name, "path": rel_path, "size": size, "issue": "Incomplete download (temp file)"})
                continue
            # Not `is_transient_artifact` (handled above) and not `_is_sidecar`:
            # `is_model_candidate` also excludes the non-model assets that belong
            # in these directories — `models/wildcards` and `models/embeddings`
            # hold `.txt` prompt files, `models/poses` holds `.yaml` — and every
            # one of them is under `delete_invalid=True` here, on a timer.
            #
            # `validate_downloaded_file` skips its header check for those
            # extensions but still applies MIN_MODEL_SIZE, so a 200-byte
            # wildcard list came back `valid: False, indeterminate: False` — a
            # definite verdict, the only kind that deletes — and was removed.
            # Measured before the fix: four `.txt`/`.yaml` files deleted from one
            # `models/wildcards` sweep, only the one over 10 KiB surviving.
            if not is_model_candidate(name):
                continue
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, DATA_ROOT).replace("\\", "/")
            try:
                size = os.path.getsize(full_path)
            except OSError as exc:
                indeterminate.append({
                    "name": name, "path": rel_path, "size": None,
                    "issue": f"Could not stat file: {exc}",
                })
                continue
            if fast:
                if size < MIN_MODEL_SIZE:
                    validation = {
                        "valid": False,
                        "indeterminate": False,
                        "error": f"File too small: {size} bytes (min: {MIN_MODEL_SIZE})",
                        "errors": [f"File too small: {size} bytes (min: {MIN_MODEL_SIZE})"],
                        "format": name.split(".")[-1] if "." in name else "unknown",
                    }
                else:
                    validation = {
                        "valid": True,
                        "indeterminate": False,
                        "format": name.split(".")[-1] if "." in name else "unknown",
                        "size": size,
                    }
            else:
                validation = validate_downloaded_file(full_path)
            model_info = {"name": name, "path": rel_path, "size": size, "size_mb": round(size / (1024 ** 2), 1), "format": validation.get("format", "unknown")}
            if not validation["valid"]:
                model_info["issues"] = validation.get("errors", [validation.get("error", "validation failed")])
                # `indeterminate` means the read FAILED (EIO, ENOMEM, a gcsfuse
                # stall) — not that the file is bad. Reconciliation runs this
                # every 2h with `delete_invalid=True` against the operator's
                # real network volume, so deleting here destroyed a healthy 7 GB
                # checkpoint on a transient read error, together with its .json
                # and .preview.png sidecars. There is no way to recover a
                # multi-GB download removed on a guess, so an unreadable file is
                # reported and left alone; the next tick reads it again. Same
                # guard as the Beam, Modal and LLM validators.
                if validation.get("indeterminate"):
                    model_info["indeterminate"] = True
                    # Its own bucket. It used to be appended to `invalid` with an
                    # extra key, so `total_invalid` counted files that were merely
                    # unreadable — and it is compared against the Modal and LLM
                    # engines' `total_invalid`, which exclude them. Same logical
                    # sweep, three different answers.
                    indeterminate.append(model_info)
                    continue
                invalid.append(model_info)
                if delete_invalid:
                    try:
                        os.remove(full_path)
                    except OSError as exc:
                        logger.warning(f"could not delete invalid file {full_path}: {exc}")
                # Was `else: continue` as the last statement of the loop body, so
                # it was unreachable and `valid.append` below was the only thing
                # that ran when the file *was* valid.
            else:
                valid.append(model_info)

    return {
        "total_valid": len(valid), "total_invalid": len(invalid), "total_partial": len(partial),
        "total_indeterminate": len(indeterminate),
        "valid": valid, "invalid": invalid, "partial": partial,
        "indeterminate": indeterminate,
        "total": len(valid) + len(invalid) + len(partial) + len(indeterminate),
    }


@app.post("/list-models", dependencies=[Depends(verify_token)])
async def list_models(req: ListModelsRequest):
    target_dir = _data_path(req.directory) if req.directory else DATA_ROOT

    def _walk():
        files = []
        if os.path.exists(target_dir):
            for root, _, filenames in os.walk(target_dir, followlinks=True):
                for filename in filenames:
                    if filename.startswith(".") or _is_sidecar(filename):
                        continue
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, DATA_ROOT).replace("\\", "/")
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        size = 0
                    files.append({"name": filename, "path": rel_path, "type": "file", "size": size})
        return files

    listed = await _bounded_to_thread(_walk)
    return ok(f"Listed {len(listed)} models", files=listed)


@app.post("/delete-model", dependencies=[Depends(verify_token)])
async def delete_model(req: DeleteModelRequest):
    full_path = _data_path(req.path)
    if not os.path.exists(full_path) and not list(pending_download_paths(full_path)):
        return failed("File not found", code=404)

    def _do_remove(path: str):
        if os.path.isdir(path):
            import shutil
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)

    def _delete_everything():
        """The whole sweep, off the event loop.

        `shutil.rmtree` is the unbounded operation: it walks and unlinks a whole
        tree, and on this agent that tree is the *same* models volume the Modal
        and Beam engines are reading. A directory of multi-GB weights is seconds
        to minutes of syscalls, and this is the single-process agent's only event
        loop — so for that whole window `/health` stops answering and Docker's 30s
        healthcheck fails a process that is busy, not broken.

        The sidecars and the pipeline artifacts go with it, in the same thread,
        for the same reason: they are `os.remove` calls on the same mount and
        there is no reason to hand control back to the loop between them.
        """
        _do_remove(full_path)
        base, _ = os.path.splitext(full_path)
        for ext in (".json", ".preview.png", ".sha256"):
            _do_remove(base + ext)
        _do_remove(full_path + ".sha256")
        # pipeline_artifacts, not a fixed `.downloading` probe. The per-attempt
        # temp is `<path>.<pid>.<hex>.downloading`, a parked resume slot is
        # `<path>.resume.<identity>.downloading` (downloads.py _unique_temp_path /
        # _resume_slot_path), and `exclusive_path_lock` leaves `<path>.lock` beside
        # both, so the old probe matched none of them: a crash-interrupted 7 GB
        # download survived delete-model forever. It also never got cleaned up by
        # /validate-*-models, which reports every transient artifact as `partial`
        # and deliberately does not delete one — so `total_partial` was permanently
        # non-zero, and step 0 of reconciliation (which runs with delete_invalid)
        # could never reach zero. Modal (modal_app.py) and Beam (beam_app.py) both
        # used the shared helper; this file never referenced it at all.
        for stale in pipeline_artifacts(full_path):
            _do_remove(stale)

    try:
        await _bounded_to_thread(_delete_everything)
    except OSError as exc:
        # Was unhandled: `_do_remove` called os.remove on a directory, which
        # raises IsADirectoryError, so a DELETE of a directory was a 500 while
        # Modal and Beam rmtree the same request and answer 200.
        return failed(f"Delete failed: {exc}")
    return ok(f"Deleted {req.path}")


@app.post("/delete-file", dependencies=[Depends(verify_token)])
async def delete_file(req: DeleteModelRequest):
    """Delete a single file only — no sidecar or pipeline-artifact sweep.

    The backend's `direct_comfy_engine.py` calls `/delete-file` when it wants a
    single path removed (e.g. a stale checkpoint the operator selected). The old
    route shared a handler with `/delete-model`, which also removed `.json`,
    `.preview.png`, `.sha256` sidecars and pipeline temp files — fine for a model
    directory sweep, wrong for a single-file delete that the backend expects to
    touch exactly one path.
    """
    full_path = _data_path(req.path)
    if not os.path.exists(full_path) and not list(pending_download_paths(full_path)):
        return failed("File not found", code=404)

    def _do_remove(path: str):
        if os.path.isdir(path):
            return
        os.remove(path)

    try:
        await _bounded_to_thread(_do_remove, full_path)
    except FileNotFoundError:
        return failed("File not found", code=404)
    except OSError as exc:
        return failed(f"Delete failed: {exc}")
    return ok(f"Deleted {req.path}")


@app.get("/get-file/{path:path}", dependencies=[Depends(verify_token)])
async def get_file(
    path: str,
    type: str = Query(default="output"),
    subfolder: str = Query(default=""),
    format: Optional[str] = Query(default=None),
):
    """Stream a file from DATA_ROOT.

    This read the whole file with `f.read()` inside an `async def` and returned it
    in a single Response. On a single-process `uvicorn.run` that blocks every other
    request on the agent for the duration, and a 7 GB checkpoint is three copies
    of RAM between here and whoever asked for it.

    `FileResponse` reads in chunks on Starlette's own threadpool, so the event loop
    stays free and peak memory is one chunk. The `type` parameter is accepted and
    ignored: it was never used here, and `_data_path` already confines the result
    to DATA_ROOT.

    The size cap is the same backstop beam_app's /get-file uses
    (`provider_core.http_client.get_file_size_cap`, overridable with
    `PROVIDER_GET_FILE_MAX_BYTES`): a wrong `path` must not turn into an
    out-of-memory kill of the agent, and a weights file is not what this route is
    for.
    """
    full_path = _data_path(os.path.join(subfolder, path) if subfolder else path)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    # High-speed WAN path: Convert PNG/JPEG images to high-quality WebP on the fly
    # when requested, reducing payload size by ~80% for fast network transfer.
    if format == "webp" and full_path.lower().endswith((".png", ".jpg", ".jpeg")):
        try:
            from io import BytesIO
            from PIL import Image

            with Image.open(full_path) as im:
                buf = BytesIO()
                im.save(buf, format="WEBP", quality=98)
                return Response(
                    content=buf.getvalue(),
                    media_type="image/webp",
                    headers={"Content-Disposition": f'inline; filename="{os.path.basename(full_path)}.webp"'},
                )
        except Exception as exc:
            logger.warning(f"get_file webp conversion failed for {path}: {exc}")

    max_bytes = get_file_size_cap()
    try:
        size = os.path.getsize(full_path)
    except OSError:
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    # `0` (or negative) is the documented *disable* value, not a zero-byte
    # limit: `max_bytes >= 0` made an operator who disabled the cap get a
    # 413 for every file. The backend's twin normalises to 0 and lets
    # callers treat it as falsy; the same rule here.
    if max_bytes > 0 and size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{path} is {size} bytes, over the {max_bytes} byte get-file limit",
        )

    return FileResponse(full_path, media_type="application/octet-stream", filename=os.path.basename(full_path))


@app.post("/upload-file", dependencies=[Depends(verify_token)])
async def upload_file(req: UploadFileRequest, http_request: Request):
    # The pydantic bound above rejects an over-long *field*, but the body was
    # already read to parse it. Content-Length is declared before that read, so
    # this is the check that actually stops an oversized upload: it answers 413
    # without ever materialising the payload. A missing or unparseable
    # Content-Length is not a reason to fail — chunked bodies are legal — so it
    # falls through to the model's own limit.
    declared = http_request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > UPLOAD_MAX_BYTES_ENCODED:
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload body of {declared} bytes is over the {UPLOAD_MAX_BYTES_ENCODED} byte limit",
                )
        except ValueError:
            pass
    # The decode and the write go to a thread. They did not, and they are the
    # heaviest thing in this file: at the 512 MiB `UPLOAD_MAX_BYTES` ceiling the
    # base64 decode alone is a ~384 MiB allocation and a multi-hundred-megabyte
    # memcpy, followed by a synchronous write of the same size to the models
    # mount. Both inside an `async def`, on the single event loop of a
    # single-process uvicorn, so for the duration of one upload the agent answered
    # *nothing* — not `/health`, not a download, not a validation. Every other
    # heavy call here already went through `_bounded_to_thread`; this one was the
    # only one that missed it.
    target_dir = _data_path(req.directory)
    os.makedirs(target_dir, exist_ok=True)
    path = _data_path(os.path.join(req.directory, req.filename))

    def _decode_and_write():
        content = base64.b64decode(req.content_base64)
        with open(path, "wb") as handle:
            handle.write(content)
        return len(content)

    size = await _bounded_to_thread(_decode_and_write)
    rel_path = os.path.relpath(path, DATA_ROOT).replace("\\", "/")
    return ok("File uploaded", path=rel_path, size=size)


@app.post("/validate-models", dependencies=[Depends(verify_token)])
async def validate_models(req: ValidateModelsRequest):
    dirs = [req.directory] if isinstance(req.directory, str) else req.directory
    # Bounded: this used to be 16 unbounded `asyncio.to_thread` calls, which is
    # the fan-out the comment above /setup warns about — enough of them, or
    # enough concurrent requests, to take every executor thread the single-process
    # agent has and stop the rig answering anything at all.
    payloads = await asyncio.gather(*[
        _bounded_to_thread(_validate_dir, _data_path(d), req.delete_invalid, req.fast)
        for d in dirs
    ], return_exceptions=True)
    results = {"valid": [], "invalid": [], "partial": [], "indeterminate": [], "total_valid": 0, "total_invalid": 0, "total_partial": 0, "total_indeterminate": 0, "by_directory": {}}
    for directory, payload in zip(dirs, payloads):
        if isinstance(payload, BaseException):
            # Was an unguarded gather: one directory raising discarded every
            # other directory's result, so a single EIO on one subdirectory
            # reported "validate failed" and hid the state of the rest of the
            # volume. Reported per directory so the rest of the answer survives.
            results["by_directory"][directory] = {"error": f"{type(payload).__name__}: {payload}"}
            continue
        results["by_directory"][directory] = payload
        for k in ("valid", "invalid", "partial", "indeterminate"):
            results[k].extend(payload.get(k, []))
        results["total_valid"] += payload["total_valid"]
        results["total_invalid"] += payload["total_invalid"]
        results["total_partial"] += payload["total_partial"]
        results["total_indeterminate"] += payload.get("total_indeterminate", 0)
    results["total"] = sum(results[k] for k in ("total_valid", "total_invalid", "total_partial", "total_indeterminate"))
    # The envelope, not a bare `{valid, invalid, partial, ...}`: the worker adopts
    # this body verbatim through `from_upstream`, and a body carrying neither
    # `status` nor `success` is the dialect the envelope exists to make impossible.
    return ok(
        f"Validated {results['total']} files across {len(dirs)} directories",
        result=results,
        **results,
    )


@app.post("/validate-all-models", dependencies=[Depends(verify_token)])
async def validate_all_models(req: Optional[ValidateAllModelsRequest] = None):
    # Was `req: Dict = {}`: a mutable default as a FastAPI body parameter, so
    # every request without a body shared (and could mutate) one dict. The body
    # stays optional so `POST` with no payload still works.
    delete_invalid = req.delete_invalid if req is not None else False
    fast = req.fast if req is not None else True
    return await validate_models(ValidateModelsRequest(directory=list(MODEL_DIRECTORIES), delete_invalid=delete_invalid, fast=fast))


# ---------------------------------------------------------------------------
# High-Speed RAM Cache routes
# ---------------------------------------------------------------------------
@app.get("/ram-cache/status", dependencies=[Depends(verify_token)])
async def ram_cache_status():
    from ram_manager import get_ram_manager
    return get_ram_manager().get_status()


@app.post("/ram-cache/prewarm", dependencies=[Depends(verify_token)])
async def ram_cache_prewarm(req: PrewarmRequest):
    from ram_manager import get_ram_manager
    mgr = get_ram_manager()
    if req.anchors:
        mgr.set_anchors(req.anchors)

    def _do_prewarm():
        specs = [s.model_dump() for s in req.models]
        return mgr.prewarm_models(specs, max_spare_gb=req.max_spare_gb)

    prewarmed = await _bounded_to_thread(_do_prewarm)
    return {
        "ok": True,
        "prewarmed": prewarmed,
        "status": mgr.get_status(),
    }


@app.post("/ram-cache/evict", dependencies=[Depends(verify_token)])
async def ram_cache_evict(req: EvictRequest):
    from ram_manager import get_ram_manager
    mgr = get_ram_manager()
    evicted = mgr.evict_model(req.model_id, force=req.force)
    return {
        "ok": evicted,
        "model_id": req.model_id,
        "status": mgr.get_status(),
    }


# ---------------------------------------------------------------------------
# LLM worker mode: an OpenAI-compatible chat surface.
#
# This is what `RemoteLLMEngine` talks to, and it is deliberately the *same*
# protocol the Modal LLM app (`deployables/modal/llm/app.py`) exposes — so a
# llama.cpp or vLLM container can sit behind it unchanged, and switching between
# Modal and a self-hosted box is a provider row, not a code change.
#
# The engine's `inference` consumes canonical `{"event": ...}` TaskEvent frames
# because it subclasses OpenAICompatLLMEngine; this route speaks SSE because
# that is what an OpenAI-compatible server emits, and the engine's SSE reader is
# already correct and tested. Implementing a TaskEvent dialect here would mean a
# second frame format for no gain.
#
# BY DEFAULT this worker serves its own weights, which is what makes a
# `remote_llm` provider the same thing as `modal_llm` rather than a lookalike.
# Modal runs llama.cpp from `backend_v2/modal_llm/models.json`; so does this, in
# the same shape — one llama-server per distinct primary on adjacent loopback
# ports, routed by the model id in the payload. Set `LLM_UPSTREAM_BASE` to opt
# OUT and front a llama.cpp or vLLM you already run.
# ---------------------------------------------------------------------------
if WORKER_MODE in ("llm", "hybrid"):
    from llama_server import BUNDLED_REGISTRY, LlamaStack, load as load_registry, resolve_registry_path

    REGISTRY = load_registry()
    REGISTRY_PATH = resolve_registry_path()

    #: The model server this worker fronts. Empty means "serve the weights
    #: myself", which is the whole parity claim: the tree this worker manages is
    #: then the tree that answers, and there is nothing to reconcile.
    UPSTREAM_OVERRIDE = os.getenv("LLM_UPSTREAM_BASE", "").strip().rstrip("/")
    if not UPSTREAM_OVERRIDE and WORKER_MODE == "hybrid":
        # In hybrid mode on Colab/self-hosted, llama-server runs on :8003
        UPSTREAM_OVERRIDE = "http://127.0.0.1:8003/v1"

    #: The local stack, launched from the registry when there is no override.
    STACK = LlamaStack(models_dir=DATA_ROOT)

    if UPSTREAM_OVERRIDE:
        # An explicit upstream wins and no local model is loaded: the operator
        # runs their own server, and this worker is the authenticated proxy.
        UPSTREAM_BASE = UPSTREAM_OVERRIDE
        # `extra=`, not a bare keyword: `Logger.info(**kwargs)` forwards them to
        # `_log`, whose signature is (level, msg, args, exc_info, extra,
        # stack_info, stacklevel) — so `base=...` raises TypeError at the FIRST
        # log line on a worker at INFO, which is every deployment. backend_v2
        # uses the `key=value` style everywhere because `infrastructure/logging.py`
        # wraps it; this sidecar deliberately imports nothing from backend_v2 and
        # gets a plain stdlib Logger, so the style does not transfer.
        logger.info("llm_upstream_configured", extra={"base": UPSTREAM_BASE})
        # The arbiter must not ALSO start a JIT llama-server: it would load
        # the same 19.5 GB of weights onto the same card that the operator's
        # server is already using, and every request goes to the operator's
        # port anyway.
        try:
            from vram_manager import get_vram_manager

            get_vram_manager().llm_served_externally = True
        except Exception:
            pass
    elif REGISTRY is None:
        # No registry and no override. There is nothing to serve and nothing to
        # proxy, which is a configuration error rather than an empty answer.
        UPSTREAM_BASE = ""
        if WORKER_MODE == "llm":
            raise RuntimeError(
                "WORKER_MODE=llm needs either a models registry at "
                f"{BUNDLED_REGISTRY} or LLM_UPSTREAM_BASE set"
            )
    else:
        _started = STACK.launch(REGISTRY)
        logger.info(
            "llm_serving_local_models",
            extra={
                "registry_path": str(REGISTRY_PATH),
                "roles": {r: REGISTRY.primary(r).id for r in REGISTRY.roles},
                "servers": _started,
            },
        )
        # Nothing to proxy to: requests are routed to whichever loopback port
        # serves the named model. See `_upstream_for`.
        UPSTREAM_BASE = ""
        # The local stack IS the LLM server, so the arbiter must not start a
        # JIT llama-server as well. It used to, and the two loaded the same
        # 19.5 GB of weights onto one 24 GB card — which is an OOM, and it
        # was the arbiter's copy that lost.
        try:
            from vram_manager import get_vram_manager

            get_vram_manager().llm_served_externally = True
        except Exception:
            pass

    UPSTREAM_TIMEOUT = float(os.getenv("LLM_UPSTREAM_TIMEOUT", "600"))

    def _upstream_for(payload: dict) -> str:
        """The base URL that serves the model this payload names.

        With no local stack this is the configured upstream, unchanged. With one,
        it is the port that model is on, which is why the model id is what the
        registry's `--alias` makes llama-server answer for.
        """
        if UPSTREAM_BASE:
            return UPSTREAM_BASE
        model_id = (payload or {}).get("model") or ""
        return f"http://127.0.0.1:{STACK.resolve(model_id)}"

    def _unavailable_payload(exc: Exception) -> dict:
        """A 503-shaped error body for a model this worker does not serve.

        `_resolve` raises non-retryable for a configuration state, which the
        engine reads as retryable=False — the signal that says try another
        provider rather than back off and retry this one.
        """
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": str(exc),
                "retryable": False,
                "served_models": sorted(STACK.servers),
            },
        )
    import urllib.error
    import urllib.parse
    import urllib.request

    #: Where the actual model server lives: llama.cpp / vLLM on the same host,
    #: or another container on the compose network. The worker is a proxy plus a
    #: token check, which is what lets the backend speak the service-token auth
    #: it already has while the app underneath stays plain OpenAI.
    UPSTREAM_TIMEOUT = float(os.getenv("LLM_UPSTREAM_TIMEOUT", "600"))

    @app.post("/v1/chat/completions", dependencies=[Depends(verify_token)])
    async def chat_completions(request: Request):
        """Proxy the chat completion stream to the upstream model server.

        Proxied rather than reimplemented: the model server already speaks SSE,
        already handles `stream: true`, and already knows its own tool-calling
        template. A reimplementation here would be a second partial copy of
        llama.cpp's protocol.
        """
        body = await request.body()
        try:
            payload = json.loads(body) if body else {}
        except ValueError:
            payload = {}
        try:
            base = _upstream_for(payload)
        except Exception as exc:
            # A model this worker does not hold. Named rather than proxied, so the
            # backend sees retryable=False and fails over to another provider
            # instead of backing off against this one.
            return _unavailable_payload(exc)

        is_streaming = bool(payload.get("stream", True))

        from fastapi.responses import StreamingResponse, Response
        # In hybrid or LLM mode, coordinate VRAM via VRAMManager:
        # 1) yield ComfyUI models from VRAM (<500ms)
        # 2) preserve Laya System 1 on CUDA
        # 3) start llama-server Just-In-Time from /dev/shm if not already running
        # 4) acquire active LLM lease so no concurrent image request terminates the inference
        lease_acquired = False
        try:
            from vram_manager import get_vram_manager
            target_model = payload.get("model")
            vmgr = get_vram_manager()
            await _bounded_to_thread(vmgr.prepare_for_workload, "llm", target_model)
            # `prepare_for_workload` took the lease. Taking it AGAIN here is
            # what left `in_flight_count` permanently at 1 — one acquire, one
            # release, and the counter never returned to zero. The lease is
            # released once, below, when the request finishes.
            lease_acquired = True
        except Exception:
            if WORKER_MODE == "hybrid":
                try:
                    async with httpx.AsyncClient(timeout=2.0) as free_client:
                        await free_client.post(
                            "http://127.0.0.1:8188/free",
                            json={"unload_models": True, "free_memory": True},
                        )
                except Exception:
                    pass

        client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT)

        try:
            upstream_req = client.build_request(
                "POST",
                f"{base}/chat/completions",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream" if is_streaming else "application/json",
                },
            )
            upstream_resp = await client.send(upstream_req, stream=True)
        except httpx.ConnectError as exc:
            if lease_acquired:
                try:
                    from vram_manager import get_vram_manager
                    await _bounded_to_thread(get_vram_manager().release_lease, "llm")
                    lease_acquired = False
                except Exception:
                    pass
            await client.aclose()
            err_payload = {
                "status": "error",
                "error": {
                    "message": f"Upstream LLM server unreachable on {base}: {exc}",
                    "type": "upstream_unavailable",
                    "code": 503,
                },
                "message": f"Upstream LLM server unreachable on {base}: {exc}",
                # RETRYABLE. This was False, which told the backend "this
                # provider is permanently broken" — so a server that was still
                # LOADING its weights, or that had been OOM-killed and was
                # about to be restarted, made the backend fail over to
                # another provider (spending money) instead of waiting and
                # retrying this one.
                #
                # The genuinely non-retryable case is a model this worker does
                # not serve, and that is `_unavailable_payload`, which is
                # still False.
                "retryable": True,
            }
            return Response(content=json.dumps(err_payload), status_code=503, media_type="application/json")
        except Exception as exc:
            if lease_acquired:
                try:
                    from vram_manager import get_vram_manager
                    await _bounded_to_thread(get_vram_manager().release_lease, "llm")
                    lease_acquired = False
                except Exception:
                    pass
            await client.aclose()
            err_payload = {
                "status": "error",
                "error": {
                    "message": f"Upstream LLM proxy error: {exc}",
                    "type": "upstream_error",
                    "code": 502,
                },
                "message": f"Upstream LLM proxy error: {exc}",
                # RETRYABLE — see the 503 above. A proxy error is a transport
                # failure, not a statement about the provider.
                "retryable": True,
            }
            return Response(content=json.dumps(err_payload), status_code=502, media_type="application/json")

        if upstream_resp.status_code != 200:
            err_bytes = await upstream_resp.aread()
            await upstream_resp.aclose()
            await client.aclose()
            if lease_acquired:
                try:
                    from vram_manager import get_vram_manager
                    await _bounded_to_thread(get_vram_manager().release_lease, "llm")
                    lease_acquired = False
                except Exception:
                    pass
            return Response(
                content=err_bytes,
                status_code=upstream_resp.status_code,
                media_type=upstream_resp.headers.get("Content-Type", "application/json"),
            )

        async def _stream_generator():
            try:
                async for chunk in upstream_resp.aiter_bytes():
                    yield chunk
            finally:
                if lease_acquired:
                    try:
                        from vram_manager import get_vram_manager
                        await _bounded_to_thread(get_vram_manager().release_lease, "llm")
                    except Exception:
                        pass
                await upstream_resp.aclose()
                await client.aclose()

        return StreamingResponse(
            _stream_generator(),
            status_code=200,
            media_type=upstream_resp.headers.get("Content-Type", "text/event-stream"),
        )


    @app.get("/v1/models", dependencies=[Depends(verify_token)])
    @app.get("/models", dependencies=[Depends(verify_token)])
    async def list_upstream_models():
        """Proxy models list to the upstream llama-server / vLLM."""
        from fastapi.responses import Response

        base = UPSTREAM_BASE or "http://127.0.0.1:8003/v1"

        def _forward() -> tuple[int, bytes, str]:
            url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    return resp.status, resp.read(), resp.headers.get("Content-Type", "")
            except Exception:
                # Upstream llama-server is in idle/standby JIT mode.
                # Discover available GGUF models so health checks and model listings see the worker as ready!
                models_data = [{"id": "default", "object": "model", "owned_by": "remote_agent"}]
                try:
                    from vram_manager import get_vram_manager
                    vmgr = get_vram_manager()
                    _, resolved_mid = vmgr._resolve_model_path(None)
                    if resolved_mid and resolved_mid != "default":
                        models_data.append({"id": resolved_mid, "object": "model", "owned_by": "remote_agent"})
                except Exception:
                    pass
                return 200, json.dumps({"object": "list", "data": models_data}).encode(), "application/json"

        status, payload, content_type = await _bounded_to_thread(_forward)
        return Response(content=payload, status_code=status, media_type=content_type or "application/json")


# ---------------------------------------------------------------------------
# System 1 Decision Maker (Laya CPU/RAM Engine) — 0 MB GPU VRAM
# ---------------------------------------------------------------------------
_LAYA_LOADED_MODELS: Dict[str, Any] = {}

_LAYA_REPO_MAP = {
    "laya_multilingual": "convaiinnovations/laya-multilingual",
    "laya_typed_decisions": "convaiinnovations/laya-typed-decisions",
    "laya_english": "convaiinnovations/laya",
}


class DecisionsRequest(BaseModel):
    model: str = "laya_multilingual"
    context: str = ""
    state: str = ""
    questions: Any = Field(default_factory=list)


def _evaluate_laya_sync(model_id: str, context_text: str, questions: Any) -> Dict[str, Any]:
    import laya  # type: ignore

    repo_or_path = _LAYA_REPO_MAP.get(model_id, model_id)
    served_from_ram = False
    try:
        from ram_manager import get_ram_manager
        mgr = get_ram_manager()
        # The RAM copy is only used when the cache says it is COMPLETE.
        #
        # The test used to be "the directory exists and is non-empty", which
        # a half-finished copy passes: `ensure_dir_in_ram` wrote in place and
        # a copy that died on ENOSPC left a partial directory behind, and the
        # next request loaded it. `resolve_entry` only knows about entries
        # the manager published, and the manager only publishes one after a
        # verified copy.
        ram_entry = mgr.resolve_entry(model_id)
        if ram_entry is not None:
            ram_candidate = Path(ram_entry.ram_path)
            if ram_candidate.is_dir() and any(ram_candidate.iterdir()):
                repo_or_path = str(ram_candidate)
                served_from_ram = True
        persistent_path = os.getenv("PERSISTENT_STORAGE_PATH", "")
        disk_candidates = [
            os.path.join(DATA_ROOT, "decisions", model_id),
            os.path.join(persistent_path, "decisions", model_id) if persistent_path else "",
            f"/mnt/data/tnhcomfy/decisions/{model_id}",
            f"/content/agent-data/decisions/{model_id}",
            f"{os.path.expanduser('~')}/agent-data/decisions/{model_id}",
            f"/content/models/decisions/{model_id}",
        ]
        for disk_candidate in ([] if served_from_ram else disk_candidates):
            if os.path.isdir(disk_candidate) and os.listdir(disk_candidate):
                try:
                    ram_synced = mgr.ensure_dir_in_ram(disk_candidate, model_id=model_id, role="decisions", is_anchor=True)
                    repo_or_path = str(ram_synced)
                    break
                except Exception:
                    repo_or_path = disk_candidate
                    break
    except Exception:
        pass

    device = "cpu"
    try:
        from vram_manager import get_vram_manager
        vram_mgr = get_vram_manager()
        laya_model, device = vram_mgr.get_or_load_laya(model_id, repo_or_path)
    except Exception:
        laya_model = _LAYA_LOADED_MODELS.get(repo_or_path)
        if laya_model is None:
            target_dev = "cuda:0"
            try:
                from vram_manager import get_vram_manager
                target_dev = f"cuda:{get_vram_manager().laya_gpu_device}"
            except Exception:
                pass
            try:
                import torch
                if not torch.cuda.is_available():
                    target_dev = "cpu"
            except Exception:
                target_dev = "cpu"
            hf_token = HF_TOKEN or os.getenv("HF_TOKEN") or None
            try:
                laya_model = laya.load(repo_or_path, device=target_dev, token=hf_token)
                m_dev = getattr(laya_model, "device", None)
                device = "cuda" if "cuda" in str(m_dev or target_dev).lower() else "cpu"
            except Exception:
                laya_model = laya.load(repo_or_path, device="cpu", token=hf_token)
                device = "cpu"
            _LAYA_LOADED_MODELS[repo_or_path] = laya_model

    if isinstance(questions, dict):
        q_list = [{"key": k, **v} for k, v in questions.items() if isinstance(v, dict)]
    elif isinstance(questions, list):
        q_list = [q for q in questions if isinstance(q, dict) and "key" in q]
    else:
        q_list = []

    questions_dict: Dict[str, Any] = {}
    min_rubric_val: Dict[str, int] = {}
    for q in q_list:
        key = q["key"]
        q_type = q.get("type")
        if q_type == "choice":
            opts = q.get("options")
            if isinstance(opts, dict):
                criteria = opts
            elif isinstance(opts, list):
                criteria = opts
            else:
                criteria = []
            questions_dict[key] = {
                "type": "choice",
                "instructions": q.get("question") or q.get("prompt") or "",
                "criteria": criteria,
            }
        elif q_type == "score":
            rubric_raw = q.get("rubric") or {}
            if isinstance(rubric_raw, dict):
                sorted_keys = sorted(rubric_raw.keys(), key=lambda x: int(x))
                min_rubric_val[key] = int(sorted_keys[0]) if sorted_keys else 1
                criteria = [rubric_raw[k] for k in sorted_keys]
            else:
                min_rubric_val[key] = 1
                criteria = [str(x) for x in (q.get("options") or [])]
            questions_dict[key] = {
                "type": "score",
                "instructions": q.get("question") or q.get("prompt") or "",
                "criteria": criteria or ["1", "2", "3", "4", "5"],
            }
        elif q_type in ("noul", "yes_no"):
            questions_dict[key] = {
                "type": "noul",
                "instructions": q.get("statement") or q.get("prompt") or q.get("question") or "",
            }

    t0 = time.perf_counter()
    raw_result = laya_model.predict(context_text, questions_dict)
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    raw_answers = raw_result.get("answers", {}) if isinstance(raw_result, dict) else {}
    answers: Dict[str, Any] = {}
    for q in q_list:
        key = q["key"]
        q_type = q.get("type")
        ans = raw_answers.get(key)
        if ans is None:
            continue
        if q_type == "choice":
            choice_val = ans.get("choice") or ans.get("selected")
            probs_val = ans.get("probabilities") or ans.get("probs") or {}
            answers[key] = {
                "choice": str(choice_val) if choice_val is not None else "",
                "probabilities": dict(probs_val or {}),
            }
        elif q_type == "score":
            score_raw = ans.get("score")
            if score_raw is None:
                score_raw = ans.get("expected", 0.0)
            score_num = float(score_raw)
            offset = min_rubric_val.get(key, 0)
            if offset > 0:
                score_num += float(offset)
            answers[key] = {"score": round(score_num, 2)}
        elif q_type in ("noul", "yes_no"):
            prob_val = ans.get("noul") if "noul" in ans else ans.get("probability", 0.0)
            answers[key] = {"probability": float(prob_val) if prob_val is not None else 0.0}

    m_dev = getattr(laya_model, "device", None)
    actual_dev = str(m_dev) if m_dev is not None else device
    report_dev = "cuda" if "cuda" in actual_dev.lower() else "cpu"

    return {
        "status": "success",
        "model_id": model_id,
        "engine_used": f"remote_laya_{report_dev}",
        "provider_tier": "remote_laya",
        "device": report_dev,
        "latency_ms": latency_ms,
        "answers": answers,
        "results": answers,
    }


def _evaluate_laya_cpu_sync(model_id: str, context_text: str, questions: Any) -> Dict[str, Any]:
    return _evaluate_laya_sync(model_id, context_text, questions)


@app.post("/v1/decisions", dependencies=[Depends(verify_token)])
async def evaluate_decisions(req: DecisionsRequest):
    """Evaluate parallel typed System 1 questions using Laya (GPU-accelerated when VRAM available, CPU fallback)."""
    try:
        res = await _bounded_to_thread(
            _evaluate_laya_sync,
            req.model,
            req.context or req.state,
            req.questions,
            timeout_seconds=60.0,
        )
        return res
    except ImportError as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": f"laya package not installed on remote agent: {exc}",
                "retryable": False,
            },
        )
    except Exception as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "message": f"Laya evaluation failed: {exc}",
                "retryable": False,
            },
        )


@app.on_event("startup")
async def _on_startup_prewarm():
    """Background startup tasks: pre-warm Laya System 1 on CUDA so first requests are <100ms."""
    import threading

    def _prewarm_laya():
        try:
            import laya  # noqa: F401
            target_model = os.getenv("LAYA_MODEL_ID", "laya_multilingual")
            logger.info(f"prewarming_laya_background: {target_model}")
            _evaluate_laya_sync(target_model, "Hello world", [])
            logger.info(f"prewarming_laya_complete: {target_model}")
        except Exception as exc:
            logger.warning(f"laya_prewarm_failed: {exc}")

    threading.Thread(target=_prewarm_laya, daemon=True, name="laya-prewarm").start()


@app.on_event("shutdown")
async def _on_shutdown_stop_children():
    """Stop the child processes this agent started.

    The agent had no teardown at all: no `atexit`, no SIGTERM handler. So when
    the agent exited — cleanly, by `docker stop`, or by being OOM-killed — its
    llama-servers were NOT stopped. In Docker the container teardown killed
    them, but in the Colab deployment the agent is a child of the notebook
    kernel, so the servers became true orphans that kept the GPU allocated
    while the notebook's watchdog started a replacement.

    And the orphans' ports are the SAME fixed ports the next agent start
    binds, so the next start collided with them — which the launch reported
    as a failure, which used to kill the worker at import.
    """
    stopped = 0
    try:
        if STACK is not None:
            stopped = STACK.stop()
            if stopped:
                logger.info("llama_stack_stopped", extra={"count": stopped})
    except Exception as exc:
        logger.warning("llama_stack_stop_failed", extra={"error": str(exc)})

    try:
        from vram_manager import get_vram_manager

        get_vram_manager().stop_llama()
    except Exception as exc:
        logger.warning("jit_llama_stop_failed", extra={"error": str(exc)})


def _atexit_stop_children() -> None:
    """The backstop for an exit the shutdown event never sees.

    The shutdown event fires on SIGTERM and on a clean exit. It does NOT fire
    on SIGKILL, on an OOM kill, or on an interpreter crash — and those are
    exactly the cases where the children need to be reaped.
    """
    try:
        if STACK is not None:
            STACK.stop()
    except Exception:
        pass


atexit.register(_atexit_stop_children)


# ---------------------------------------------------------------------------
# Dynamic VRAM Arbiter Routes
# ---------------------------------------------------------------------------
class VramPrepareRequest(BaseModel):
    workload: str = "image"
    model: Optional[str] = None
    min_free_vram_mb: Optional[int] = None
    kv_cache_type: Optional[str] = None
    context_tokens: Optional[int] = None
    timeout: Optional[float] = 60.0


class VramReleaseRequest(BaseModel):
    workload: str = "image"


@app.post("/vram/prepare", dependencies=[Depends(verify_token)])
async def vram_prepare(req: VramPrepareRequest):
    """Coordinate VRAM allocation before dispatching a workload."""
    from vram_manager import get_vram_manager
    mgr = get_vram_manager()
    res = await _bounded_to_thread(
        mgr.prepare_for_workload,
        req.workload,
        model_id=req.model,
        min_free_vram_mb=req.min_free_vram_mb or 0,
        kv_cache_type=req.kv_cache_type,
        context_tokens=req.context_tokens,
        timeout=req.timeout or 60.0,
    )
    return res


@app.post("/vram/release", dependencies=[Depends(verify_token)])
async def vram_release(req: VramReleaseRequest):
    """Explicitly release a workload lease and wake queued workloads."""
    from vram_manager import get_vram_manager
    mgr = get_vram_manager()
    await _bounded_to_thread(mgr.release_lease, req.workload)
    return {
        "status": "released",
        "workload": req.workload,
        "active_lease": mgr.active_lease,
        "in_flight": mgr.in_flight_count,
        "queue_depth": len(mgr.waiting_queue),
    }


@app.get("/vram/status", dependencies=[Depends(verify_token)])
async def vram_status():
    """Report live GPU VRAM usage, device details, and component states."""
    from vram_manager import get_vram_manager
    mgr = get_vram_manager()
    return mgr.get_vram_info()


@app.post("/vram/stop-llm", dependencies=[Depends(verify_token)])
async def vram_stop_llm():
    """Explicitly stop llama-server to immediately recover 10-18GB VRAM."""
    from vram_manager import get_vram_manager
    mgr = get_vram_manager()
    stopped = await _bounded_to_thread(mgr.stop_llama)
    return {"status": "success" if stopped else "noop", "vram": mgr.get_vram_info()}


# ---------------------------------------------------------------------------
# TTS & Hybrid worker voice enumeration:
# Enumerate available voices from Qwen3-TTS voice library + designed voices.
# ---------------------------------------------------------------------------
if WORKER_MODE in ("tts", "hybrid"):
    @app.get("/v1/voices", dependencies=[Depends(verify_token)])
    async def list_voices():
        """Enumerate available voices from Qwen3-TTS voice library + designed voices."""
        import glob
        voices = []
        
        # Qwen3-TTS preset voices (9 built-in timbres)
        preset_voices = [
            {"id": "friendly", "name": "Friendly", "type": "preset", "language": "en", "description": "Warm, approachable tone"},
            {"id": "professional", "name": "Professional", "type": "preset", "language": "en", "description": "Clear, authoritative delivery"},
            {"id": "cheerful", "name": "Cheerful", "type": "preset", "language": "en", "description": "Bright, energetic tone"},
            {"id": "calm", "name": "Calm", "type": "preset", "language": "en", "description": "Relaxed, soothing presence"},
            {"id": "deep", "name": "Deep", "type": "preset", "language": "en", "description": "Rich, resonant bass"},
            {"id": "bright", "name": "Bright", "type": "preset", "language": "en", "description": "Crisp, clear high register"},
            {"id": "storyteller", "name": "Storyteller", "type": "preset", "language": "en", "description": "Expressive, narrative style"},
            {"id": "whisper", "name": "Whisper", "type": "preset", "language": "en", "description": "Intimate, hushed delivery"},
            {"id": "dramatic", "name": "Dramatic", "type": "preset", "language": "en", "description": "Theatrical, emotional range"},
        ]
        
        for pv in preset_voices:
            voices.append(pv)
        
        # Designed voices: scan output/voice/ directory for saved voice designs
        voice_output_dir = os.path.join(DATA_ROOT, "output", "voice")
        if os.path.isdir(voice_output_dir):
            for voice_dir in os.listdir(voice_output_dir):
                voice_path = os.path.join(voice_output_dir, voice_dir)
                if os.path.isdir(voice_path):
                    # Check for metadata file
                    meta_path = os.path.join(voice_path, "metadata.json")
                    if os.path.exists(meta_path):
                        try:
                            import json
                            with open(meta_path, "r") as f:
                                meta = json.load(f)
                            voices.append({
                                "id": f"design_{voice_dir}",
                                "name": meta.get("name", voice_dir),
                                "type": "design",
                                "language": meta.get("language", "en"),
                                "description": meta.get("description", ""),
                                "created": meta.get("created"),
                            })
                        except Exception:
                            voices.append({
                                "id": f"design_{voice_dir}",
                                "name": voice_dir,
                                "type": "design",
                                "language": "en",
                                "description": "Designed voice",
                            })
                    else:
                        # Look for audio files to infer
                        audio_files = glob.glob(os.path.join(voice_path, "*.wav")) + glob.glob(os.path.join(voice_path, "*.mp3"))
                        if audio_files:
                            voices.append({
                                "id": f"design_{voice_dir}",
                                "name": voice_dir,
                                "type": "design",
                                "language": "en",
                                "description": "Designed voice (no metadata)",
                            })
        
        return {"voices": voices, "total": len(voices)}

    @app.post("/synthesize", dependencies=[Depends(verify_token)])
    async def synthesize(req: SynthesizeRequest):
        """Synthesise speech and return the stored clip's address.

        Returns a descriptor, not the audio: `RemoteTTSEngine.get_file_stream`
        fetches the bytes under the shared read cap, and a job that finalised
        with an oversized inline body would bypass it.
        """
        import subprocess

        # `TTS_COMMAND` is the operator's hook: the container ships no model by
        # default, and pointing it at any `text -> wav` shell command (Qwen3-TTS CLI,
        # an in-process server) is all that is needed. Missing means no
        # synthesis is configured, which is a 503 rather than a crash.
        command = os.getenv("TTS_COMMAND", "").strip()
        if not command:
            return failed(
                "TTS worker has no TTS_COMMAND configured; set it to a "
                "`text -> wav` command and restart the container",
                code=503,
            )

        target_dir = os.path.join(_ensure_data_dir(), AUDIO_DIR)
        os.makedirs(target_dir, exist_ok=True)
        suffix = (req.format or "wav").lstrip(".")
        filename = f"tts-{os.urandom(8).hex()}.{suffix}"
        output_path = os.path.join(target_dir, filename)

        env = dict(os.environ)
        env.update({
            "TTS_TEXT": req.text,
            "TTS_OUTPUT": output_path,
            "TTS_FORMAT": suffix,
        })
        if req.voice:
            env["TTS_VOICE"] = req.voice
        if req.speed is not None:
            env["TTS_SPEED"] = str(req.speed)
        if req.sample_rate is not None:
            env["TTS_SAMPLE_RATE"] = str(req.sample_rate)

        timeout_seconds = float(os.getenv("TTS_COMMAND_TIMEOUT", "600"))

        def _run() -> tuple[int, bytes, bytes]:
            proc = subprocess.run(
                command, shell=True, env=env,
                capture_output=True, timeout=timeout_seconds,
            )
            return proc.returncode, proc.stdout, proc.stderr

        try:
            returncode, stdout, stderr = await _bounded_to_thread(
                _run, timeout_seconds=timeout_seconds + 30
            )
        except Exception as exc:
            return failed(f"TTS synthesis failed: {exc}", code=502)

        if returncode != 0:
            detail = stderr.decode("utf-8", "ignore")[:300] or "no stderr"
            return failed(f"TTS command exited {returncode}: {detail}", code=502)

        if not os.path.exists(output_path):
            return failed(
                "TTS command exited 0 but wrote no file at the expected path",
                code=502,
            )

        # Audio clips are addressed by their path under DATA_ROOT (relative), so
        # the engine's `/get-file/{path}` and `/delete-file` treat them exactly
        # like any other artefact.
        rel_path = f"{AUDIO_DIR}/{filename}"

        def _duration() -> Optional[float]:
            import struct

            try:
                with open(output_path, "rb") as fh:
                    header = fh.read(44)
                if len(header) < 44 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                    return None
                byte_rate = struct.unpack("<I", header[28:32])[0]
                data_size = struct.unpack("<I", header[40:44])[0]
                return round(data_size / byte_rate, 3) if byte_rate else None
            except Exception:
                return None

        return ok("Synthesised", result={
            "path": rel_path,
            "filename": filename,
            "duration": await _bounded_to_thread(_duration),
            "voice": req.voice,
        })



class ReconcileBackendRequest(BaseModel):
    backend_url: Optional[str] = None
    provider_id: Optional[str] = None
    force: bool = True
    quick_sync: bool = False


@app.post("/reconcile-backend", dependencies=[Depends(verify_token)])
async def reconcile_with_backend(req: ReconcileBackendRequest):
    """Trigger reconciliation on the backend for this provider directly from the worker."""
    backend_url = (req.backend_url or os.getenv("BACKEND_URL", "")).strip().rstrip("/")
    provider_id = (req.provider_id or os.getenv("PROVIDER_ID", "colab_worker")).strip()
    if not backend_url:
        return failed("BACKEND_URL not configured", code=400)

    url = f"{backend_url}/api/v2/providers/{provider_id}/reconcile"
    params = {"force": str(req.force).lower(), "quick_sync": str(req.quick_sync).lower()}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, params=params)
            if resp.status_code >= 400:
                return failed(f"Backend returned HTTP {resp.status_code}: {resp.text}", code=resp.status_code)
            return ok("Reconciliation triggered on backend", result=resp.json())
    except Exception as exc:
        return failed(f"Failed to reach backend: {exc}", code=502)


if WORKER_MODE == "storage":
    @app.api_route("/v1/chat/completions", methods=["POST", "GET"])
    @app.api_route("/v1/models", methods=["GET"])
    @app.api_route("/synthesize", methods=["POST"])
    @app.api_route("/v1/voices", methods=["GET"])
    @app.api_route("/prompt", methods=["POST"])
    async def storage_mode_inference_unavailable():
        raise HTTPException(
            status_code=503,
            detail="Worker is running in storage-only / model-manager mode on CPU. Switch Colab runtime to GPU hybrid mode for inference."
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8001"))
    _warn_insecure_bind()
    uvicorn.run(app, host=_resolve_bind_host(), port=port, access_log=True, log_level="info")
