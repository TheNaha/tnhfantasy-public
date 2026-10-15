"""ARCHIVED 2026-10-15 — superseded by backend_v2/modal_llm/app.py.

Kept for reference only. This is the first llama.cpp draft; the shipped app is
`backend_v2/modal_llm/app.py`, which reads the same `models.json`, registers one
`ChatLLM` function per enabled model, and — deliberately — exposes NO HTTP
surface. The `modal.web_server` + bearer-key design below is the thing that
revision was written to remove: it published a public per-model URL, where the
current app is SDK-only and authenticated by the caller's Modal credentials.

Differences worth knowing before reading this:
  * `modal.concurrent`+`web_server` per model  ->  `ChatLLM`, parametrized by
    `modal.parameter()` model_id, with one llama-server per role.
  * Its own `MODELS` literal  ->  `models.json`, shared with the backend's
    llm_router and with `remote_agent/llama_server.py`.
  * `modal run ...::urls` published the manifest; the backend calls the SDK.

To deploy the real thing:  bash scripts/deploy.sh llm
"""


TNH LLM backend on Modal: registry-driven llama.cpp servers (OpenAI-compatible).

Every enabled entry in MODELS becomes its own Modal function with its own URL
and its own scale-to-zero timer. Unused models cost nothing while idle, so
"switching" models is just calling a different URL. List order inside each
role (rp / util) is the fallback order: first = primary, last = deepest backup.

Setup (once):
  modal secret create tnh-llm-key LLAMA_API_KEY=<long-random-string>
  modal run modal_llm.py                    # download weights for all enabled models
  modal run modal_llm.py --key artemis_31b  # ...or just one
  modal deploy modal_llm.py
  modal run modal_llm.py::urls              # JSON manifest for your backend
  modal run modal_llm.py::bench --key artemis_31b   # cold-start timer (run when idle)

Call a model:  POST <url>/v1/chat/completions  with
  Authorization: Bearer <LLAMA_API_KEY>   and   "model": "<id>"

To use a model from the bench: set enabled=True, rerun the download, redeploy.

VERIFY ON FIRST RUN (not tested against a live Modal account; the file does
import cleanly on modal 1.6.1 and registers one function per enabled entry):
  - GEMMA 4 CHAT TEMPLATE: GGUFs made before ~May 2026 may carry a broken
    template (model runs past its turn, prints <end_of_turn>, invents user
    replies). Several repos below were built in April. Test 3 turns; if you see
    raw turn tokens, pass a fixed template with
    extra_args=["--chat-template-file", "<path on the Volume>"] or use a
    newer GGUF.
  - Dynamic function registration (_register) deploys cleanly.
  - Cross-repo vision: finetunes with mmproj_repo use the STOCK Gemma 4
    projector. That usually works for abliterations/finetunes but is untested.
  - llama.cpp image tag (floats; pin it once something works), the
    /app/llama-server path, and flags (--jinja, --mmproj, --alias,
    --cache-type-*, LLAMA_API_KEY).
  - VRAM: 31B + big context + Gemma 4's large KV cache may not fit at the ctx
    below on an L40S. Lower ctx or switch kv to "q4_0" on OOM.

Gemma 4 thinking mode: off by default; to turn it on, start the system prompt
with <|think|> (per the model cards). Roleplay in the Reddit thread was
non-thinking.
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

import modal

APP_NAME = "tnh-llm"
app = modal.App(APP_NAME)

MODELS_DIR = "/models"
PORT = 8080

vol = modal.Volume.from_name("tnh-llm-models", create_if_missing=True)

# Prebuilt llama.cpp server image: no compile step, quick to pull.
image = (
    modal.Image.from_registry(
        "ghcr.io/ggml-org/llama.cpp:server-cuda", add_python="3.12"
    )
    .entrypoint([])  # drop the image's own entrypoint so Modal controls startup
    .pip_install("huggingface_hub")
)

# --------------------------------------------------------------------------
# Registry. Order within a role = fallback order (first = primary).
#
#   id          unique; becomes the function name and API alias
#   role        "rp" (roleplay prose) or "util" (vision, tool calls, extraction)
#   repo        Hugging Face GGUF repo
#   gguf        exact filename OR a glob (e.g. "*Q5_K_M.gguf"); must match 1 file
#   mmproj      vision projector filename/glob, or None for text-only
#   mmproj_repo repo to fetch mmproj from (default: same as repo)
#   dir         Volume folder (default: id). Entries sharing a dir share weights
#   ctx         context PER SLOT; total context = ctx * parallel
#   parallel    concurrent slots
#   kv          KV cache quant: None (f16), "q8_0", "q4_0"
#   gpu         "L40S" (48GB) or "A100-40GB"
#   idle        seconds a container stays warm after the last request
#   sampler     suggested sampler values; exported in the manifest, NOT enforced
#   extra_args  extra llama-server flags
#   enabled     False = on the bench: not downloaded, not deployed
#
# Evidence tags in comments: [UGI] leaderboard CSV (non-thinking rows),
# [Reddit] r/SillyTavernAI 16-31B thread, Oct 2026.
# --------------------------------------------------------------------------
GEMMA4_SAMPLER = dict(temperature=1.0, top_p=0.95, top_k=64)  # from model cards
STOCK_31B_MMPROJ = dict(
    mmproj="mmproj-F16.gguf", mmproj_repo="unsloth/gemma-4-31B-it-GGUF"
)  # 1.2 GB, verified filename

