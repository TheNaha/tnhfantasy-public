# Remote Agent reliability audit — 2026-10-20

**Scope:** `remote_agent/` (6,534 lines) — `vram_manager.py` (1,196), `server.py`
(1,936), `provider_core/downloads.py` (1,333), `llama_server.py` (494),
`ram_manager.py` (741), plus the Colab notebook that supervises them.

**Why:** the operator reports the worker is unreliable on its minimum target
(an L4, 24 GB VRAM) — "sometimes it oomed, crashed, underperform (because
poor vram management and the layers got loaded on ram instead), long wait
(due to improper cache strategy)".

**Verdict:** the symptoms are not a hardware problem and not a capacity
problem. They are four defects, each of which produces a distinct symptom,
plus a set of secondary issues that make each of them worse than it needs to
be. The single most damaging finding is a **lease counter that never returns
to zero**, which imposes a deterministic **60-second tax on every image
generation after the first chat reply**.

Three audits were run independently (VRAM management, RAM cache + downloads,
process lifecycle) and cross-checked. Findings that appeared in more than one
audit are marked **[×2]** or **[×3]**.

---

## 1. The four primary defects

### P1 — CRITICAL [×2] — The workload lease is taken twice and released once, so every image request waits 60 s

`remote_agent/vram_manager.py:617-624` (inside `prepare_for_workload`):

```python
                    if self.is_comfy_generating() or (self.active_lease == "image" and self.in_flight_count > 0):
                        actions_taken.append("waited_for_comfy_drain")
                        self.acquire_lease("llm", timeout=timeout)
                    else:
                        self.active_lease = "llm"
                        if self.in_flight_count == 0:
                            self.in_flight_count = 1
```

`remote_agent/server.py:1393-1399`:

```python
        lease_acquired = False
        try:
            ...
            await _bounded_to_thread(vmgr.prepare_for_workload, "llm", target_model)
            lease_acquired = await _bounded_to_thread(vmgr.acquire_lease, "llm")
```

`prepare_for_workload` already takes the lease. The route takes it **again**.
Exactly one `release_lease` runs per request (`server.py:1428, 1448, 1472, 1490`).

So `in_flight_count` settles at **1 permanently** after the first chat
request, and `active_lease` is never cleared again. From then on, every
**image** request hits `vram_manager.py:570-572`:

```python
                if self.active_lease == "llm" and self.in_flight_count > 0:
                    actions_taken.append("waited_for_llm_drain")
                    self.acquire_lease("image", timeout=timeout)
```

`acquire_lease("image")` sees a conflict, blocks on the condition for the
full `timeout=60.0`, and **returns False — whose value is discarded**. The
image request then proceeds anyway, 60 s later, into the eviction path that
SIGTERMs the llama-server that may be streaming an answer.

Three consequences, all matching reported symptoms:
- a hard **+60 s** on every image generation after the first chat reply
  ("long wait");
- the LLM is killed **mid-stream** by the next image request ("crashed");
- the next chat request must JIT-reload the model, so the loop repeats.

**Fix:** make the lease accounting symmetric. `prepare_for_workload` must not
take a lease the caller does not release, and the drain must honour
`acquire_lease`'s `False` return instead of proceeding anyway.

### P2 — CRITICAL — The KV-cache type is chosen from live free VRAM, so the running server is torn down and the 20 GB model reloaded on alternating requests

`remote_agent/vram_manager.py:746-755`:

```python
            if not target_kv:
                info = self.get_vram_info(device_idx=self.llm_gpu_device)
                free_mb = info.get("vram_free_mb", 0)
                is_gemma = "gemma" in model_path.lower() or ...
                if is_gemma or free_mb >= 20000:
                    target_kv = "f16"
                else:
                    target_kv = "q8_0"
```

`remote_agent/vram_manager.py:759-766`:

```python
            if self.is_llama_running():
                model_matches = is_generic or (...)
                config_matches = (self.current_kv_type == target_kv) and (self.current_ctx_size == target_ctx)
                if model_matches and config_matches:
                    self.last_llm_activity = time.time()
                    return True
                # Different model or config requested -> stop current and hot-switch
                self.stop_llama()
```

`target_kv` is recomputed on **every** call from the *current* free VRAM;
`current_kv_type` is frozen at server start. Free VRAM on this box swings by
±10 GB depending on whether ComfyUI currently holds a checkpoint, so:

- chat request (ComfyUI idle, free 22 GB) → `f16` → server starts f16
- image request (ComfyUI resident, free 11 GB) → `q8_0` → mismatch → **kill and reload**
- chat request (ComfyUI idle again) → `f16` → mismatch → **kill and reload again**

