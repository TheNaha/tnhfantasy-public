"""
TNH LLM on Modal — llama.cpp servers behind an OpenAI-compatible API.

One Modal function per *enabled* registry entry, each with its own URL and its
own scale-to-zero timer. Nothing here decides which model serves which role:
that is `models.json`, read by this file and by the backend so the two cannot
drift. See `modal_llm/README.md`.

Setup (once):
    modal secret create tnh-llm-key LLAMA_API_KEY=<long-random-string>
    modal run modal_llm/app.py              # download weights for enabled models
    modal run modal_llm/app.py --key rp     # ...or just one role
    modal deploy modal_llm/app.py           # prints the URLs
    modal run modal_llm/app.py::urls        # JSON manifest for the backend
    modal run modal_llm/app.py::bench --key artemis_31b

Call a model:
    POST <url>/v1/chat/completions
    Authorization: Bearer <LLAMA_API_KEY>
    {"model": "<id>", "messages": [...]}

To change which model serves a role, edit `models.json` and redeploy. To try a
model that is on the bench, flip `enabled: true`, run the download, redeploy.

VERIFY ON FIRST RUN — this file has not been deployed against a live account:
  * Gemma 4 chat template: GGUFs built before ~May 2026 may run past their turn
    and print raw turn tokens. If 3 turns look wrong, add
    extra_args=["--chat-template-file", "/models/chat-template.jinja"] to that
    model in models.json.
  * Cross-repo vision: the abliterated `util` models take the STOCK Gemma 4
    projector. That usually works, but it has not been tested with a real image.
  * VRAM: 31B at 32k with q8_0 KV may not fit one L40S. On OOM, lower `ctx` or
    set `kv` to "q4_0".
  * Cold-start times: run `bench` once the deployment is idle, and send the
    numbers back so the `roles` order can be tuned.
"""

from __future__ import annotations

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


class _RoleChatBase:
    """Shared body for the two role classes.

    A base rather than a factory: Modal registers functions by the name it finds
    in the source AST, so generating two classes inside a loop both literally
    named `_RoleChat` makes the second override the first (Modal warns
    "function name collision"). Two explicit subclasses is the same amount of
    code and no warning — and the role vocabulary is a fixed pair, so there is
    nothing dynamic to write for.
    """

    #: Which registry entry this role serves. Overridden per subclass, which is
    #: the only thing that differs between them.
    ROLE = "rp"

    def _model(self):
        return ROLE_PRIMARY[self.ROLE]

    #: Llama-server starts on container enter, so the model load happens before
    #: the first call rather than inside it. This is also where the ~16 s load
    #: is paid — on the container's own clock, not inside the caller's request.
    @modal.enter()
    def start(self):
        _launch(self._model())

    @modal.method()
    def complete(self, messages: list, sampler: dict | None = None) -> dict:
        """One-shot completion. Returns the full parsed response."""
        payload = {"model": self._model().id, "messages": messages, "stream": False}
        if sampler:
            payload.update(sampler)
        return _proxy("/v1/chat/completions", payload)

    @modal.method(is_generator=True)
    def stream(self, messages: list, sampler: dict | None = None):
        """Streamed completion, yielding each SSE chunk as a dict.

        A generator method, consumed with `.gen()` over the Modal SDK — so there
        is no HTTP endpoint to secure in the first place, which is the whole
        reason `modal.web_server` is not used here.
        """
        payload = {"model": self._model().id, "messages": messages, "stream": True}
        if sampler:
            payload.update(sampler)
        yield from _proxy_stream("/v1/chat/completions", payload)

    @modal.method()
    def health(self) -> dict:
        return _proxy("/health")


#: One Modal class per ROLE, not per model.
#:
#: This is the fix for "why a million endpoints". Nine web functions — one per
#: enabled model — is nine public URLs, nine scale-to-zero timers and nine
#: attack surfaces on a single-user app. A role is what the backend actually
#: addresses, and `ROLE_PRIMARY` decides which weights sit behind it, so
#: swapping the primary model is an edit to models.json and a redeploy rather
#: than a new function.
#:
#: No `modal.web_server`: those endpoints were unauthenticated, and llama-server's
#: own API key was the only thing between a public URL and the model. A plain
#: `@modal.method()` is reached only through the Modal SDK with the caller's
#: token — the same auth the rest of this app's Modal path uses.
#:
#: `max_containers=1` and one input at a time: two L40S containers is twice the
#: bill for a workload where the second request never happens.
def _register_role(name: str, role: str):
    model = ROLE_PRIMARY[role]

    cls = type(
        name,
        (_RoleChatBase,),
        {
            "ROLE": role,
            "__doc__": f"{role} prose chat — currently {model.id}.",
        },
    )
    decorated = app.cls(
        image=image,
        gpu=model.gpu,
        volumes={MODELS_DIR: vol},
        secrets=[modal.Secret.from_name("tnh-llm-key")],
        scaledown_window=model.idle,
        max_containers=_MAX_CONTAINERS_PER_ROLE,
        timeout=60 * 60,
        startup_timeout=_STARTUP_TIMEOUT_SECONDS,
    )(cls)
    globals()[name] = decorated
    return decorated


ChatRP = _register_role("ChatRP", "rp")
ChatUTIL = _register_role("ChatUTIL", "util")


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
    """Is the model's GGUF (and projector, if it has one) on the Volume?"""
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


def _web_url(model) -> str:
    fn = modal.Function.from_name(APP_NAME, f"serve_{model.id}")
    try:
        return fn.get_web_url()
    except AttributeError:  # older modal clients
        return fn.web_url


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

    Per role, in fallback order, with the sampler the model card suggests. The
    backend reads the same `models.json` for the *order*; this manifest is what
    tells it which URL each model ended up on, which only Modal knows.
    """
    manifest: dict = {"roles": {}, "models": {}}
    for role in registry.fallback:
        manifest["roles"][role] = []
        for model in registry.enabled_for(role):
            url = _web_url(model)
            manifest["roles"][role].append(model.id)
            manifest["models"][model.id] = {
                "id": model.id,
                "role": model.role,
                "url": url,
                "chat_url": f"{url}/v1/chat/completions",
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
    model = registry.get(key)
    url = _web_url(model) + "/health"
    t0 = time.time()
    while time.time() - t0 < 900:
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                if response.status == 200:
                    print(f"{key}: healthy after {time.time() - t0:.1f}s")
                    return
        except Exception:
            pass  # still booting / still loading
        time.sleep(2)
    raise SystemExit(f"{key}: not healthy after 900s")


if __name__ == "__main__":
    # `modal run` uses the local entrypoints; running the module directly prints
    # the resolved registry so a change can be checked without deploying.
    print(json.dumps(
        {
            "enabled": ENABLED,
            "roles": {r: registry.enabled_for(r).__len__() for r in registry.fallback},
        },
        indent=2,
    ))
