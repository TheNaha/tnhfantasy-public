"""
TNH LLM on Modal — llama.cpp servers reachable only through the Modal SDK.

ONE class, `ChatLLM`, parametrized by model id. Modal gives each distinct
`model_id` its own container pool with its own lifecycle and scale-to-zero
timer, so every model in the registry is individually addressable without a
separate function or a public URL per model. The backend reads the same
`models.json` this image is built with, so the role's primary and its fallback
chain are agreed on both sides.

There is no HTTP surface at all. The earlier version used `modal.web_server`,
which left unauthenticated public URLs where llama-server's own API key was the
only thing between the internet and the model. Plain `@modal.method()` is
reachable only through the Modal SDK with the caller's token.

Setup (once):
    modal secret create tnh-llm-key LLAMA_API_KEY=<long-random-string>
    modal run deployables/modal/llm/app.py              # download the two role primaries
    modal deploy deployables/modal/llm/app.py
    modal run deployables/modal/llm/app.py::urls        # manifest for the backend
    modal run deployables/modal/llm/app.py::bench --key artemis_31b   # cold-start timer

Call a model:
    cls = modal.Cls.from_name("tnh-llm", "ChatLLM")
    cls(model_id="artemis_31b").complete.remote([{...}])
    # or, streamed:
    for chunk in cls(model_id="artemis_31b").stream.remote_gen([{...}]):
        ...

To add a model to rotation: add it to models.json, then
    modal run deployables/modal/llm/app.py::ensure --model-id <id>`   # fetch weights
    modal deploy deployables/modal/llm/app.py                          # make it routable
`ensure_model` downloads on demand and `volume_state` reports what is genuinely
on the Volume, so a model can be fetched before it is needed.

MEASURED (2026-10-11, first real deploy): ~18 s of llama-server model load for
a 23.5 GB GGUF off the Volume, ~26 s cold container to an answered SDK call,
4-10 s warm. See README.md.
"""

# NOTE: no `from __future__ import annotations` here, deliberately.
#
# Modal 1.5.5 validates a `modal.parameter()` attribute by reading the
# annotation's `.`__name__`. With PEP 563 in effect every annotation is a
# *string*, so `model_id: str = modal.parameter()` hands Modal `"str"` instead
# of `str`, and registration dies with
# `AttributeError: 'str' object has no attribute '__name__'`. The `X | Y`
# spelling below is native from 3.10 and the image runs 3.12, so the future
# import is not needed.

import json
import logging
import os
import sys
import time
import urllib.request
from pathlib import Path

import modal

# The storage surface added below (`FileStorage`, `list_models_with_metadata`,
# `validate_models`) needs to report reload failures the way the image and TTS
# apps already do. This module predates all three of those and had no logger of
# its own, so there was nothing to reach for.
logger = logging.getLogger(__name__)

# `registry.py` and `models.json` do NOT sit beside this file any more — they
# stayed in `backend_v2/modal_llm/`, because the backend's `llm_router` and
# `remote_agent/llama_server.py` both import the registry and there is no reason
# for three consumers to resolve one file by search. This file is the odd one
# out, and used to solve that by sitting with them.
#
# Modal uploads ONLY the module it runs — `app.py` becomes `/root/app.py` and
# its siblings do not come with it — so locally this import works and remotely
# it dies with `ModuleNotFoundError: No module named 'registry'`, on every
# function, at hydrate time. Both images therefore ADD the registry directory,
# and the import looks there first.
#
# The repo root is resolved by marker rather than by counting parents: counting
# is exactly what made the image and beam apps un-deployable, and this file just
# moved two levels deeper. Falls through to None inside the container, where the
# app is uploaded to `/root` with no repo above it and `sys.path[0]` is already
# the directory the image added.
_HERE = Path(__file__).resolve().parent
_REMOTE_LLM_DIR = Path("/app/modal_llm")
# This file is 3 levels below the repo root: modal/llm -> modal -> deployables.
_REPO_ROOT = next(
    (p for p in _HERE.parents if (p / "backend_v2" / "modal_llm" / "registry.py").is_file()),
    None,
)
_LOCAL_REGISTRY_DIR = _REPO_ROOT / "backend_v2" / "modal_llm" if _REPO_ROOT else None

# Order matters and is NOT "remote first". `/app/modal_llm` is where the Modal
# image puts the registry, but `backend_v2/` is mounted at `/app` inside the
# backend container, so `/app/modal_llm` also exists there — for a completely
# unrelated reason, and it happens to hold the right file. A local repo must win
# so the checkout is what gets packaged; `/app/modal_llm` is the fallback for the
# Modal container, which has no repo at all.
for _candidate in (
    _LOCAL_REGISTRY_DIR,
    _REMOTE_LLM_DIR if _REMOTE_LLM_DIR.is_dir() else None,
):
    if _candidate and (_candidate / "registry.py").is_file():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break
else:  # pragma: no cover - a broken checkout, reported by the import below
    raise RuntimeError(
        f"cannot locate registry.py: looked in {_LOCAL_REGISTRY_DIR} and "
        f"{_REMOTE_LLM_DIR}"
    )

from registry import REGISTRY_PATH, load  # noqa: E402

# `provider_core` is a sibling of nothing. It used to live next to every worker
# that imported it by bare name; `acc86aa3` moved it under `remote_agent/`,
# which the LLM app was not a consumer of and therefore never got the sibling
# import for. The storage surface below needs the same helpers the image app
# uses — path traversal rejection, the download entry point, the pipeline
# sidecar sweep — so it resolves them the way `modal/image/modal_app.py` does.
_HERE = Path(__file__).resolve().parent
for _candidate in (
    _HERE.parents[1] if len(_HERE.parents) > 1 else None,
    *(p for p in _HERE.parents if (p / "remote_agent" / "provider_core").is_dir()),
):
    if _candidate and (candidate_core := _candidate / "remote_agent").is_dir():
        if str(candidate_core) not in sys.path:
            sys.path.insert(0, str(candidate_core))
        break

from provider_core.downloads import (  # noqa: E402
    download_model_to_path,
    pending_download_paths,
    pipeline_artifacts,
)
from provider_core.utils import get_safe_path, is_model_candidate  # noqa: E402