Every alternating request pays a full process kill plus a 19.5 GB GGUF load
(tens of seconds). This is the "long wait (due to improper cache strategy)"
in its most literal form: the cache is not a cache, it is a reload trigger.

**Fix:** derive the KV type from the model and the requested context, not
from a fluctuating resource reading; store it with the model id so the
comparison is like-for-like.

### P3 — CRITICAL [×2] — A model swap starts the replacement while the evicted process is still alive and still holding VRAM

`remote_agent/vram_manager.py:275-315` (`stop_llama`):

```python
            # 2. Check if an orphaned llama-server is listening on the port
            try:
                subprocess.run(["pkill", "-f", f"llama-server.*{self.llm_port}"], check=False, ...)
            except Exception:
                pass
            ...
            return True
```

Four holes:
1. `self.llama_proc.wait(timeout=1.0)` raises `TimeoutExpired`, which is
   swallowed by `except Exception` (`:292`), and the `finally` clears the
   handle (`:295`). The SIGKILLed child may still hold 10–19 GB.
2. The orphan path (`self.llama_proc is None`) skips the terminate/kill
   branch entirely; the only cleanup is an **asynchronous** `pkill` that
   returns immediately.
3. Nothing ever polls `mem_get_info` to confirm the memory came back.
4. `pkill` may not exist in the slim image; `FileNotFoundError` is swallowed
   by `except Exception: pass`.

`stop_llama` returns `True` unconditionally, so the caller cannot tell
whether anything was freed. `vram_manager.py:766-817` then does, with **zero
settle time** between them: `stop_llama()` → `calculate_safe_ngl(model_path)`
→ `Popen`.

llama.cpp handles SIGTERM **deferred** — the handler sets a flag that the
main loop notices between token batches. A server mid-prefill can take
seconds to honour it.

Two outcomes, both bad:
- The old server is still resident → free VRAM reads low → `ngl` is computed
  too small → **the new server starts with most of its layers on the CPU**.
  This is precisely the reported "the layers got loaded on ram instead", and
  it is **silent**: the server answers `/health` and is treated as fully
  loaded.
- Both are resident → 2 × 19.5 GB on a 24 GB card → CUDA OOM inside the
  new server.

**Fix:** stop → wait for exit → **verify the VRAM actually came back** →
only then allocate. Never proceed while a previous process may still hold
VRAM.

### P4 — CRITICAL — The VRAM reserve is a hardcoded constant that is 4.7× too small for the context the code selects

`remote_agent/vram_manager.py:1136-1139` (and the same constant duplicated at
`:646`):

```python
        # Reserve for KV cache (8192 context q8_0 with -np 1) + compute scratch / context activation buffers
        reserve_mb = 1800
```

The reserve is the *only* allowance for the KV cache and the compute buffer,
and it is a literal. It does not scale with context length, KV precision, or
architecture — while the same file chooses the KV precision from free VRAM
(defaulting to **f16** whenever the card has ≥20 GB free, or the model is a
gemma) and the model registry declares `ctx: 32768` for the prose models and
`ctx: 16384` for the utility model.

For a 64-layer, 8-KV-head, 128-dim model (256 KB/token at f16):

| ctx | KV type | KV size | + compute | reserve needed | reserve used |
|---|---|---|---|---|---|
| 8192 | f16 | 2.0 GB | +0.3–0.8 | ~2.4–2.8 GB | 1.8 GB (borderline) |
| 32768 | f16 | 8.0 GB | +0.3–0.8 | ~8.4–8.8 GB | 1.8 GB (**4.7× short**) |
| 16384 | q8_0 | 2.0 GB | +0.3 | ~2.3 GB | 1.8 GB (short) |

The OOM happens **inside the llama-server child**, so it surfaces as
`llama-server exited unexpectedly code 1` and a 503 — with no OOM in the log,
because the child's stderr is inherited rather than captured. There is **no
retry** anywhere: one OOM is one dead LLM until the next request re-triggers
the same decision.

**Fix:** compute the reserve from the target context, the KV type, and the
model's KV geometry, and use it in both places.

---

## 2. Secondary findings, by area

### VRAM arbitration (`vram_manager.py`)

