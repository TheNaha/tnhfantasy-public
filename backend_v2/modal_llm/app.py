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
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import modal

# `registry.py` sits beside this file, so it is importable as a local module
# rather than needing a package install inside the image.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from registry import REGISTRY_PATH, load  # noqa: E402

APP_NAME = "tnh-llm"
app = modal.App(APP_NAME)

MODELS_DIR = "/models"
PORT = 8080

#: The registry as it was when this file was last deployed. Baked into the image
#: so a deployed container knows its own role and sampler without a network call.
REGISTRY_REMOTE = "/models-registry"

vol = modal.Volume.from_name("tnh-llm-models", create_if_missing=True)

#: Prebuilt llama.cpp server image: no compile step, small, quick to pull. The
#: tag is deliberately unpinned (it floats) — pin it once something works, so a
#: redeploy cannot silently change llama.cpp versions under a working deployment.
image = (
    modal.Image.from_registry(
        "ghcr.io/ggml-org/llama.cpp:server-cuda", add_python="3.12"
    )
    .entrypoint([])  # drop the image's own entrypoint so Modal controls startup
    .pip_install("huggingface_hub")
)

registry = load(REGISTRY_PATH)
ENABLED = registry.enabled_ids()


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


def _launch(model) -> None:
    """Start llama-server for one model, then block forever.

    Blocking is required: Modal keeps the container alive while the entrypoint
    runs, so a `Popen` that returned would let the function exit and the server
    die with it.
    """
    cmd = ["/app/llama-server"] + model.llama_args() + [
        "--host", "0.0.0.0",
        "--port", str(PORT),
    ]
    print(f"[{model.id}] launching: {' '.join(cmd)}", flush=True)
    process = subprocess.Popen(cmd)
    try:
        process.wait()
    finally:
        if process.poll() is None:  # pragma: no cover - shutdown path
            process.terminate()


def _bind(model) -> None:
    """Register one Modal function for a model and publish it by name.

    A closure per model, with the name set on the function object so Modal's
    import-based lookup finds it. This is the same trick the reference file used
    and there is no cleaner way to do it — the alternative is one hand-written
    `serve_*` function per model, which is the duplication the registry exists to
    remove.
    """
    name = f"serve_{model.id}"

    def _serve():
        _launch(model)

    _serve.__name__ = _serve.__qualname__ = name

    fn = app.function(
        name=name,
        image=image,
        gpu=model.gpu,
        volumes={MODELS_DIR: vol},
        secrets=[modal.Secret.from_name("tnh-llm-key")],
        timeout=60 * 60,
        scaledown_window=model.idle,
    )(
        modal.concurrent(max_inputs=model.parallel * 2)(
            modal.web_server(port=PORT, startup_timeout=model.startup)(_serve)
        )
    )
    globals()[name] = fn
    return fn


for _model_id in ENABLED:
    _bind(registry.get(_model_id))


# ---------------------------------------------------------------------------
# Weight download. One entry per (volume_dir, repo, pattern), so a model that
# shares another's weights — the `util` twin of an `rp` entry — downloads once.
# ---------------------------------------------------------------------------
@app.function(
    image=image.pip_install("huggingface_hub"),
    volumes={MODELS_DIR: vol},
    timeout=4 * 3600,
)
def download(key: str = ""):
    """Fetch every enabled model's weights into the Volume.

    `key` matches a model id or a *role*, so `--key rp` fetches just the
    roleplay set and `--key util` just the structured set.
    """
    from huggingface_hub import snapshot_download

    if key and key in registry.fallback and key not in registry.models:
        targets = registry.enabled_for(key)
    elif key:
        targets = [registry.get(key)]
    else:
        targets = [registry.get(mid) for mid in ENABLED]

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


def _web_url(model) -> str:
    fn = modal.Function.from_name(APP_NAME, f"serve_{model.id}")
    try:
        return fn.get_web_url()
    except AttributeError:  # older modal clients
        return fn.web_url


@app.local_entrypoint()
def main(key: str = ""):
    """`modal run modal_llm/app.py [--key <id|role>]` — download weights."""
    download.remote(key)


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