DEFAULTS = dict(
    mmproj=None, mmproj_repo=None, dir=None, ctx=32768, parallel=1, kv=None,
    gpu="L40S", idle=300, startup=600, sampler=None, extra_args=[], enabled=True,
)

_RAW = [
    # =========================== rp (fallback order) =======================
    dict(  # 1. [Reddit] most praised RP finetune this week; 1/30 refusals in
        # one tester's bench; not on UGI yet. bartowski, post-fix. Has its own
        # mmproj, so rp can read images directly. 23.5 + 1.2 GB.
        id="artemis_31b", role="rp",
        repo="bartowski/TheDrummer_Artemis-31B-v1.2-GGUF",
        gguf="TheDrummer_Artemis-31B-v1.2-Q5_K_M.gguf",
        mmproj="mmproj-TheDrummer_Artemis-31B-v1.2-f16.gguf",
        ctx=32768, kv="q8_0", sampler=GEMMA4_SAMPLER,
    ),
    dict(  # 2. [Reddit] "goated" for long RP, slopless style, handles stat
        # tables. Not on UGI. 21.8 GB. Text-only (no mmproj in repo).
        id="writers_31b_v2", role="rp",
        repo="mradermacher/Gemma-4-Writers-31B-V2-i1-GGUF",
        gguf="Gemma-4-Writers-31B-V2.i1-Q5_K_M.gguf",
        ctx=32768, kv="q8_0", sampler=GEMMA4_SAMPLER,
    ),
    dict(  # 3. [UGI] best intelligence + willingness measured: UGI 56.4,
        # W/10 10, NatInt 35.6, Writing 39.6. An abliteration of stock Gemma 4,
        # not an RP finetune, so prose may feel "assistant-like" ([Reddit]).
        # Shares weights with the util entry below. GGUF built Apr 2026:
        # check the chat template. 21.8 GB.
        id="gemma4_31b_heretic", role="rp",
        repo="mradermacher/gemma-4-31B-it-heretic-i1-GGUF",
        gguf="gemma-4-31B-it-heretic.i1-Q5_K_M.gguf",
        ctx=32768, kv="q8_0", sampler=GEMMA4_SAMPLER,
    ),
    dict(  # 4. FAST TIER. [UGI] Writing 43.5, W/10 8.0, NatInt 34.7 (non-think);
        # MoE, ~4B active, so much quicker per token. GGUF built Apr 27 (check
        # template). 19.1 GB.
        id="sompoa_26b_a4b", role="rp",
        repo="mradermacher/gemma-4-26B-A4B-it-SOMPOA-heresy-i1-GGUF",
        gguf="gemma-4-26B-A4B-it-SOMPOA-heresy.i1-Q5_K_M.gguf",
        ctx=32768, kv="q8_0", idle=240, sampler=GEMMA4_SAMPLER,
    ),
    dict(  # 5. MISTRAL-FAMILY BACKUP. [UGI] Writing 47.0, UGI 48.0, W/10 8.0,
        # NSFW 7.8, Dark 7.5, NatInt 30.2: best all-round Mistral-family row.
        # Text-only, Mistral Tekken template. 16.8 GB.
        id="weirdcompound_24b", role="rp",
        repo="mradermacher/WeirdCompound-v1.7-24b-i1-GGUF",
        gguf="WeirdCompound-v1.7-24b.i1-Q5_K_M.gguf",
        ctx=32768, sampler=dict(temperature=1.0, min_p=0.1),
    ),
    dict(  # 6. DEEP BACKUP (your original pick). [UGI] low willingness (W/10 2.2,
        # UGI 22.8) but high NSFW/Dark writing scores (7.0/7.2). Repo is linked
        # from its model card; filename is a glob (file list unseen). ~17 GB.
        id="magnum_diamond_24b", role="rp",
        repo="Doctor-Shotgun/MS3.2-24B-Magnum-Diamond-GGUF",
        gguf="*Q5_K_M.gguf",
        ctx=32768, sampler=dict(temperature=1.0, min_p=0.1),
    ),
    # ---- on the bench (enabled=False): fully specified, flip to try ----------
    dict(  # [Reddit] best multilingual behavior of the 31B finetunes; flip this
        # on if you roleplay outside English. 21.8 GB.
        id="dark_thoughts_v2_31b", role="rp", enabled=False,
        repo="mradermacher/Gemma-4-Dark-Thoughts-V2-31B-i1-GGUF",
        gguf="Gemma-4-Dark-Thoughts-V2-31B.i1-Q5_K_M.gguf",
        ctx=32768, kv="q8_0", sampler=GEMMA4_SAMPLER,
    ),
    dict(  # [Reddit] "split-untied": needs its own preset or it leaks English;
        # 22.8 GB.
        id="split_untied_31b", role="rp", enabled=False,
        repo="mradermacher/Split-Untied-31B-i1-GGUF",
        gguf="Split-Untied-31B.i1-Q5_K_M.gguf",
        ctx=32768, kv="q8_0", sampler=GEMMA4_SAMPLER,
    ),
    dict(  # [UGI] Writing 40.9 (47.9 with thinking), W/10 8.2, NatInt 29.7.
        # 26B-A4B MoE merge, post-fix GGUF (Jun 2026). 19.1 GB.
        id="goetia_26b_a4b", role="rp", enabled=False,
        repo="mradermacher/Goetia-26B-A4B-v1.3-Absolute-Heretic-ARA-i1-GGUF",
        gguf="Goetia-26B-A4B-v1.3-Absolute-Heretic-ARA.i1-Q5_K_M.gguf",
        ctx=32768, kv="q8_0", idle=240, sampler=GEMMA4_SAMPLER,
    ),
    dict(  # [Reddit] ~63 tok/s on a 16GB card, clean output, speculation hurts
        # RP on this MoE. Not on UGI. 19.6 GB.
        id="styletune_v2_26b_a4b", role="rp", enabled=False,
        repo="mradermacher/Gemma-4-26B-A4B-StyleTune-V2-i1-GGUF",
        gguf="Gemma-4-26B-A4B-StyleTune-V2.i1-Q5_K_M.gguf",
        ctx=32768, kv="q8_0", idle=240, sampler=GEMMA4_SAMPLER,
    ),
    # ============================ util (fallback order) ====================
    dict(  # 1. Same weights as rp "gemma4_31b_heretic" (shared dir, downloaded
        # once). [UGI] willing (W/10 10) with the best NatInt (35.6): keeps
        # NSFW memory extraction / captioning from refusing. Vision via the
        # STOCK Gemma 4 mmproj: test with a real image.
        id="gemma4_31b_heretic_util", role="util", dir="gemma4_31b_heretic",
        repo="mradermacher/gemma-4-31B-it-heretic-i1-GGUF",
        gguf="gemma-4-31B-it-heretic.i1-Q5_K_M.gguf",
        ctx=16384, parallel=2, kv="q8_0", idle=180,
        sampler=dict(temperature=0.3, top_p=0.95, top_k=64),
        **STOCK_31B_MMPROJ,
    ),
    dict(  # 2. FAST util. [UGI] UGI 45.0, W/10 8.8, NatInt 33.7 (non-think).
        # Author's own repo ships a BF16 mmproj. 19.1 + 1.2 GB.
        id="gemma4_26b_a4b_heretic_util", role="util",
        repo="llmfan46/gemma-4-26B-A4B-it-ultra-uncensored-heretic-GGUF",
        gguf="gemma-4-26B-A4B-it-ultra-uncensored-heretic-Q5_K_M.gguf",
        mmproj="gemma-4-26B-A4B-it-mmproj-BF16.gguf",
        ctx=16384, parallel=2, kv="q8_0", idle=180,
        sampler=dict(temperature=0.3, top_p=0.95, top_k=64),
    ),
    dict(  # 3. DEEP BACKUP (your original util pick). [UGI] W/10 6.5, UGI 40.4,
        # NatInt 23.9: more cautious than the Gemma 4 abliterations. Verified
        # filenames. 14.3 GB + 0.9 GB mmproj.
        id="mistral_small_32_it", role="util",
        repo="unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF",
        gguf="Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf",
        mmproj="mmproj-F16.gguf",
        ctx=16384, parallel=2, idle=180, sampler=dict(temperature=0.15),
    ),
]

