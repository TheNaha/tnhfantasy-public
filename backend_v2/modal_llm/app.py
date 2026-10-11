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


def _proxy_stream(port: int, path: str, payload: dict):
    """SSE from the in-container llama-server, yielding each parsed chunk.

    `urlopen` gives a file-like object, so `readline()` is the natural SSE
    reader — no client library and no buffering layer that has to be configured
    to stop holding lines back.
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
        """Load one llama-server per role, each on its own port.

        A role whose weights are missing, or which is not in the registry, is
        recorded in `unavailable` rather than raised. Raising makes Modal retry
        enter and re-create the container on every call, so a missing download
        becomes an infinite crash-loop burning GPU on something that can never
        succeed.
        """
        self.serving = {}
        self.unavailable = {}
        # Before any model loads — see `_refresh_volume`.
        _refresh_volume()
        for index, role in enumerate(ROLES):
            model = ROLE_PRIMARY[role]
            try:
                model = registry.get(ROLE_PRIMARY[role].id)
            except KeyError:
                self.unavailable[role] = (
                    f"role {role!r} points at {ROLE_PRIMARY[role].id!r}, which is "
                    "not in the baked-in registry"
                )
                continue
            if not _present(model):
                self.unavailable[role] = (
                    f"{model.id!r} has no weights on the Volume; run "
                    "`modal run modal_llm/app.py::ensure --model-id <id>` first"
                )
                continue
            port = _SERVER_PORT_BASE + index
            _launch(model, port)
            self.serving[role] = model.id
        print(f"serving: {self.serving}; unavailable: {self.unavailable}", flush=True)

    # ------------------------------------------------------------------
    def _resolve(self, model_id: str) -> tuple[str, int]:
        """(role, port) for a model id, or raise a clear non-retryable error.

        Not retryable on purpose: an unknown or unserved model is a
        configuration state, so a caller should fail rather than back off.
        """
        for role, served in self.serving.items():
            if served == model_id:
                return role, _SERVER_PORT_BASE + ROLES.index(role)
        reason = self.unavailable.get(model_id) or self.unavailable.get(
            self._role_for(model_id)
        )
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
        _, port = self._resolve(model_id or self._default_model())
        payload = {"model": model_id or self._default_model(),
                   "messages": messages, "stream": False}
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
        resolved = model_id or self._default_model()
        _, port = self._resolve(resolved)
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
        """
        out: dict = {"app": APP_NAME, "roles": {}}
        for role in ROLES:
            model_id = ROLE_PRIMARY[role].id
            if role in self.unavailable:
                out["roles"][role] = {
                    "status": "not_downloaded",
                    "model_id": model_id,
                    "reason": self.unavailable[role],
                }
                continue
            if role not in self.serving:
                out["roles"][role] = {
                    "status": "unknown",
                    "model_id": model_id,
                }
                continue
            port = _SERVER_PORT_BASE + ROLES.index(role)
            server = _require_healthy_server(self.serving[role])
            out["roles"][role] = {
                "status": "ok",
                "model_id": self.serving[role],
                "port": server.port,
                **_proxy(port, "/health"),
            }
        return out

    @staticmethod
    def _default_model() -> str:
        """The rp role's model, for a caller that does not name one."""
        return ROLE_PRIMARY["rp"].id if "rp" in ROLE_PRIMARY else PRIMARY_IDS[0]


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

    # This container holds no model files, so a reload is safe and needed —
    # another container may have committed since this one last looked.
    _refresh_volume()
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
    """Is the model's GGUF (and projector, if it has one) on the Volume?

    Pure filesystem — no reload, so it is safe to call at any point in the
    container's life, including while a model is loaded. Refresh first with
    `_refresh_volume()`.
    """
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