| # | Sev | Finding |
|---|---|---|
| S1 | HIGH | `is_multi_gpu` is derived from *configured device indices*, not the device count (`:55-60`). `LLM_GPU_DEVICE=1` on a single-GPU L4 — which `remote_agent/.env.example` suggests — makes the arbiter believe it is multi-GPU and **disable all eviction** (`:545-552`, `:613-615`). The OOM is then guaranteed. |
| S2 | HIGH | `prepare` and `acquire` are not atomic (two lock acquisitions), and an "llm" lease does not conflict with another "llm" lease. A util request arriving during an rp stream calls `stop_llama()` and **kills the in-flight stream**. This worker is explicitly built for a two-model split, so this is the normal case, not an edge case. |
| S3 | HIGH | `get_vram_info()` takes the same lock a model load holds for its entire duration (up to 60 s) and makes two blocking HTTP probes — and `server.py:1812` calls it **directly on the event loop**. One `/vram/status` freezes the whole worker. |
| S4 | HIGH | The image path always answers `"status": "ready"`, even when the target free VRAM was never reached. `hybrid_engine.py:227` discards the body and dispatches anyway. The arbiter's contract is not enforced. |
| S5 | HIGH | `get_laya_device()` calls `free_comfy_vram()` with **no drain check** (`:363-369`), unlike every other eviction in the file. The Director runs on every chat turn, so this can yank ComfyUI's model out from under a running generation. |
| S6 | HIGH | Laya models loaded by the server's own fallback (`server.py:1586-1613`) go into a different dict and are **never** in `laya_cache`, so `unload_laya_cuda()` cannot free them — a permanent, un-evictable VRAM leak that skews every later free-VRAM decision. The fallback also forces CUDA even when the arbiter had chosen CPU. |
| S7 | MED-HIGH | `LLM_IDLE_TIMEOUT_SECONDS` is parsed, stored, reported — and **never acted on**. There is no idle reaper, so the LLM pins 10–19 GB of VRAM until an unrelated image workload happens to evict it. |
| S8 | MED-HIGH | `safe_ngl = max(4, min(total_layers - 2, target_layers - 1))` (`:1163-1169`) — the hard floor of 4 **overrides** the budget, so 4 layers are forced onto the GPU when the arithmetic allowed 3. |
| S9 | MED-HIGH | `is_comfy_generating()` returns `False` on **any** error (`:227-239`), including a 1 s timeout on a loaded box. A false negative there means evicting under a live generation. The two gates that are supposed to prevent that are the ones that fail open. |
| S10 | MEDIUM | The health check is by **port**, not by process (`:824-846`). An orphan on :8003 answers it, and the manager then records the *new* (doomed) child as the healthy server. |
| S11 | MEDIUM | The layer-count fallback constants are wrong for the shipped models (`:1105-1122`): 46 for the 26/27B family (actually 62) and 40 for the 12B (actually 48). Under-allocates VRAM → "layers on RAM". |
| S12 | MEDIUM | The Laya device decision is made outside the lock and the load happens inside it (TOCTOU), and `unload_laya_cuda()` books a fixed 1500 MB of freed space even when the model is still referenced by the thread that received it. |
| S13 | MEDIUM | "Generic" model ids (`default`/`auto`/`rp`/`llm`/`primary`/`base`) match **any** running server (`:758-762`), so a util model can serve an rp request. |
| S14 | LOW | `min_free_vram_mb` is honoured only on the image path, never on the LLM path. |

### RAM cache and downloads (`ram_manager.py`, `provider_core/downloads.py`)