#: What both images `add_local_dir`. Resolved now, not at image-build time, so a
#: local checkout packages the checkout's registry and the Modal container
#: packages the copy it already has at `/app/modal_llm`.
_REGISTRY_SRC = _LOCAL_REGISTRY_DIR or _REMOTE_LLM_DIR

APP_NAME = "tnh-llm"
app = modal.App(APP_NAME)

MODELS_DIR = "/models"
PORT = 8080

#: The registry as it was when this file was last deployed. Baked into the image
#: so a deployed container knows its own role and sampler without a network call.
REGISTRY_REMOTE = "/models-registry"

vol = modal.Volume.from_name("tnh-llm-models", create_if_missing=True)

#: Prebuilt llama.cpp server image: no compile step, quick to pull. The tag
#: floats — pin it once something works, so a redeploy cannot silently change
#: llama.cpp versions under a working deployment.
image = (
    modal.Image.from_registry(
        "ghcr.io/ggml-org/llama.cpp:server-cuda", add_python="3.12"
    )
    .entrypoint([])  # drop the image's own entrypoint so Modal controls startup
    # Nothing the runtime needs: the proxy uses urllib from the stdlib.
    # The registry AND models.json, baked in. Modal ships only the module it
    # runs, so without this the container has `app.py` and nothing else.
    # `_REGISTRY_SRC` rather than `_HERE`: this file no longer sits beside them.
    .add_local_dir(_REGISTRY_SRC, "/app/modal_llm")
)

#: The DOWNLOAD image, deliberately not the server image. Downloading is network
#: and disk, not compute: building it from the CUDA base would make every fetch
#: pay for a multi-gigabyte image pull and inherit a GPU allocation it never
#: uses. A debian_slim base starts in seconds.
download_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("huggingface_hub[hf_transfer]", "laya>=0.4.10")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
    .add_local_dir(_REGISTRY_SRC, "/app/modal_llm")
)

registry = load(REGISTRY_PATH)
ENABLED = [mid for mid in registry.enabled_ids() if registry.get(mid).engine_type == "gguf"]

#: What a fresh deployment fetches: each GGUF role's PRIMARY only, ~47 GB rather than
#: ~150 GB for every enabled model. `ensure_model` pulls the rest on demand and
#: `volume_state` reports what is genuinely there.
ROLES = [
    role
    for role in sorted(registry.fallback)
    if registry.primary(role).engine_type == "gguf"
]
ROLE_PRIMARY = {role: registry.primary(role) for role in ROLES}


def _resolve(volume_dir: str, pattern: str) -> str:
    """The single file in a model's Volume folder matching a name or glob."""
    from pathlib import Path as _Path

    hits = sorted(_Path(MODELS_DIR, volume_dir).glob(pattern))
    if len(hits) != 1:
        raise RuntimeError(
            f"{volume_dir}: {pattern!r} matched {len(hits)} files: "
            f"{[h.name for h in hits]}"
        )
    return str(hits[0])


#: Kept as a name the download helpers use, derived from the roles' primaries.
PRIMARY_IDS = [ROLE_PRIMARY[role].id for role in ROLES]

class _LaunchedServer:
    """A running llama-server plus the handle needed to notice it died.

    Keeping the `Popen` matters: without it a container whose model process
    exits after becoming healthy answers every subsequent call with a connection
    error until it happens to scale down, which reads as "the model is broken"
    rather than "the process is gone".
    """

    def __init__(self, process, port: int):
        self.process = process
        self.port = port

    @property
    def alive(self) -> bool:
        return self.process.poll() is None


#: One entry per ROLE this container serves, keyed by model id.
#:
#: A single container runs one llama-server per role — each on its own port — so
#: both roles are served by ONE L40S instead of two. `max_containers=1` is the
#: whole point: a second container is a second card billed for a workload whose
#: second request may never come.
_SERVERS: dict = {}

#: Base port; each role gets BASE + its index in `ROLES`. Adjacent, fixed, and
#: never published, so there is nothing to configure and nothing to collide with.
_SERVER_PORT_BASE = 8081


def _launch(model, port: int) -> None:
    """Start llama-server for one model on `port` and wait until it answers.

    Blocking is required: Modal keeps the container alive while `@modal.enter()`
    runs, so a `Popen` that returned would let the function exit and the server
    die with it. The wait is where the model load is paid — on the container's
    own clock, before the first call rather than inside it.

    One process per role, each on its own port, so a single container serves
    both. That is the whole point of this shape: `max_containers=1` buys one
    L40S rather than two, and the roles time-share the card instead of each
    owning one. The cost is real and is paid in throughput — two llama-servers
    on one GPU means a reply's token rate drops while an extraction runs.
    """
    global _SERVERS

    import subprocess

    # Loopback only: nothing outside the container can reach these ports, and
    # there is no web endpoint to secure.
    cmd = ["/app/llama-server"] + model.llama_args() + [
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
    print(f"[{model.id}] launching on :{port}: {' '.join(cmd)}", flush=True)
    process = subprocess.Popen(cmd)
    started = time.time()
    deadline = started + _MODEL_LOAD_TIMEOUT_SECONDS
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"llama-server exited {process.returncode} for {model.id} "
                f"after {time.time() - started:.1f}s"
            )
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=2
            ) as response:
                if response.status == 200:
                    _SERVERS[model.id] = _LaunchedServer(process, port)
                    print(
                        f"[{model.id}] healthy on :{port} after "
                        f"{time.time() - started:.1f}s",
                        flush=True,
                    )
                    return
        except Exception:
            pass
        time.sleep(1)
    process.terminate()
    raise RuntimeError(
        f"llama-server for {model.id} did not become healthy within "
        f"{_MODEL_LOAD_TIMEOUT_SECONDS}s"
    )


#: How long a container waits for its model to load. The measured figure is
#: ~18 s for a 23.5 GB GGUF off a Modal Volume; this leaves room for a slower
#: cold volume and the first pull.
_MODEL_LOAD_TIMEOUT_SECONDS = 600

#: Modal's own startup budget for the container, which must exceed the model
#: load time or the container is killed before it ever serves.
_STARTUP_TIMEOUT_SECONDS = 900

#: Per-request ceiling inside the container. The caller's timeout is the other
#: half; too small here turns a long reply into a 500.
_REQUEST_TIMEOUT_SECONDS = 900