MODELS = []
for _r in _RAW:
    _m = {**DEFAULTS, **_r}
    _m["dir"] = _m["dir"] or _m["id"]
    MODELS.append(_m)
ENABLED = [m for m in MODELS if m["enabled"]]


def _resolve(mdir: str, pattern: str) -> str:
    """Find the single file in a model's Volume folder matching a name/glob."""
    hits = sorted(Path(MODELS_DIR, mdir).glob(pattern))
    if len(hits) != 1:
        raise RuntimeError(
            f"{mdir}: {pattern!r} matched {len(hits)} files: {[h.name for h in hits]}"
        )
    return str(hits[0])


def _launch(m: dict) -> None:
    cmd = [
        "/app/llama-server",
        "-m", _resolve(m["dir"], m["gguf"]),
        "--alias", m["id"],
        "--host", "0.0.0.0",
        "--port", str(PORT),
        "-ngl", "99",  # all layers on GPU
        "-c", str(m["ctx"] * m["parallel"]),
        "--parallel", str(m["parallel"]),
        "--jinja",  # use the model's own chat template + tool calling
    ]
    if m["mmproj"]:
        cmd += ["--mmproj", _resolve(m["dir"], m["mmproj"])]
    if m["kv"]:
        cmd += ["--cache-type-k", m["kv"], "--cache-type-v", m["kv"]]
    cmd += m["extra_args"]
    # Auth: llama-server reads LLAMA_API_KEY from the environment (Modal Secret).
    subprocess.Popen(cmd)