| # | Sev | Finding |
|---|---|---|
| R1 | CRITICAL | **The RAM cache is never a download target.** The network transfer always lands on disk (`server.py:761`); the cache is filled by a *second* full copy afterwards (`server.py:807-812`). And `prewarm` defaults to `False` (`server.py:266`) with **no backend caller ever setting it**, so in the Docker/Modal deployment the cache is never populated for image models at all. |
| R2 | CRITICAL | **The `/dev/shm` trap.** The write test is `write_text("ok")` — 2 bytes (`ram_manager.py:112-125`) — so a 64 MB tmpfs passes and the `/tmp` fallback never fires. `remote_agent/docker-compose.yml` declares **no `shm_size`**, so Docker's default 64 MB applies to the whole agent container, and `mount -o remount` fails without `CAP_SYS_ADMIN`. Every multi-GB `ensure_in_ram` then raises, is logged as a warning, and the agent silently streams from the volume. |
| R3 | CRITICAL | The RAM "budget" is not a budget: the reserve only triggers eviction, never refusal (`ram_manager.py:445-453`), the budget is 75 % of *total* RAM with a fixed 8 GB reserve, and the copy transiently needs **2×** the model. When everything is pinned, eviction cannot free enough and the copy proceeds into an OOM. There is no `psutil` in `requirements.txt`, so `_detect_ram_capacity_gb()` returns a hardcoded **32.0** and the low-RAM fallback never engages. |
| R4 | CRITICAL | `ensure_dir_in_ram` is neither atomic nor verified (`ram_manager.py:614-627`): `copytree` writes in place, is never size-checked, and a failed copy leaves a partial directory. The Laya loader then treats **"non-empty directory"** as "valid model" (`server.py:1561-1563`) and loads the truncated copy. |
| R5 | HIGH | Concurrent `ensure_in_ram` calls for the same model share **one deterministic temp path** (`.{dest_filename}.tmp`, `ram_manager.py:473`), and there is no file lock — unlike `downloads.py`, which has `exclusive_path_lock`. The notebook prewarms with the basename and the agent prewarms with the basename: **identical temp path, two processes.** |
| R6 | HIGH | **"Pinned Anchors (Protected)" are silently wiped by a rescan.** `_rescan_ram_dir` hardcodes `is_anchor=False` (`:200-209`) and overwrites the entry, and it is called on **every model-path resolution miss** — i.e. routinely, exactly when a model is being loaded. The pin is also matched by *substring* in one place and *exactly* in another. |
| R7 | HIGH | An **unknown magic header is treated as VALID** (`validation.py:107-128`): an unrecognised header appends no error, so `valid: True` is returned. A 200-with-JSON-body (a proxy error envelope) matches `b"{"` and is published as the model. **No checksum is ever verified** — the `.sha256` sidecar is only ever deleted. |
| R8 | HIGH | A multi-GB copy runs **synchronously inside an `async def`** (`server.py:753-812`, `:742-747`, `:691-693`) — the whole event loop stalls for the duration, including the `/health` probe the backend uses for provider status. |
| R9 | MED-HIGH | A failed prewarm can **empty the entire cache** and still not succeed: the eviction loop tests physical free space but evicts against the *budget* (`ram_manager.py:457-463`). |
| R10 | MEDIUM | `drop_page_cache()` after every fill does not free tmpfs pages, `sync` can block on the FUSE mount, and it makes the **next** source read a cold read — the mechanism creates the wait it claims to prevent. |
| R11 | MEDIUM-HIGH | `is_cached` can return `True` via a **substring** match for an entry that is not keyed by the requested id; `llama_server.py:334` then does `mgr.entries[model.id]` → **`KeyError`** → the prewarm is skipped entirely and the model loads from the slow volume, while the cache still says "cached". |
| R12 | MEDIUM | Staleness is detected by **size only** — no hash, no mtime. A same-size re-upload is served forever, and a *truncated source* deletes a *good* cache entry. |
| R13 | MEDIUM | `RAM_CACHE_BUDGET_GB=0` (the notebook's "cache off" value) sets the budget to **zero** rather than disabling caching, and the notebook still calls `ensure_in_ram` unconditionally — the "safe" configuration is not low-RAM. |
| R14 | MEDIUM | The free-space check is against the **temp file's** filesystem, not the destination volume; a failed download parks its partial **on the model volume** (`downloads.py:209-214`, `:380-402`), so a failed 7 GB download needs 14 GB free. |
| R15 | MEDIUM | Abandoned downloads leave multi-GB `.resume.*` files on the model volume forever — they are *reported* but never reaped (`server.py:831-858`). |
| R16 | LOW-MED | The copy is never size-verified after publication, and the VRAM resolver serves `ram_path` with no validation and a substring match that can return a *different* model's cached file. |
| R17 | LOW | The alias map is keyed by filename fragments — `artemis_model.gguf` registers the alias `model.gguf`, which then points at whatever was cached last. |
| R18 | LOW | `prewarm_models` uses the role `"anchor"`, which maps to the cache **root**, so the same model is copied twice under two names. |

### Process lifecycle (`server.py`, `llama_server.py`)

| # | Sev | Finding |
|---|---|---|
| L1 | HIGH | **No port pre-check and no `EADDRINUSE` handling.** llama.cpp loads the weights *before* it binds its listener, so a duplicate launch allocates the entire weight set into VRAM and only *then* fails to bind — the OOM happens before the bind error is printed. And in the window before the new process binds, `/health` is answered by whatever is already on that port. |
| L2 | HIGH | **A failed model launch kills the entire agent at import.** `llama_server.py:388-393` raises `RuntimeError` out of `_spawn` → `launch()` → `server.py:1308`, which is **module-level** — the import of `server.py` fails, `uvicorn.run` never executes, the process exits. With `restart: unless-stopped` this is a restart loop, and each iteration launches another llama-server that briefly allocates VRAM before dying. |
| L3 | HIGH | **The registry stack has no stop path at all.** `llama_server.py` contains exactly one process-control call. The stack's servers on :8081+ are never stopped, are not reaped when the agent exits, and on the next start collide with the same fixed ports → `EADDRINUSE` → L2. |
| L4 | HIGH | The readiness probes are 0.8–1.0 s HTTP pings whose failure modes are **all** interpreted as "not running" — a busy llama-server reads as dead, and the arbiter spawns a second one. |
| L5 | HIGH | The JIT load timeout is **60 s** (`vram_manager.py:726-731`) for a 19–23 GB GGUF, while the other launcher in the same codebase uses **600 s** (`llama_server.py:67`). From a Google-Drive FUSE mount the load takes minutes, so it times out, the half-loaded server is killed, and the request fails with `retryable: False` — telling the backend the provider is permanently broken. |
| L6 | HIGH | The agent holds its own CUDA context on the same card (Laya on CUDA, `server.py:1596-1613`), and `torch.cuda.empty_cache()` frees the *agent's* blocks, not the llama-server's — a no-op for the actual problem. Any CUDA driver error raised in a worker thread is process-fatal, so the agent dies with no Python traceback. |
| L7 | MEDIUM | There is **no supervisor loop** in the agent: no watchdog for the stack's servers, no reaper for the JIT server, no PID/lock file, no `atexit`/SIGTERM handler. A crash becomes a *persistent* outage. |
| L8 | MEDIUM | Upstream failures are reported `retryable: False` (`server.py:1433-1443`), so a transient OOM kill makes the backend give up on the provider rather than waiting and retrying. |
| L9 | MEDIUM | The VRAM arbiter runs even when the LLM is served by a **remote** upstream (`server.py:1394-1399`) — spawning a local 19 GB llama-server for a request that is going to another machine. |
| L10 | MEDIUM | Cancellation leaks the lease and the HTTP client: `asyncio.CancelledError` is a `BaseException` and is not caught by `_bounded_to_thread`'s `except asyncio.TimeoutError` (`server.py:169-204`). |
| L11 | MEDIUM | `free_comfy_vram()` runs on **every chat request** — unloading the diffusion model from VRAM unconditionally — and the only "wait for release" is a fixed 400 ms sleep. Six fixed sleeps in the file stand in for "wait for the GPU". |
| L12 | MEDIUM | The Laya decision path can load the model twice, and it blocks on the arbiter's lock, which a model load holds for its entire duration. |
| L13 | LOW | `/download-model` with `model_id` bypasses the response envelope, so a failed fetch is invisible to the backend (it only recognises `status == "error"`). |
| L14 | LOW | Hybrid mode hardcodes the upstream port (`:1279`) while the arbiter reads `LLM_PORT` from the environment — setting it to anything but 8003 makes every request 503. |

### Colab notebook vs. the arbiter

| # | Sev | Finding |
|---|---|---|
| N1 | HIGH | **The notebook's watchdog and the arbiter both own :8003.** The arbiter's `stop_llama` pkills `llama-server.*8003` — including the **notebook's** server (`notebook:2126-2157`, `:2197`) — and then starts its own. The notebook's watchdog (`notebook:2551-2572`) sees its server dead and starts a third. Two ~19 GB servers loading at once → guaranteed OOM, then a port conflict, then whichever wins serves requests while the other dies. |
| N2 | MEDIUM | The notebook's startup health loop checks `comfy` and `llm` but **never the agent sidecar** in hybrid/model mode — which is exactly the mode where the agent serves the public tunnel (`notebook:1055`, `:2280`). |
| N3 | MEDIUM | The `remote_agent` image and the `remote_agent` notebook are separate copies of the same worker logic; the notebook's `pkill` patterns and port assignments have drifted from `vram_manager.py`'s. |

---

## 3. What is actually FINE — do not change

1. **Free VRAM is measured live on every call.** `vram_manager.py:128-151` uses `torch.cuda.mem_get_info` with an `nvidia-smi` fallback; there is **no cached stale free-VRAM value anywhere**. All the staleness is *ordering* (P3) and *decision-input* (P2) staleness, not caching.
2. **Eviction granularity is always whole-model** — the llama process is terminated, ComfyUI's models are all unloaded, Laya's instance is dropped. There is no partial-model eviction that could leave a half-resident model.
3. **The Laya unload path is textbook-correct**: drop the reference → `gc.collect()` → `torch.cuda.empty_cache()`. The defects are around it (S6, S12), not inside it.
4. **The lock itself is correct** — a single `RLock`, a `Condition` built on the same lock so `wait()` releases it, and `release_lease` calls `notify_all()` under the lock. The problems are *what is held and for how long* and *that prepare+acquire are not one atomic step* — not the absence of locking.
5. **The GGUF header parser** (`_get_gguf_layer_count`, `:1069-1103`) is correct for the value types it handles and validates the range `8..256`. It is a better source than the name heuristics (S11).
6. **Using the GGUF file size as the weight-VRAM proxy is sound** — llama.cpp keeps quantized weights quantized on the GPU. It is the *reserve* (P4) and the *per-layer* estimate (S11) that are wrong, not this.
7. **The download pipeline's concurrency control is correct** — `exclusive_path_lock` (flock), `_unique_temp_path` (per-attempt), and an atomic `_replace_or_move` publish together make two concurrent downloads of one destination impossible to interleave.
8. **Resume is implemented correctly** — the remote identity binds URL + ETag + Last-Modified + size; `Range` + `If-Range` are sent; the 206 branch validates the offset; a changed remote drops the partial; the 416 branch handles "already complete"; an identity mismatch truncates rather than appends. The blind-append corruption is genuinely prevented.
9. **The out-of-space policy is right** — a partial is deliberately *not* parked on a full volume, and the message explains why. The free-space check runs before a single body byte is written.
10. **The "indeterminate" validation contract is honoured** — a transient EIO parks the file rather than deleting it, so a 7 GB model is not destroyed by one bad read.
11. **A 404 is reported once, not retried**; the retry budget is 3 with exponential backoff.
12. **The cache fill never deletes the source** — the RAM cache is never the only copy.
13. **A bad request does not kill the agent** — Starlette's `ServerErrorMiddleware` turns a handler exception into a 500 and the process keeps serving. The processes that die, die at *import* (L2) or in *native code* (L6).
14. **`provider_core/auth.py` is correct** — constant-time comparison, total functions, never raises.
15. **`provider_core/responses.py` is sound** — one canonical envelope, envelope-last merge, and a normaliser for third-party bodies. The only bypass is L13.
16. **The lease is released on all three normal exits** of the chat route. The leak is on the *acquisition* side (P1).
17. **The download's single-file publish is atomic** (`os.replace`). The bug is the *shared* temp name (R5), not the rename.
18. **The notebook's credential names are all accepted by the backend** — every one is canonical or a declared registry alias, and the engine's port defaults (8188/8001/8003) match the notebook's.

---

## 4. What was fixed in this pass

The fixes below are the ones that are small, local, and provably correct
without the hardware to test on. Each is marked with the finding it closes.

### The four primary defects

| Fix | Where | What |
|---|---|---|
| **P1** the lease leak | `vram_manager.py`, `server.py` | **One acquire, one release.** `prepare_for_workload` now takes the lease and the caller releases it — the caller's second `acquire_lease` is gone. The drain is a wait-only `_wait_for_drain`; the conflict test is one shared `_lease_conflicts` so the two can never disagree. **The deterministic 60 s tax on every image request is gone.** |
| **P2** the KV flip-flop | `vram_manager.py` | `config_matches` now compares only what the CALLER asked for. The auto-derived KV type is a function of the free VRAM at the moment of the call, and free VRAM swings by ~10 GB as ComfyUI takes and releases its checkpoint — so the old comparison decided the running server was misconfigured and tore down a 19.5 GB model for a full reload, on every alternating request. The KV type is now only chosen when a server is actually being started. |
| **P3** the swap race | `vram_manager.py` | `stop_llama` returns whether the server is actually gone; a SIGKILL that timed out is logged as an error rather than swallowed; the `pkill` pattern is anchored to the port (`--port[ =]8003`, not `llama-server.*8003`, which also matched `:18003`) and a missing `pkill` is reported instead of silently ignored. The caller then **polls `mem_get_info` until the VRAM actually comes back** instead of sleeping a fixed 200 ms. |
| **P4** the KV reserve | `vram_manager.py` | The flat `reserve_mb = 1800` is gone. It is now computed from the model's real geometry — read out of the GGUF header (`block_count`, `head_count`, `head_count_kv`, `embedding_length`, `key_length`) — times the context window, times the KV precision, plus a compute allowance. For the 32k f16 context the registry actually ships, that is **9192 MB: 5.1x the old constant.** The old value was calibrated for an 8k context at q8_0, a quarter of what the worker runs. |

### Secondary fixes

| Fix | Where | What |
|---|---|---|
| **S1** `is_multi_gpu` | `vram_manager.py` | The device indices must differ AND must EXIST. `_get_cuda_device_count()` now returns **0 for "unknown"** (it used to return 1, which is indistinguishable from "one real GPU"), so a box whose count could not be measured is judged on the configured indices, while a real single-GPU L4 with `LLM_GPU_DEVICE=1` — a device that does not exist — is correctly NOT multi-GPU, and the eviction paths stay armed. |
| **S3** the 0.8 s probe | `vram_manager.py` | `is_comfy_generating` now FAILS SAFE: a probe that cannot reach ComfyUI means "busy", not "idle". A false negative there frees ComfyUI's VRAM under a live generation. |
| **S4** the honest status | `vram_manager.py` | The image path answers `insufficient_vram` when the target was not reached, instead of `ready` unconditionally. The LLM path answers `llm_launch_failed` instead of `ready` when the launch failed. "No GPU at all" stays `ready` — there is nothing to enforce and nothing to report. |
| **S5** the Laya drain | `vram_manager.py` | `get_laya_device` no longer calls `free_comfy_vram()` without checking that ComfyUI is idle. The Director runs on every chat turn, so this could yank the checkpoint out from under a running generation. |
| **S6/S7** the Laya leak | `server.py` | A Laya model loaded by the server's own fallback is now registered with the manager, so `unload_laya_cuda()` can free it. It was an un-evictable permanent VRAM leak that skewed every later free-VRAM reading. |
| **S8** the ngl floor | `vram_manager.py` | `max(4, ...)` became `max(0, ...)`. The floor OVERRODE the budget: when the arithmetic allowed 3 layers, 4 were forced onto the GPU. |
| **S9** the layer estimates | `vram_manager.py` | The name heuristics were wrong for two shipped families (26/27B is 62 layers, not 46; 12B is 48, not 40). The GGUF header is now the primary source. |
| **S11** the layer counts | `vram_manager.py` | Same fix, for the fallback path. |
| **L2** the crash loop | `llama_server.py` | A model that fails to launch no longer takes the worker down. `launch()` records it as unavailable and continues; the call site is module-level code, so the old exception killed the import and the container restart-looped, each iteration allocating VRAM before dying. |
| **L3/L7** the orphans | `llama_server.py`, `server.py` | The stack has a `stop()`, the agent has a shutdown hook and an `atexit` backstop, and a failed spawn is terminated AND reaped. The stack's servers used to survive the agent's exit and collide with the next start on the same fixed ports. |
| **L5** the load timeout | `vram_manager.py` | 60 s -> 600 s, matching the other launcher in the same codebase. 60 s cannot load a 19.5 GB GGUF from a FUSE mount. |
| **L8** the non-retryable | `server.py` | An unreachable upstream is now `retryable: True`. It was `False`, which told the backend "this provider is permanently broken" when the model was merely still loading. |
| **N1** the double load | the notebook, `server.py` | The notebook no longer starts its own llama-server in `llm` mode — the agent's stack serves the LLM — and its watchdog no longer restarts one. The agent's arbiter no longer JIT-launches when the stack (or an operator's server) already answers. The two used to load the same 19.5 GB of weights onto one 24 GB card, which is an OOM by construction. |
| **R1** the empty cache | `server.py` | `prewarm` now defaults to True. It was False and no caller set it, so the RAM cache was NEVER populated in the Docker/Modal deployment — which is the whole reason the worker can share one card. |
| **R2** the tmpfs trap | `docker-compose.yml`, `vram_manager.py` | `shm_size` is declared (Docker's default is 64 MB, and the agent cannot remount without CAP_SYS_ADMIN). The capacity is now measured and REPORTED, so a cache that cannot hold the model is visible instead of silent. |
| **R4** the partial copy | `ram_manager.py`, `server.py` | `ensure_dir_in_ram` copies to a staging directory, verifies the byte count, and `os.replace`s it into place. The Laya loader now requires a VERIFIED cache entry, not "the directory exists and is non-empty" — a copy that died on ENOSPC left a partial directory that the next request loaded. |
| **R5** the shared temp path | `ram_manager.py` | The temp name is per-attempt (`pid` + `uuid`). It was deterministic, so the notebook's prewarm and the agent's prewarm wrote the SAME file concurrently. |
| **R6** the wiped anchors | `ram_manager.py` | `_rescan_ram_dir` preserves `is_anchor`. It hard-coded `False` and overwrote the entry, and a rescan happens on every model-path resolution miss — so the pinned prose model could be evicted. |
| **R7** the unrecognised header | `provider_core/validation.py` | An unrecognised header is now an ERROR. It used to append no error at all, and "no errors" means valid — so a 200-with-a-truncated-body was published as a model. A JSON error envelope is now detected by content, not by the header. |
| **R8** the event-loop stall | `server.py` | The multi-GB RAM copies run off the event loop, so a download no longer makes the worker look dead to the backend's health probe. |
| **R11** the cache/entry mismatch | `ram_manager.py`, `llama_server.py` | `resolve_entry` returns the ENTRY, so "is it cached?" and "where is it?" can no longer disagree — which is what produced a swallowed `KeyError` and a skipped prewarm. |
| **R13** the zero budget | `ram_manager.py` | A zero budget now means "caching off" and `ensure_in_ram` returns the source path. It used to mean "a zero-byte budget", so every call raised and every caller logged a warning. |
| **P1b** the RAM capacity | `vram_manager.py` | `_detect_ram_capacity_gb` reads `/proc/meminfo` (psutil is not a dependency), so the "auto" policy engages on a small machine. It returned a hardcoded 32.0, so caching was enabled on an 18 GB box. |

### The contract these fixes are pinned by

`backend_v2/tests/test_vram_manager_and_arbiter.py` is the backend's contract
test for the sidecar's arbiter, and it is strict about three of the behaviours
above: that `prepare_for_workload` HOLDS the lease for the duration of the
work, that the image path frees ComfyUI's VRAM when the LLM needs the room,
and that the multi-GPU path is chosen from the configured device indices. The
first pass of these fixes broke nine of its tests, and the fixes were then
re-shaped to satisfy both the contract and the audit — the lease in particular
moved to "prepare takes it, the caller releases it", which is both symmetric
AND closes the window between the drain and the work.

### Deliberately not changed

- The arbiter's design. It can be made correct; rewriting it without the
  hardware to test on would be a worse trade.
- The KV-cache geometry fallback, which still assumes a 128-dim head when the
  GGUF has no `key_length`.
- `psutil` as a dependency — the `/proc/meminfo` fallback is correct.
- Automatic provider registration is implemented, but the notebook still
  prints the credentials, because the backend may be unreachable from the
  notebook and the manual path must remain.

## 4. Fix plan

Ordered by symptom relief per unit of risk. The first block is the "make it stop happening" set; the second is the "make it stop being silent" set.

### Block 1 — stop the bleeding (each is a small, local, verifiable change)

| # | Fix | Files |
|---|---|---|
| 1 | **P1** — make the lease accounting symmetric; honour `acquire_lease`'s `False` | `vram_manager.py`, `server.py` |
| 2 | **P2** — derive the KV type from the model + requested ctx, not from free VRAM | `vram_manager.py` |
| 3 | **P3** — stop → wait for exit → **verify VRAM released** → only then allocate | `vram_manager.py` |
| 4 | **P4** — compute the KV reserve from ctx + KV type + model geometry | `vram_manager.py` |
| 5 | **S1** — `is_multi_gpu` requires `device_count >= 2` | `vram_manager.py` |
| 6 | **S8** — drop the hard `max(4, …)` floor on `ngl` | `vram_manager.py` |
| 7 | **S4** — return a real status when the VRAM target was not reached | `vram_manager.py` |
| 8 | **S9** — a failed "is ComfyUI generating?" probe means **busy**, not idle | `vram_manager.py` |
| 9 | **S5** — gate `free_comfy_vram()` in `get_laya_device()` on the drain | `vram_manager.py` |
| 10 | **R6** — `_rescan_ram_dir` must not wipe `is_anchor`; unify the anchor match rule | `ram_manager.py` |
| 11 | **R4/R5** — atomic + verified directory copy; unique temp name; a flock | `ram_manager.py` |
| 12 | **R11** — resolve `entries` through the alias map | `llama_server.py` |
| 13 | **R2** — detect the backing store's capacity and report it | `ram_manager.py` |
| 14 | **L5** — raise the JIT load timeout to match the other launcher | `vram_manager.py` |
| 15 | **L2** — a failed stack launch must not kill the agent at import | `llama_server.py` |
| 16 | **N1** — one owner for :8003; the watchdog must not fight the arbiter | the notebook generator |
| 17 | **L3** — a `stop()` for the stack + an `atexit`/SIGTERM reaper | `llama_server.py`, `server.py` |
| 18 | **R8** — move the multi-GB copies off the event loop | `server.py` |
| 19 | **R1** — the download must populate the cache, not merely permit it | `server.py` |

### Block 2 — stop it being silent (observability, no behaviour change)

| # | Fix |
|---|---|
| 20 | Capture the llama child's stderr so an OOM in the child is visible in the agent's log. |
| 21 | Report the real cache state in `get_status()`: backing-store capacity, population, why a prewarm was refused. |
| 22 | Report `insufficient_vram` distinctly from `ready`, and surface it through the agent's response. |
| 23 | Log the reserve, the KV geometry and the layer budget with every launch decision. |

### Deliberately out of scope

- Replacing the arbiter with a scheduler. The current design can be made
  correct; rewriting it without the hardware to test on would be a worse
  trade.
- Automatic provider registration by the notebook — implemented separately
  (see the notebook section of the commit that accompanies this audit).
- `psutil` as a dependency (the `/proc/meminfo` fallback is correct; the
  hardcoded `32.0` is the bug).