#: `validate_models` sweeps every registry entry's weights across the volume,
#: which on a cold gcsfuse mount is a stat per file. It has to outlast the
#: engine's own `asyncio.wait_for` (llm_engine wraps it at 300s) or the sweep
#: is abandoned and reported as a validation failure — i.e. "something is wrong
#: with your models" for a scan that merely needed longer.
VALIDATE_TIMEOUT = 600

#: The engine calls `vol.reload()` through the lifecycle helper rather than
#: reaching for the Volume object itself, so the storage classes stay free of
#: Modal specifics and this stays the only place reload is issued.
def safe_vol_reload() -> None:
    try:
        vol.reload()
    except Exception as exc:  # noqa: BLE001 - a failed reload must not be fatal
        logger.warning(f"vol.reload failed: {exc}")


def _all_registry_models() -> list:
    """Every GGUF model in the registry, enabled or not.

    Validation needs the full GGUF set: a disabled entry's weights may still be
    sitting on the volume, and "there is a file nobody declared" is exactly
    the state worth reporting.
    """
    return [m for m in registry.models.values() if m.engine_type == "gguf"]

#: Concurrent inputs per container. `parallel` in models.json is how many slots
#: llama-server opens, and WITHOUT this Modal sends one input at a time — so a
#: util container declared with `parallel: 2` would serve one request while its
#: second slot sat empty, and a long memory-extraction call would block
#: captioning and tool calls behind it. Class-level because `@modal.concurrent`
#: is not per-parameter, so it takes the widest model in the registry.
_MAX_INPUTS = max(
    (m.parallel for m in _all_registry_models() if m.enabled), default=1
) * 2

#: Scale-to-zero is class-level for a parameterized class, so it cannot be
#: per-model. Every registry entry declares the same value; reading it back is
#: what keeps models.json the one place to change it.
_IDLE_SECONDS = next(
    iter({m.idle for m in _all_registry_models() if m.enabled}), 60
)

#: GPU is class-level for a parameterized class, so it cannot be per-model.
#: Every model in the registry targets the same card; assert that rather than
#: silently picking one, because a 48 GB model on a smaller card fails at load.
_GPU = next(iter({m.gpu for m in _all_registry_models() if m.enabled}), "L40S")


def _server_for_port(port: int) -> "_LaunchedServer":
    """The running server on this port, or a clear error.

    Keyed by port rather than model id because `_proxy` and `_proxy_stream`
    receive only a port, and making them take a second argument they do not
    otherwise need is how the signature drifted out of sync in the first place.
    """
    for server in _SERVERS.values():
        if server.port == port:
            if not server.alive:
                break
            return server
    raise RuntimeError(
        f"no live llama-server on port {port}; this container serves "
        f"{sorted(_SERVERS)} and a dead one must be recycled"
    )


def _require_healthy_server(model_id: str) -> "_LaunchedServer":
    """Fail fast if this role's llama-server process is gone.

    A Modal method on a dead llama-server raises a connection error that names
    the HTTP layer, not the model. Naming the process here is what makes the
    failure diagnosable instead of a stream of connection errors.
    """
    server = _SERVERS.get(model_id)
    if server is None or not server.alive:
        raise RuntimeError(
            f"llama-server for {model_id!r} is not running in this container; "
            "the container should be recycled"
        )
    return server


