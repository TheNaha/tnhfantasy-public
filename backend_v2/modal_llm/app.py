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
    modal run modal_llm/app.py              # download the two role primaries
    modal deploy modal_llm/app.py
    modal run modal_llm/app.py::urls        # manifest for the backend
    modal run modal_llm/app.py::bench --key artemis_31b   # cold-start timer

Call a model:
    cls = modal.Cls.from_name("tnh-llm", "ChatLLM")
    cls(model_id="artemis_31b").complete.remote([{...}])
    # or, streamed:
    for chunk in cls(model_id="artemis_31b").stream.remote_gen([{...}]):
        ...

To add a model to rotation: add it to models.json, then
    modal run modal_llm/app.py::ensure --model-id <id>`   # fetch weights
    modal deploy modal_llm/app.py                          # make it routable
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
import os
import sys
import time
import urllib.request
from pathlib import Path

import modal

# `registry.py` and `models.json` sit beside this file. Modal uploads ONLY the
# module it runs — `app.py` becomes `/root/app.py` and its siblings do not come
# with it — so locally this import works and remotely it dies with
# `ModuleNotFoundError: No module named 'registry'`, on every function, at
# hydrate time. Both images therefore ADD this directory, and the import looks
# there first. Discovering it at runtime rather than hard-coding `/app/...`
# keeps the file runnable locally too.
_HERE = Path(__file__).resolve().parent
_REMOTE_LLM_DIR = Path("/app/modal_llm")

for _candidate in (_REMOTE_LLM_DIR if _REMOTE_LLM_DIR.is_dir() else None, _HERE):
    if _candidate and (_candidate / "registry.py").is_file():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from registry import REGISTRY_PATH, load  # noqa: E402

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
    .add_local_dir(_HERE, "/app/modal_llm")
)

#: The DOWNLOAD image, deliberately not the server image. Downloading is network
#: and disk, not compute: building it from the CUDA base would make every fetch
#: pay for a multi-gigabyte image pull and inherit a GPU allocation it never
#: uses. A debian_slim base starts in seconds.
download_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("huggingface_hub[hf_transfer]")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
    .add_local_dir(_HERE, "/app/modal_llm")
)

registry = load(REGISTRY_PATH)
ENABLED = registry.enabled_ids()

#: What a fresh deployment fetches: each role's PRIMARY only, ~47 GB rather than
#: ~150 GB for every enabled model. `ensure_model` pulls the rest on demand and
#: `volume_state` reports what is genuinely there.
ROLES = sorted(registry.fallback)
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

#: GPU and container budget. ONE container per role, one input at a time.
#:
#: `max_containers=1` is the whole point for a single-user app: two containers
#: of an L40S is twice the bill for a workload where the second request never
#: happens. The role's `parallel` in models.json is slot parallelism INSIDE one
#: llama-server, not extra containers, so it does not need to be honoured here.
_MAX_CONTAINERS_PER_ROLE = 1


def _launch(model) -> None:
    """Start llama-server for one model.

    Blocking is required: Modal keeps the container alive while `@modal.enter()`
    runs, so a `Popen` that returned would let the function exit and the server
    die with it. Wait for the port to answer so the first real call is fast —
    that is where the ~16 s model load goes, and it happens on the container's
    own clock rather than inside the caller's request.
    """
    import subprocess

    cmd = ["/app/llama-server"] + model.llama_args() + [
        "--host", "127.0.0.1",  # loopback only; nothing outside the container
        "--port", str(PORT),
    ]
    print(f"[{model.id}] launching: {' '.join(cmd)}", flush=True)
    process = subprocess.Popen(cmd)
    deadline = time.time() + _MODEL_LOAD_TIMEOUT_SECONDS
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"llama-server exited {process.returncode} for {model.id}")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/health", timeout=2
            ) as response:
                if response.status == 200:
                    print(f"[{model.id}] healthy after {time.time() - (deadline - _MODEL_LOAD_TIMEOUT_SECONDS):.1f}s", flush=True)
                    return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(
        f"llama-server for {model.id} did not become healthy within "
        f"{_MODEL_LOAD_TIMEOUT_SECONDS}s"
    )


#: How long a container will wait for its model to load before giving up. The
#: measured figure is ~16 s for a 23.5 GB GGUF off a Modal Volume; this leaves
#: room for a slower cold volume and for the first pull.
_MODEL_LOAD_TIMEOUT_SECONDS = 600

#: Modal's own startup budget for the container, which must exceed the model
#: load time or the container is killed before it ever serves.
_STARTUP_TIMEOUT_SECONDS = 900


def _proxy(path: str, payload: dict | None = None):
    """One call to the in-container llama-server.

    Stdlib only — `urllib.request`, no `requests`, no `httpx`. A pip dependency
    in this image is a dependency that can be missing at exactly the moment a
    cold container starts serving, which is how this function's first version
    failed: the image installed `httpx`, the code imported `requests`, and every
    call died with ModuleNotFoundError while Modal logged the container as
    cold-booting in a loop. Nothing to install means nothing to be missing.

    Loopback only, and authenticated with the same LLAMA_API_KEY llama-server
    was started with, because nothing outside the container can reach it.
    """
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['LLAMA_API_KEY']}",
        },
        method="POST" if body else "GET",
    )
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _proxy_stream(path: str, payload: dict):
    """SSE from the in-container llama-server, yielding each parsed chunk.

    `urlopen` gives a file-like object, so `readline()` is the natural SSE
    reader — no client library required, and no buffering layer that has to be
    configured to stop holding lines back.
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {os.environ['LLAMA_API_KEY']}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
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


#: Per-request ceiling inside the container. The caller's own timeout is the
#: other half; a value here that is too small turns a long reply into a 500.
_REQUEST_TIMEOUT_SECONDS = 900


class _LaunchedServer:
    """A running llama-server plus the handle needed to notice it died.

    Keeping the `Popen` matters: without it a container whose model process
    exits after becoming healthy answers every subsequent call with a connection
    error until it happens to scale down, which reads as "the model is broken"
    rather than "the process is gone".
    """

    def __init__(self, process):
        self.process = process

    @property
    def alive(self) -> bool:
        return self.process.poll() is None


#: One per container. `@modal.enter()` sets it; the methods check it.
_SERVER: _LaunchedServer | None = None


def _launch(model) -> None:
    """Start llama-server for one model and wait until it answers.

    Blocking is required: Modal keeps the container alive while `@modal.enter()`
    runs, so a `Popen` that returned would let the function exit and the server
    die with it. The wait is where the ~18 s model load is paid — on the
    container's own clock, before the first call rather than inside it.
    """
    global _SERVER

    import subprocess

    # Loopback only: nothing outside the container can reach this port, and
    # there is no web endpoint to secure.
    cmd = ["/app/llama-server"] + model.llama_args() + [
        "--host", "127.0.0.1",
        "--port", str(PORT),
    ]
    print(f"[{model.id}] launching: {' '.join(cmd)}", flush=True)
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
                f"http://127.0.0.1:{PORT}/health", timeout=2
            ) as response:
                if response.status == 200:
                    _SERVER = _LaunchedServer(process)
                    print(
                        f"[{model.id}] healthy after {time.time() - started:.1f}s",
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

#: Concurrent inputs per container. `parallel` in models.json is how many slots
#: llama-server opens, and WITHOUT this Modal sends one input at a time — so a
#: util container declared with `parallel: 2` would serve one request while its
#: second slot sat empty, and a long memory-extraction call would block
#: captioning and tool calls behind it. Class-level because `@modal.concurrent`
#: is not per-parameter, so it takes the widest model in the registry.
_MAX_INPUTS = max(
    (m.parallel for m in registry.models.values() if m.enabled), default=1
) * 2

#: Scale-to-zero is class-level for a parameterized class, so it cannot be
#: per-model. Every registry entry declares the same value; reading it back is
#: what keeps models.json the one place to change it.
_IDLE_SECONDS = next(
    iter({m.idle for m in registry.models.values() if m.enabled}), 60
)

#: GPU is class-level for a parameterized class, so it cannot be per-model.
#: Every model in the registry targets the same card; assert that rather than
#: silently picking one, because a 48 GB model on a smaller card fails at load.
_GPU = next(iter({m.gpu for m in registry.models.values() if m.enabled}), "L40S")


def _require_healthy_server() -> None:
    """Fail fast if the in-container model process is gone.

    A Modal method on a dead llama-server raises a connection error that names
    the HTTP layer, not the model. Naming the process here is what makes the
    container exit instead of serving errors forever.
    """
    if _SERVER is None or not _SERVER.alive:
        raise RuntimeError(
            "llama-server is not running in this container; the container "
            "should be recycled"
        )


def _proxy(path: str, payload: dict | None = None):
    """One call to the in-container llama-server.

    Stdlib only — `urllib.request`. A pip dependency in this image is one that
    can be missing at exactly the moment a cold container starts serving, which
    is how this function's first version failed: the image installed `httpx`,
    the code imported `requests`, and every call died with ModuleNotFoundError
    while Modal logged the container as cold-booting forever.
    """
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['LLAMA_API_KEY']}",
        },
        method="POST" if body else "GET",
    )
    _require_healthy_server()
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _proxy_stream(path: str, payload: dict):
    """SSE from the in-container llama-server, yielding each parsed chunk.

    `urlopen` gives a file-like object, so `readline()` is the natural SSE
    reader — no client library and no buffering layer that has to be configured
    to stop holding lines back.
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {os.environ['LLAMA_API_KEY']}",
        },
        method="POST",
    )
    _require_healthy_server()
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
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
    """Serve any registry model behind an OpenAI-compatible surface.

    One Modal class, one container pool per `model_id`. The backend reads the
    same `models.json` this container was built with, so the role's primary and
    its fallback chain are agreed on both sides without a second manifest.
    """

    #: Which registry entry to load. A parameter, so each value gets its own
    #: pool and its own scale-to-zero timer.
    model_id: str = modal.parameter()

    #: Set on container enter when the model cannot be served. The container
    #: still starts and answers — it just says so, rather than failing.
    unavailable_reason: str | None = None

    #: Loaded on container enter, so the model load happens BEFORE the first
    #: call rather than inside it.
    #:
    #: A model with no weights, or not in the registry, is a PERMANENT
    #: configuration state. Raising here is the obvious move and the wrong one:
    #: Modal retries `@modal.enter()` and then re-creates the container on every
    #: call, so a missing download becomes an infinite container crash-loop
    #: burning GPU on a thing that can never succeed. The container starts
    #: cheaply instead, records why it cannot serve, and every method reports
    #: that — which is what makes "not downloaded yet" a state the caller can
    #: act on rather than an outage it has to diagnose.
    @modal.enter()
    def start(self):
        try:
            model = registry.get(self.model_id)
        except KeyError:
            self.unavailable_reason = (
                f"{self.model_id!r} is not in the baked-in registry; add it to "
                "models.json and redeploy"
            )
            return
        if not _present(model):
            self.unavailable_reason = (
                f"{self.model_id!r} has no weights on the Volume; run "
                "`modal run modal_llm/app.py::ensure --model-id <id>` first"
            )
            return
        _launch(model)

    @modal.method()
    def complete(self, messages: list, sampler: dict | None = None) -> dict:
        """One-shot completion. Returns the full parsed response."""
        self._require_available()
        payload = {"model": self.model_id, "messages": messages, "stream": False}
        if sampler:
            payload.update(sampler)
        return _proxy("/v1/chat/completions", payload)

    @modal.method(is_generator=True)
    def stream(self, messages: list, sampler: dict | None = None):
        """Streamed completion, yielding each SSE chunk as a dict.

        A generator method, consumed with `.remote_gen()` over the Modal SDK —
        which is why there is no HTTP endpoint to secure at all.
        """
        self._require_available()
        payload = {"model": self.model_id, "messages": messages, "stream": True}
        if sampler:
            payload.update(sampler)
        yield from _proxy_stream("/v1/chat/completions", payload)

    def _require_available(self) -> None:
        """Raise a clear, non-retryable error when this model cannot be served.

        Non-retryable is the point: this is a configuration state, not a
        transient failure, so a caller should not back off and retry it.
        """
        if self.unavailable_reason:
            raise RuntimeError(self.unavailable_reason)

    @modal.method()
    def health(self) -> dict:
        """Container and model reachability, including "not downloaded".

        A missing model answers `{"status": "not_downloaded", ...}` rather than
        raising, so a caller polling health sees an actionable state instead of
        a crash-loop it has to infer from retries.
        """
        if self.unavailable_reason:
            return {
                "status": "not_downloaded",
                "model_id": self.model_id,
                "reason": self.unavailable_reason,
            }
        _require_healthy_server()
        return {**_proxy("/health"), "model_id": self.model_id}


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

    if _present(model):
        return {"ok": True, "model_id": model_id, "downloaded": False, **_size(model)}

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


def _present(model) -> bool:
    """Is the model's GGUF (and projector, if it has one) on the Volume?

    Reloads first, without exception. A Modal Volume is a cache in front of
    object storage: a file committed by *another* container — which is what
    `ensure_model` does, from its own short-lived instance — is invisible here
    until this process refreshes. Without the reload the answer is "not
    downloaded" for a model that is, and `ensure_model` stops being idempotent.
    """
    vol.reload()
    for pattern in filter(None, [model.gguf, model.mmproj]):
        try:
            _resolve(model.volume_dir, pattern)
        except RuntimeError:
            return False
    return True


def _size(model) -> dict:
    """Byte size of the model's files, 0 when unreadable."""
    total = 0
    for pattern in filter(None, [model.gguf, model.mmproj]):
        try:
            total += Path(_resolve(model.volume_dir, pattern)).stat().st_size
        except RuntimeError:
            continue
    return {"bytes": total, "gb": round(total / 1e9, 2)}


@app.local_entrypoint()
def main(key: str = ""):
    """`modal run modal_llm/app.py [--key <id|role>]` — download weights.

    With no key this fetches the two primaries only, and says so, so a bare
    `modal run modal_llm/app.py` cannot be mistaken for "everything is ready".
    """
    fetched = download.remote(key)
    print(f"fetched: {fetched}")


@app.local_entrypoint()
def ensure(model_id: str):
    """`modal run modal_llm/app.py::ensure --model-id <id>` — fetch one model."""
    result = ensure_model.remote(model_id)
    print(f"{model_id}: {result}")


@app.local_entrypoint()
def presence():
    """`modal run modal_llm/app.py::presence` — what is on the Volume."""
    print(json.dumps(volume_state.remote(), indent=2))


@app.local_entrypoint()
def urls():
    """Print the JSON manifest the backend needs.

    Per role, in fallback order, with the sampler the model card suggests. There
    are no URLs in it any more — the app exposes no HTTP surface at all — so the
    backend constructs a Modal class instead:
        ChatLLM(model_id=manifest["roles"][role][0])
    which is also why `max_inputs`, `gpu` and `idle` are class-level facts the
    backend does not need to know.
    """
    manifest: dict = {"app": APP_NAME, "cls": "ChatLLM", "roles": {}, "models": {}}
    for role in sorted(registry.fallback):
        manifest["roles"][role] = []
        for model in registry.enabled_for(role):
            manifest["roles"][role].append(model.id)
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
def bench(key: str):
    """Time a cold start. Run when the model has been idle long enough to
    scale to zero, or it measures nothing."""
    model_id = key or PRIMARY_IDS[0]
    t0 = time.time()
    instance = ChatLLM(model_id=model_id)
    instance.health.remote()
    print(f"{model_id}: healthy after {time.time() - t0:.1f}s")


if __name__ == "__main__":
    # `modal run` uses the local entrypoints; running the module directly prints
    # the resolved registry so a change can be checked without deploying.
    print(json.dumps(
        {
            "enabled": ENABLED,
            "primaries": {role: ROLE_PRIMARY[role].id for role in ROLES},
        },
        indent=2,
    ))