# --------------------------------------------------------------------------
# One Modal function per enabled model, generated from the registry.
# --------------------------------------------------------------------------
def _register(m: dict) -> None:
    name = f"serve_{m['id']}"

    def _serve():
        _launch(m)

    _serve.__name__ = _serve.__qualname__ = name  # unique, importable name

    fn = app.function(
        name=name,
        image=image,
        gpu=m["gpu"],
        volumes={MODELS_DIR: vol},
        secrets=[modal.Secret.from_name("tnh-llm-key")],
        timeout=60 * 60,
        scaledown_window=m["idle"],
    )(
        modal.concurrent(max_inputs=m["parallel"] * 2)(
            modal.web_server(port=PORT, startup_timeout=m["startup"])(_serve)
        )
    )
    globals()[name] = fn  # module-level, so the container can find it by name


for _m in ENABLED:
    _register(_m)


# --------------------------------------------------------------------------
# One-time weight download into the Volume (runs remotely; fast network).
# Entries that share a dir are downloaded once. For gated repos, add a Modal
# Secret with HF_TOKEN to secrets=[...].
# --------------------------------------------------------------------------
@app.function(image=image, volumes={MODELS_DIR: vol}, timeout=4 * 3600)
def download(key: str = ""):
    from huggingface_hub import snapshot_download

    done = set()
    for m in ENABLED:
        if key and m["id"] != key:
            continue
        jobs = [(m["repo"], m["gguf"])]
        if m["mmproj"]:
            jobs.append((m["mmproj_repo"] or m["repo"], m["mmproj"]))
        for repo, pattern in jobs:
            if (m["dir"], repo, pattern) in done:
                continue
            done.add((m["dir"], repo, pattern))
            print(f"[{m['id']}] {repo} :: {pattern}")
            snapshot_download(
                repo,
                allow_patterns=[pattern],
                local_dir=f"{MODELS_DIR}/{m['dir']}",
            )
            f = Path(_resolve(m["dir"], pattern))  # fail loudly if nothing matched
            print(f"   ok {f.name}  {f.stat().st_size / 1e9:.1f} GB")
    vol.commit()


# --------------------------------------------------------------------------
# Local helpers (run from your machine with `modal run`).
# --------------------------------------------------------------------------
def _url(m: dict) -> str:
    fn = modal.Function.from_name(APP_NAME, f"serve_{m['id']}")
    try:
        return fn.get_web_url()
    except AttributeError:  # older modal clients
        return fn.web_url


@app.local_entrypoint()
def main(key: str = ""):
    """modal run modal_llm.py [--key <id>]  ->  download weights."""
    download.remote(key)


@app.local_entrypoint()
def urls():
    """Print a JSON manifest (fallback order per role) for your backend."""
    manifest = {}
    for m in ENABLED:
        manifest.setdefault(m["role"], []).append(
            {
                "id": m["id"],
                "url": _url(m),
                "model": m["id"],
                "ctx_per_slot": m["ctx"],
                "parallel": m["parallel"],
                "vision": bool(m["mmproj"]),
                "sampler": m["sampler"],
                "repo": m["repo"],
            }
        )
    print(json.dumps(manifest, indent=2))


@app.local_entrypoint()
def bench(key: str):
    """Time a cold start: run when the model has been idle long enough to scale to zero."""
    m = next(x for x in ENABLED if x["id"] == key)
    url = _url(m) + "/health"
    t0 = time.time()
    while time.time() - t0 < 900:
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                if r.status == 200:
                    print(f"{key}: healthy after {time.time() - t0:.1f}s")
                    return
        except Exception:
            pass  # still booting / loading the model
        time.sleep(2)
    raise SystemExit(f"{key}: not healthy after 900s")