def _proxy(port: int, path: str, payload: dict | None = None):
    """One call to the in-container llama-server.

    Stdlib only — `urllib.request`. A pip dependency in this image is one that
    can be missing at exactly the moment a cold container starts serving, which
    is how this function's first version failed: the image installed `httpx`,
    the code imported `requests`, and every call died with ModuleNotFoundError
    while Modal logged the container as cold-booting forever.
    """
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['LLAMA_API_KEY']}",
        },
        method="POST" if body else "GET",
    )
    _server_for_port(port)
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _proxy_stream(port: int, path: str, payload: dict, timeout: float | None = None):
    """SSE from the in-container llama-server, yielding each parsed chunk.

    `urlopen` gives a file-like object, so `readline()` is the natural SSE
    reader — no client library and no buffering layer that has to be configured
    to stop holding lines back.

    `timeout` is the caller's remaining budget. It is a read timeout on the
    socket, which is the right granularity here: llama.cpp streams tokens as it
    produces them, so a gap means the server has stalled, not that the answer
    is unusually long. Omitting it falls back to the module default.
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {os.environ['LLAMA_API_KEY']}",
        },
        method="POST",
    )
    _server_for_port(port)
    deadline = float(timeout) if timeout else _REQUEST_TIMEOUT_SECONDS
    with urllib.request.urlopen(request, timeout=deadline) as response:
        for raw in response:
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                return
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue


#: One class, parametrized by model id.
#:
#: This is what makes the registry's fallback order and the "switch models
#: without redeploying" promise real. A class bound to `ROLE_PRIMARY` at deploy
#: time can only ever serve that one model — the others would download via
#: `ensure_model` and then have nothing behind them until a redeploy. Modal
#: gives each distinct `model_id` its own container pool with its own lifecycle,
#: so every model still scales to zero on its own, with no URLs involved.
#: ONE class, ONE container, one llama-server per role.
#:
#: This is the shape that buys a single L40S instead of two. The parameterized
#: version before it gave each `model_id` its own container pool — which is what
#: made every model routable, and what made each role a separate card. With the
# `util` primary now a 12B (9.3 GB with vision, verified against the HuggingFace
# API) instead of a second 31B (47.7 GB of weights total), both models fit one
# card: roughly 40.6 GB of the ~46.7 GB usable, with `--swa-full` OFF — turning
# it on makes Artemis's KV cache ~15.7 GB and nothing fits.
#:
#: The cost is throughput, not correctness. Two llama-servers on one GPU means a
# reply's token rate dips while an extraction runs. For a single user who is
# mostly waiting on one reply at a time, that is the cheaper trade.
@app.cls(
    image=image,
    gpu=_GPU,
    volumes={MODELS_DIR: vol},
    secrets=[modal.Secret.from_name("tnh-llm-key")],
    scaledown_window=_IDLE_SECONDS,
    max_containers=1,
    timeout=60 * 60,
    startup_timeout=_STARTUP_TIMEOUT_SECONDS,
)
@modal.concurrent(max_inputs=_MAX_INPUTS)
class ChatLLM:
    """Serve every role from ONE container, one llama-server per role."""

    #: role -> model id this container is running. Filled on enter.
    serving: dict = {}

    #: role -> why it is not serving. A role with no weights is a permanent
    #: configuration state, so it is reported rather than crashed on — see
    #: `start`.
    unavailable: dict = {}

    @modal.enter()
    def start(self):
        """Load one llama-server per DISTINCT model, and map every role to it.

        A role per model, not a role per server. When `rp` and `util` resolve to
        the same weights — which is the whole point of the shared-model setting —
        one server serves both and the second is never started: launching the
        same 24.7 GB GGUF twice would double the VRAM for no gain. Distinct
        models still get their own server on their own port, so the container
        holds whichever combination the registry asks for.

        A model with no weights, or one not in the registry, is recorded in
        `unavailable` rather than raised. Raising makes Modal retry enter and
        re-create the container on every call, so a missing download becomes an
        infinite crash-loop burning GPU on something that can never succeed.
        """
        self.serving = {}
        self.unavailable = {}
        # Before any model loads — see `_refresh_volume`.
        _refresh_volume()

        # Distinct models across every role, in registry order for a stable
        # port assignment.
        distinct: list[str] = []
        for role in ROLES:
            model_id = ROLE_PRIMARY[role].id
            if model_id not in distinct:
                distinct.append(model_id)

        for index, model_id in enumerate(distinct):
            port = _SERVER_PORT_BASE + index
            try:
                model = registry.get(model_id)
            except KeyError:
                self.unavailable[model_id] = (
                    f"{model_id!r} is not in the baked-in registry; add it to "
                    "models.json and redeploy"
                )
                continue
            if not _present(model):
                self.unavailable[model_id] = (
                    f"{model_id!r} has no weights on the Volume; run "
                    "`modal run deployables/modal/llm/app.py::ensure --model-id <id>` first"
                )
                continue
            _launch(model, port)

        for role in ROLES:
            model_id = ROLE_PRIMARY[role].id
            if model_id in _SERVERS:
                self.serving[role] = model_id
        print(
            f"serving: {self.serving}; servers on "
            f"{ {mid: sv.port for mid, sv in _SERVERS.items()} }",
            flush=True,
        )

    # ------------------------------------------------------------------
    def _resolve_model_id(self, model_id: str) -> str:
        """Map role aliases ('rp', 'util', 'default') to served model IDs."""
        if not model_id or model_id in ("default", ""):
            return self._default_model()
        if model_id in self.serving:
            return self.serving[model_id]
        return model_id

    def _resolve(self, model_id: str) -> int:
        """The port serving `model_id`, or a clear non-retryable error.

        Not retryable on purpose: an unknown or unserved model is a
        configuration state, so a caller should fail rather than back off.
        """
        resolved = self._resolve_model_id(model_id)
        server = _SERVERS.get(resolved)
        if server is not None and resolved in self.serving.values():
            return server.port
        reason = self.unavailable.get(resolved) or self.unavailable.get(model_id)
        if reason:
            raise RuntimeError(reason)
        raise RuntimeError(
            f"{model_id!r} is not served by this container; it serves "
            f"{sorted(self.serving.values())}"
        )

    @staticmethod
    def _role_for(model_id: str) -> str | None:
        try:
            return registry.get(model_id).role
        except KeyError:
            return None

    @modal.method()
    def complete(self, messages: list, sampler: dict | None = None,
                 model_id: str = "") -> dict:
        """One-shot completion. Returns the full parsed response."""
        resolved = self._resolve_model_id(model_id)
        port = self._resolve(resolved)
        payload = {"model": resolved, "messages": messages, "stream": False}
        if sampler:
            payload.update(sampler)
        return _proxy(port, "/v1/chat/completions", payload)

    @modal.method(is_generator=True)
    def stream(self, messages: list, sampler: dict | None = None,
               model_id: str = ""):
        """Streamed completion, yielding each SSE chunk as a dict.

        A generator method, consumed with `.remote_gen()` over the Modal SDK —
        which is why there is no HTTP endpoint to secure at all.
        """
        resolved = self._resolve_model_id(model_id)
        port = self._resolve(resolved)
        payload = {"model": resolved, "messages": messages, "stream": True}
        if sampler:
            payload.update(sampler)
        yield from _proxy_stream(port, "/v1/chat/completions", payload)

    @modal.method()
    def health(self) -> dict:
        """Every role's reachability, including the ones not downloaded.

        A role with no weights answers `not_downloaded` with its reason rather
        than raising, so a caller polling health sees an actionable state
        instead of a crash-loop it has to infer from retries.

        Roles that share a server report the same port, which is the point — and
        what makes the shared-model setting visible rather than something you
        have to infer from two llama-servers being absent.
        """
        out: dict = {"app": APP_NAME, "roles": {}, "servers": {}}
        for model_id, server in _SERVERS.items():
            out["servers"][model_id] = {"port": server.port, "alive": server.alive}
        for role in ROLES:
            model_id = ROLE_PRIMARY[role].id
            if model_id in self.unavailable:
                out["roles"][role] = {
                    "status": "not_downloaded",
                    "model_id": model_id,
                    "reason": self.unavailable[model_id],
                }
                continue
            server = _SERVERS.get(model_id)
            if server is None:
                out["roles"][role] = {"status": "unknown", "model_id": model_id}
                continue
            port = server.port
            try:
                out["roles"][role] = {
                    "status": "ok",
                    "model_id": model_id,
                    "port": port,
                    **_proxy(port, "/health"),
                }
            except Exception as exc:
                out["roles"][role] = {
                    "status": "unhealthy",
                    "model_id": model_id,
                    "reason": str(exc),
                }
        return out

    @staticmethod
    def _default_model() -> str:
        """The rp role's model, for a caller that does not name one."""
        return ROLE_PRIMARY["rp"].id if "rp" in ROLE_PRIMARY else PRIMARY_IDS[0]

    # ------------------------------------------------------------------
    # The dispatch entry point. `ModalLlamaCPPEngine` calls exactly this:
    #
    #   instance.generate.remote_gen.aio(
    #       model_id, messages, tools, timeout, sampling or None)
    #
    # It did not exist. The engine looked it up on an unhydrated class, which
    # raises `NotFoundError: Class has no method generate` at hydration — so
    # every LLM job on a `modal_llm` provider failed at first dispatch, for
    # every provider, in a way `check_health` (config-only) could not see.
    # `complete`/`stream` are the same capability under different names and
    # different signatures; `generate` is the canonical one and the others are
    # kept because the CLI entrypoints use them.
    #
    # It yields CANONICAL TaskEvents, not raw SSE chunks: the engine's reducer
    # (`provider_client._LLMReducer`) accumulates `delta` and finishes on
    # `completed`. It also understands the legacy `{"status": ...}` dialect, but
    # emitting canonical events from the start keeps one code path.
    # ------------------------------------------------------------------
    @modal.method(is_generator=True)
    def generate(
        self,
        model_id: str,
        messages: list,
        tools: list | None = None,
        timeout: float | None = None,
        sampling: dict | None = None,
    ):
        """Stream one chat completion as canonical TaskEvents.

        `timeout` is the backend's remaining budget, forwarded to llama.cpp so
        the in-container server gives up at the same deadline the backend will
        rather than holding a GPU slot past it.
        """
        resolved = self._resolve_model_id(model_id)
        try:
            port = self._resolve(resolved)
        except Exception as exc:
            # A model this container does not serve is a permanent
            # configuration state, not a blip: retrying it across the pool
            # cannot succeed.
            yield {
                "event": "failed",
                "message": str(exc),
                "retryable": False,
            }
            return

        payload: dict = {"model": resolved, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        # The backend's sampler keys are its own; llama.cpp speaks the OpenAI
        # names. `max_output_tokens` is ours and is NOT forwarded under that
        # name — forwarded verbatim it is ignored, so the engine would sit at
        # llama.cpp's default length and the chat would truncate silently.
        for backend_key, upstream_key in _SAMPLER_KEY_MAP.items():
            if sampling and sampling.get(backend_key) is not None:
                payload[upstream_key] = sampling[backend_key]

        full_content = ""
        tool_calls: list[dict] = []
        try:
            for chunk in _proxy_stream(port, "/v1/chat/completions", payload,
                                       timeout=timeout):
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        full_content += text
                        yield {"event": "delta", "text": text}
                    for call in delta.get("tool_calls") or []:
                        index = call.get("index", 0)
                        while len(tool_calls) <= index:
                            tool_calls.append({
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            })
                        if call.get("id"):
                            tool_calls[index]["id"] = call["id"]
                        if call.get("type"):
                            tool_calls[index]["type"] = call["type"]
                        function = call.get("function") or {}
                        if function.get("name"):
                            tool_calls[index]["function"]["name"] = function["name"]
                        if function.get("arguments"):
                            tool_calls[index]["function"]["arguments"] += function["arguments"]
        except Exception as exc:
            yield {
                "event": "failed",
                "message": f"llama.cpp generation failed: {exc}",
                "retryable": not isinstance(exc, RuntimeError),
            }
            return

        output: dict = {"role": "assistant", "content": full_content}
        if tool_calls:
            output["tool_calls"] = tool_calls
        yield {"event": "completed", "outputs": [output]}


#: Backend sampler key -> the OpenAI-compatible name llama.cpp expects. Keys
#: absent from this map are NOT forwarded: `max_output_tokens` in particular is
#: a backend name with no upstream equivalent, and passing it through unused is
#: how a chat silently truncates at llama.cpp's default.
_SAMPLER_KEY_MAP = {
    "temperature": "temperature",
    "top_p": "top_p",
    "max_output_tokens": "max_tokens",
    "frequency_penalty": "frequency_penalty",
    "presence_penalty": "presence_penalty",
}


# ---------------------------------------------------------------------------
# Weight download. CPU-only, on the slim image, so fetching never spends GPU.
#
# Default is the two PRIMARIES, not "every enabled model". A fresh deployment
# then fetches ~35 GB instead of ~150 GB, and the rest is pulled on demand by
# `ensure_model` when a user actually selects it — which `volume_state` makes
# visible, so the UI can show "not downloaded" rather than failing a job.
# ---------------------------------------------------------------------------
@app.function(
    image=download_image,
    volumes={MODELS_DIR: vol},
    timeout=6 * 3600,
    # No `gpu=`, and the image is slim: this is a network-and-disk function.
    # Keeping it off the server image is what stops a download from inheriting
    # a multi-gigabyte CUDA pull and an idle GPU allocation.
)
def download(key: str = ""):
    """Fetch weights into the Volume.

    `key` selects what: a model id, a role name, or "" for the two primaries.
    Anything else is a hard error rather than a silent no-op, because a typo
    here is how a deployment ends up with weights nobody meant to fetch.
    """
    from huggingface_hub import snapshot_download

    targets = _download_targets(key)
    done = set()
    for model in targets:
        if getattr(model, "engine_type", None) == "system1_laya":
            marker = (model.volume_dir, model.repo, "laya")
            if marker in done:
                continue
            done.add(marker)
            print(f"[{model.id}] {model.repo} :: snapshot (laya)", flush=True)
            snapshot_download(
                model.repo,
                local_dir=f"{MODELS_DIR}/{model.volume_dir}",
            )
            print(f"   ok laya snapshot {model.volume_dir}", flush=True)
            continue
        jobs = [(model.repo, model.gguf)]
        if model.mmproj:
            jobs.append((model.mmproj_repo or model.repo, model.mmproj))
        for repo, pattern in jobs:
            marker = (model.volume_dir, repo, pattern)
            if marker in done:
                continue
            done.add(marker)
            print(f"[{model.id}] {repo} :: {pattern}", flush=True)
            snapshot_download(
                repo,
                allow_patterns=[pattern],
                local_dir=f"{MODELS_DIR}/{model.volume_dir}",
            )
            resolved = _resolve(model.volume_dir, pattern)
            print(
                f"   ok {Path(resolved).name} "
                f"{Path(resolved).stat().st_size / 1e9:.1f} GB",
                flush=True,
            )
    vol.commit()
    return [m.id for m in targets]


def _download_targets(key: str) -> list:
    """Which models a `download` call should fetch, or raise on a bad key."""
    key = (key or "").strip()
    if not key:
        return [registry.get(mid) for mid in PRIMARY_IDS]
    if key in registry.models:
        return [registry.get(key)]
    if key in registry.fallback:
        return registry.enabled_for(key)
    raise SystemExit(
        f"unknown key {key!r}: expected a model id, a role "
        f"({sorted(registry.fallback)}), or '' for the primaries "
        f"{PRIMARY_IDS}"
    )


@app.function(image=download_image, volumes={MODELS_DIR: vol}, timeout=6 * 3600)
def ensure_model(model_id: str) -> dict:
    """Fetch ONE model if it is missing, and say whether it fetched.

    This is the on-demand path: a user picks a model in the UI, the UI asks for
    it, and this pulls the weights. Returning the same shape as `volume_state`
    means the response is directly renderable.

    A model already present answers without downloading — calling this twice is
    free, which is what makes it safe to drive from a button.
    """
    from huggingface_hub import snapshot_download

    try:
        model = registry.get(model_id)
    except KeyError:
        return {"ok": False, "model_id": model_id, "reason": "not_in_registry"}

    # This container holds no model files, so a reload is safe and needed —
    # another container may have committed since this one last looked.
    _refresh_volume()
    if _present(model):
        return {"ok": True, "model_id": model_id, "downloaded": False, **_size(model)}

    if getattr(model, "engine_type", None) == "system1_laya":
        print(f"[{model_id}] {model.repo} :: snapshot (laya)", flush=True)
        snapshot_download(
            model.repo,
            local_dir=f"{MODELS_DIR}/{model.volume_dir}",
        )
        if not _present(model):
            return {
                "ok": False,
                "model_id": model_id,
                "reason": "download_left_nothing",
            }
        vol.commit()
        return {"ok": True, "model_id": model_id, "downloaded": True, **_size(model)}

    jobs = [(model.repo, model.gguf)]
    if model.mmproj:
        jobs.append((model.mmproj_repo or model.repo, model.mmproj))
    for repo, pattern in jobs:
        print(f"[{model_id}] {repo} :: {pattern}", flush=True)
        snapshot_download(
            repo,
            allow_patterns=[pattern],
            local_dir=f"{MODELS_DIR}/{model.volume_dir}",
        )
    if not _present(model):
        # The download "succeeded" but the file is not there. That is the
        # glob-matched-nothing case, and reporting success here is how a model
        # becomes permanently un-startable with no error anywhere.
        return {
            "ok": False,
            "model_id": model_id,
            "reason": "download_left_nothing",
            "expected": model.gguf,
        }
    vol.commit()
    return {"ok": True, "model_id": model_id, "downloaded": True, **_size(model)}


@app.function(image=download_image, volumes={MODELS_DIR: vol}, timeout=300)
def volume_state() -> dict:
    """What is ACTUALLY on the Volume, per registry model.

    The honest answer to "can this model start?", which the registry can't give:
    `enabled: true` says a model is *deployed*, not that its weights exist. A
    model switched to without a download fails in the container with a path
    error that does not name the model, so the UI needs this to show
    "not downloaded yet" instead.
    """
    out: dict = {"models": {}, "primaries": PRIMARY_IDS}
    for model_id in ENABLED:
        model = registry.get(model_id)
        entry = {"present": _present(model)}
        if entry["present"]:
            entry.update(_size(model))
        out["models"][model_id] = entry
    return out


# ---------------------------------------------------------------------------
# The model-file surface `ModalLlamaCPPEngine` declares it owns.
#
# `registry.py` sets `manages_model_files: True` for `modal_llm`, which is what
# turns on reconciliation, the maintenance browse and the provider page's setup
# button. All three then call names this app did not define: `FileStorage`,
# `list_models_with_metadata`, `download_model`, `validate_models`,
# `setup_models`. Not one of them existed — the engine inherited them from the
# image engine's shape without the image app's implementation coming with it.
# Reconciliation fanned out over ComfyUI's sixteen MODEL_DIRECTORIES and every
# one raised `NotFoundError`.
#
# Paths are rooted at `/mnt/data`, which is what the engine's convention
# expects (`ModalLlamaCPPEngine._MODEL_DIRS == ("models",)`, so it lists the
# `models/` subtree). The Volume is mounted at BOTH `/models` — unchanged, for
# the llama-server and the download helpers, which address
# `/models/<volume_dir>/<gguf>` — and `/mnt/data/models`, so one Volume answers
# both addressing schemes without a copy or a symlink that a Modal redeploy
# would not reproduce.
# ---------------------------------------------------------------------------

#: Where the engine's paths resolve. `STORAGE_ROOT + "models"` is the same
#: Volume mount as `MODELS_DIR`.
STORAGE_ROOT = "/mnt/data"
_STORAGE_IMAGE_TIMEOUT = 3600


def _storage_volumes() -> dict:
    return {MODELS_DIR: vol, f"{STORAGE_ROOT}/models": vol}


@app.cls(
    image=image,
    volumes=_storage_volumes(),
    timeout=300,
    max_containers=1,
    scaledown_window=5,
)
class FileStorage:
    """Volume file operations for the LLM weights tree.

    Byte-for-byte the contract `ModalEngine` publishes for the image app, and
    the engine reads it through the same `file_size` / `read_file_range` /
    `put_file` / `delete_file` calls.
    """

    @modal.method()
    def file_size(self, path: str) -> int:
        """Size of a file in bytes. Raises `FileNotFoundError` if absent."""
        import os

        safe_vol_reload()
        full_path = get_safe_path(STORAGE_ROOT, path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {path}")
        return os.path.getsize(full_path)

    @modal.method()
    def read_file_range(self, path: str, offset: int, length: int) -> bytes:
        """Read at most `length` bytes from `offset`.

        Ranged rather than whole-file because a modal method serialises its
        return value across the RPC boundary: a 24 GB GGUF read whole is 24 GB
        in this container and 24 GB in the caller before anyone can do anything
        with it. `offset` is validated rather than trusted — a negative offset
        is an absolute seek.
        """
        import os

        if offset < 0 or length < 0:
            raise ValueError("offset and length must be non-negative")
        if length == 0:
            return b""

        safe_vol_reload()
        full_path = get_safe_path(STORAGE_ROOT, path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {path}")

        with open(full_path, "rb") as handle:
            handle.seek(offset)
            return handle.read(length)

    @modal.method()
    def put_file(self, path: str, content: bytes) -> bool:
        """Write bytes, creating parents. Used for GGUF uploads."""
        import os

        safe_vol_reload()
        full_path = get_safe_path(STORAGE_ROOT, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as handle:
            handle.write(content)
        vol.commit()
        return True

    @modal.method()
    async def delete_file(self, path: str) -> bool:
        """Remove a file and any pipeline sidecars beside it."""
        import asyncio
        import os

        safe_vol_reload()
        full_path = get_safe_path(STORAGE_ROOT, path)
        if not os.path.exists(full_path) and not list(pending_download_paths(full_path)):
            return False

        try:
            if os.path.exists(full_path):
                os.remove(full_path)
            for sidecar in pipeline_artifacts(full_path):
                if os.path.exists(sidecar):
                    os.remove(sidecar)
            vol.commit()
            return True
        except OSError:
            # A volume commit can race another container's write. Retrying the
            # unlink alone is the whole fix; a raise here would surface as a
            # provider failure for what is a transient FS conflict.
            await asyncio.sleep(0.5)
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
                vol.commit()
                return True
            except OSError:
                return False


@app.function(
    image=image,
    volumes=_storage_volumes(),
    timeout=_STORAGE_IMAGE_TIMEOUT,
)
@modal.concurrent(max_inputs=20, target_inputs=10)
async def list_models_with_metadata(directory: str) -> list:
    """Every file under `directory`, with size and type.

    The shape `normalize_validation_result` and the reconciler both expect: a
    flat list of `{name, path, type, size}`. `directory` is relative to
    `/mnt/data` and rejected if it escapes it.
    """
    import os

    safe_vol_reload()
    root = get_safe_path(STORAGE_ROOT, directory or "models")
    if not os.path.isdir(root):
        return []

    out: list = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            out.append({
                "name": name,
                "path": os.path.relpath(full, STORAGE_ROOT),
                "type": name.rsplit(".", 1)[-1].lower() if "." in name else "",
                "size": size,
            })
    return sorted(out, key=lambda entry: entry["path"])


@app.function(
    image=download_image,
    volumes=_storage_volumes(),
    timeout=6 * 3600,
)
@modal.concurrent(max_inputs=1, target_inputs=1)
async def download_model(url: str, path: str, token: str | None = None,
                         preview_url: str | None = None, metadata: dict | None = None):
    """Fetch one file into the volume. The engine's universal download entry."""
    await download_model_to_path(url, get_safe_path(STORAGE_ROOT, path), token=token)
    return {"ok": True, "path": path, **(metadata or {})}


@app.function(
    image=image,
    volumes=_storage_volumes(),
    timeout=VALIDATE_TIMEOUT,
)
@modal.concurrent(max_inputs=10, target_inputs=5)
async def validate_models(directories: list[str], delete_invalid: bool = False):
    """Classify every file under `directories` as valid / partial / invalid.

    Returns the totals contract `normalize_validation_result` reads:
    `total_valid` / `total_invalid` / `total_partial`, plus the per-directory
    breakdown. A GGUF is "partial" when it is smaller than the registry entry
    says it should be — the failure mode an interrupted download leaves behind,
    and the one that otherwise presents as a model that simply will not load.
    """
    import os

    safe_vol_reload()
    expected: dict[str, int] = {}
    for model in _all_registry_models():
        if model.gguf:
            expected[model.gguf] = model.size or 0

    valid: list = []
    partial: list = []
    invalid: list = []
    by_directory: dict = {}

    for directory in directories or ["models"]:
        roots = [get_safe_path(STORAGE_ROOT, directory)]
        seen_valid: list = []
        seen_partial: list = []
        seen_invalid: list = []
        for root in roots:
            if not os.path.isdir(root):
                continue
            for dirpath, _dirnames, filenames in os.walk(root):
                for name in filenames:
                    if not is_model_candidate(name):
                        continue
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, STORAGE_ROOT)
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        continue
                    if size == 0:
                        seen_invalid.append(rel)
                        if delete_invalid:
                            try:
                                os.remove(full)
                            except OSError:
                                pass
                        continue
                    floor = expected.get(name, 0)
                    if floor and size < floor:
                        seen_partial.append(rel)
                    else:
                        seen_valid.append(rel)
        valid.extend(seen_valid)
        partial.extend(seen_partial)
        invalid.extend(seen_invalid)
        by_directory[directory] = {
            "valid": seen_valid,
            "partial": seen_partial,
            "invalid": seen_invalid,
        }

    vol.commit()
    return {
        "status": "ok",
        "valid": valid,
        "partial": partial,
        "invalid": invalid,
        "by_directory": by_directory,
        "total_valid": len(valid),
        "total_partial": len(partial),
        "total_invalid": len(invalid),
        "total_indeterminate": 0,
    }


@app.function(
    image=image,
    volumes=_storage_volumes(),
    timeout=600,
)
@modal.concurrent(max_inputs=10, target_inputs=5)
def setup_models():
    """Create the storage layout the reconciler expects to find.

    Deliberately NOT a weight fetch. `modal_llm` pulls weights through
    `ensure_model`, which only fetches the primaries and pulls the rest on
    demand — seeding the provider page's setup button with a multi-GB download
    would spend the user's money on weights they may never select. This only
    makes the tree exist so a listing returns [] rather than raising.
    """
    import os

    safe_vol_reload()
    os.makedirs(f"{STORAGE_ROOT}/models", exist_ok=True)
    vol.commit()
    return {"ok": True, "directories": ["models"]}


def _refresh_volume() -> None:
    """Refresh this process's view of the Volume. Call ONCE, before any model
    is loaded.

    A Modal Volume is a cache in front of object storage, so a file committed
    by *another* container — which is what `ensure_model` does from its own
    short-lived instance — is invisible until this process reloads.

    The timing is load-bearing, and getting it wrong is a crash-loop. `reload()`
    fails with `ConflictError: there are open files preventing the operation` as
    soon as ANY model file is held open, and a loaded llama-server mmaps its
    weights and holds them for the container's life. So this must run before
    the first `_launch`, not between two of them: calling it while checking the
    second role's weights — which is what the first version of this did — dies
    after the first role loads, and `@modal.enter()` failing makes Modal
    re-create the container forever.
    """
    try:
        vol.reload()
    except Exception as exc:
        # A reload failure is not fatal on its own: the volume may already be
        # current, and a model whose weights ARE local still works. The one case
        # that matters is a genuinely stale view reporting a present model as
        # absent, and that surfaces as `not_downloaded` from health rather than
        # as a lost model.
        print(f"volume reload skipped: {exc}", flush=True)


def _present(model) -> bool:
    """Is the model's GGUF (and projector, if it has one) or Laya directory on the Volume?

    Pure filesystem — no reload, so it is safe to call at any point in the
    container's life, including while a model is loaded. Refresh first with
    `_refresh_volume()`.
    """
    if getattr(model, "engine_type", None) == "system1_laya":
        target = Path(MODELS_DIR, model.volume_dir)
        return target.is_dir() and any(target.iterdir())
    for pattern in filter(None, [model.gguf, model.mmproj]):
        try:
            _resolve(model.volume_dir, pattern)
        except RuntimeError:
            return False
    return True


def _size(model) -> dict:
    """Byte size of the model's files, 0 when unreadable."""
    total = 0
    if getattr(model, "engine_type", None) == "system1_laya":
        target = Path(MODELS_DIR, model.volume_dir)
        if target.is_dir():
            for p in target.rglob("*"):
                if p.is_file():
                    total += p.stat().st_size
        return {"bytes": total, "gb": round(total / 1e9, 2)}
    for pattern in filter(None, [model.gguf, model.mmproj]):
        try:
            total += Path(_resolve(model.volume_dir, pattern)).stat().st_size
        except RuntimeError:
            continue
    return {"bytes": total, "gb": round(total / 1e9, 2)}


@app.function(
    image=download_image,
    volumes={MODELS_DIR: vol},
    timeout=120,
    cpu=2,
    memory="2Gi",
)
def evaluate_decisions(
    model_id: str,
    context_text: str,
    questions: dict | list,
) -> dict:
    """Evaluate parallel typed decisions using Laya on CPU without GPU billing."""
    import time
    import laya  # type: ignore

    t0 = time.perf_counter()
    _refresh_volume()
    repo_or_dir = model_id
    try:
        model_entry = registry.get(model_id)
        if getattr(model_entry, "engine_type", None) == "system1_laya":
            local_dir = Path(MODELS_DIR, model_entry.volume_dir)
            if local_dir.is_dir() and any(local_dir.iterdir()):
                repo_or_dir = str(local_dir)
            elif model_entry.repo:
                repo_or_dir = model_entry.repo
    except Exception:
        pass

    laya_model = laya.load(repo_or_dir, device="cpu")

    if isinstance(questions, dict):
        q_list = [{"key": k, **v} for k, v in questions.items() if isinstance(v, dict)]
    elif isinstance(questions, list):
        q_list = [q for q in questions if isinstance(q, dict) and "key" in q]
    else:
        q_list = []

    questions_dict: dict = {}
    min_rubric_val: dict = {}
    for q in q_list:
        key = q["key"]
        q_type = q.get("type")
        if q_type == "choice":
            opts = q.get("options")
            criteria = opts if isinstance(opts, (list, dict)) else []
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

    raw_result = laya_model.predict(context_text, questions_dict)
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    raw_answers = raw_result.get("answers", {}) if isinstance(raw_result, dict) else {}
    answers: dict = {}
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

    return {
        "status": "success",
        "model_id": model_id,
        "engine_used": "modal_laya_cpu",
        "provider_tier": "modal_laya",
        "latency_ms": latency_ms,
        "answers": answers,
        "results": answers,
    }


@app.local_entrypoint()
def main(key: str = ""):
    """`modal run deployables/modal/llm/app.py [--key <id|role>]` — download weights.

    With no key this fetches the two primaries only, and says so, so a bare
    `modal run deployables/modal/llm/app.py` cannot be mistaken for "everything is ready".
    """
    fetched = download.remote(key)
    print(f"fetched: {fetched}")


@app.local_entrypoint()
def ensure(model_id: str):
    """`modal run deployables/modal/llm/app.py::ensure --model-id <id>` — fetch one model."""
    result = ensure_model.remote(model_id)
    print(f"{model_id}: {result}")


@app.local_entrypoint()
def presence():
    """`modal run deployables/modal/llm/app.py::presence` — what is on the Volume."""
    print(json.dumps(volume_state.remote(), indent=2))


@app.local_entrypoint()
def urls():
    """Print the JSON manifest the backend needs.

    One container, one llama-server per role, so the manifest is a role ->
    model-id table plus the samplers. There are no URLs at all: the app exposes
    no HTTP surface, and the backend calls the Modal SDK class by role:
        modal.Cls.from_name("tnh-llm", "ChatLLM")()
    """
    manifest: dict = {
        "app": APP_NAME,
        "cls": "ChatLLM",
        "container": "one per deployment, max_containers=1",
        "roles": {},
        "models": {},
    }
    for role in sorted(registry.fallback):
        manifest["roles"][role] = ROLE_PRIMARY[role].id
        for model in registry.enabled_for(role):
            manifest["models"][model.id] = {
                "id": model.id,
                "role": model.role,
                "vision": model.has_vision,
                "ctx_per_slot": model.ctx,
                "parallel": model.parallel,
                "sampler": model.sampler,
                "repo": model.repo,
            }
    print(json.dumps(manifest, indent=2))


@app.local_entrypoint()
def bench(key: str = ""):
    """Time a cold start. Run when the container has been idle long enough to
    scale to zero, or it measures nothing.

    Covers both roles, because one container now serves both — which is exactly
    the number worth knowing: it is the single cold boot the caller pays.
    """
    t0 = time.time()
    result = ChatLLM().health.remote()
    print(json.dumps(result, indent=2))
    print(f"\ncold container answering both roles: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    print(json.dumps(
        {
            "roles": {role: ROLE_PRIMARY[role].id for role in ROLES},
            "enabled": ENABLED,
        },
        indent=2,
    ))
