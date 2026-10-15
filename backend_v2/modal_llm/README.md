# TNH LLM — roles, models, and how they are chosen

This directory is the **one place** model choices live. Nothing in the Modal app
or the backend hardcodes a model id; both read `models.json`.

```
backend_v2/modal_llm/                    SHARED — three consumers import it
  models.json    <- THE file you edit. Roles, fallback order, per-model config.
  registry.py    <- parses it, applies defaults, validates.
  README.md      <- this file.

deployables/modal/llm/app.py             DEPLOYABLE — imports the registry above
backend_v2/services/llm_router.py        RUNTIME  — job kind -> role
remote_agent/llama_server.py             RUNTIME  — same roles on your own box
```

`app.py` used to live here too, beside the files it imports. It moved to
`deployables/` on 2026-10-15 so that every cloud worker the engines name has its
source in one place, and it now finds this directory by walking up to the repo
root — the same bootstrap `deployables/modal/image/` uses. Deploy it with
`bash scripts/deploy.sh llm`.

This directory lives **inside `backend_v2/`**, not at the repo root, and that is
load-bearing. It used to sit at the repo root and the backend resolved it with
`Path(__file__).parents[2]` — the repo root in development, `/` inside the
backend container, whose Docker build context is `backend_v2/` and therefore has
no repo root above it. `GET /llm/routing` then 500ed in the container while
every test passed locally. `registry.py` now resolves by *search*, preferring
the file beside it, with `LLM_REGISTRY_PATH` as an override.

## The two roles

| role | what it serves | why it exists |
|---|---|---|
| `rp` | in-character prose, scene narration, story continuations | chosen for prose quality and willingness |
| `util` | image captioning, tool calls, memory extraction, summaries, image prompts | chosen for instruction-following and structure |

An rp finetune is *worse* at structured output and tool calls, and most rp
finetunes have no vision at all. Sending everything to the rp model is why
roleplay quality and agentic quality could not both be good.

## Changing what runs

Edit `models.json`:

- **Reorder** a role's `fallback` list to change its primary. First is primary.
- **Set `enabled: false`** to bench a model (it stops being deployed and stops
  being routed to, but nothing is removed).
- **Add a new model** to `models` and to a role's `fallback`. It will be
  downloaded, deployed as its own Modal function, and become routable.
- **Change a sampler** — per model, not enforced server-side, but the backend
  sends it.

Then:

```bash
modal deploy deployables/modal/llm/app.py                       # pick up the new registry
modal run deployables/modal/llm/app.py                          # download any new weights
modal run deployables/modal/llm/app.py::urls                    # refresh the URL manifest
```

The backend does not need a restart: `llm_router` re-reads on process start, and
`refresh_router()` exists for a future reload endpoint. A new provider is needed
only if the URL changed.

**Adding a job kind** means adding it to `ROLE_BY_KIND` in
`backend_v2/services/llm_router.py`. An unknown kind silently routes to the rp
model, so a mistake there is *invisible* rather than loud — that is why the test
suite asserts every kind the codebase emits appears in the table.

## Which model actually serves a request

Precedence, highest first:

1. **A per-chat or per-story pin** (`chat.llm_model` / `story.llm_model`). The
   user chose it, so it wins over every automatic decision.
2. **The router's primary for the job kind** — but only when a real LLM provider
   actually serves that model. This condition is what keeps a one-provider
   deployment on its existing model instead of routing it to a model nothing can
   reach.
3. **`get_default_llm_model()`** — the previous single-model answer, unchanged.

So the two-model split activates itself: deploy a provider whose
`config.default_model` matches a registry entry, and that role starts routing to
it. Until then everything resolves exactly as it did before.

## Per-model config

| field | meaning |
|---|---|
| `repo` | Hugging Face GGUF repo |
| `gguf` | exact filename, or a glob that must match exactly one file |
| `mmproj` / `mmproj_repo` | vision projector; `mmproj_repo` fetches it from another repo (used for the stock Gemma 4 projector on abliterated models) |
| `dir` | Volume folder. Omit and it defaults to the id; **set it to share another model's weights** so one download serves two functions |
| `ctx` | context **per slot**; total = `ctx * parallel` |
| `parallel` | concurrent slots; Modal runs with `max_inputs = parallel * 2` |
| `kv` | KV cache quantisation — `q8_0` or `q4_0`. Lower this first on OOM |
| `gpu` | `L40S` (48 GB) or `A100-40GB` |
| `idle` | seconds warm after the last request. Per model, so each scales independently |
| `sampler` | suggested sampler values. Sent by the backend, overridable per chat |
| `extra_args` | extra `llama-server` flags, appended last |

## Architecture: ONE container, one llama-server per role

`ChatLLM` is a single Modal class with `max_containers=1`. On container enter it
loads one llama-server **per role**, each on its own port (`8081 + role index`),
so both roles are served by one L40S rather than two cards.

Why: two 31B models are 47.7 GB of weights and cannot share one card at all. The
`util` primary is therefore a **12B** (`gemma3_12b_heretic_util`, 9.3 GB with
vision, filenames and byte sizes verified against the HuggingFace API), which
leaves room:

| | GB |
|---|---|
| Artemis 31B Q5_K_M + projector | 24.7 |
| Artemis KV @ 32k, q8_0 | ~2.1 |
| Gemma 3 12B Q5_K_M + projector | **9.3** |
| Gemma KV @ 16k, q8_0 | ~1.0 |
| CUDA contexts, two servers | ~3.5 |
| **total** | **~40.6 of ~46.7 usable** |

`--swa-full` must stay **OFF**: it makes Artemis's KV cache ~15.7 GB and nothing
fits. The trade is throughput — two llama-servers on one GPU means a reply's
token rate dips while an extraction runs. For one user who waits on one reply at
a time, that is cheaper than a second card.

Changing a role's model is an edit to `models.json` and a redeploy; fetching its
weights is `modal run deployables/modal/llm/app.py::ensure --model-id <id>`.

## Measured (2026-10-11, one-container shape)

| | seconds | note |
|---|---|---|
| llama-server model load | **~17-18** | 23.5 GB GGUF off the Volume, mmap'd |
| Cold container, BOTH roles healthy | **~28** | Artemis's load dominates; the 12B adds ~2 s |
| Warm `rp` call | ~8-10 | |
| Warm `util` call | **~0.5** | the 12B is quick and short-reasoning |
| Concurrent `rp` + `util` in ONE container | **~10.6** | proved they overlap, not queue |
| Streamed `rp` | 194 chunks in ~8 s | via `.remote_gen()` |



| | seconds | what it is |
|---|---|---|
| llama-server model load | **~18** | 23.5 GB GGUF off a Modal Volume, mmap'd — from `load_model: loading model` to `listening on 0.0.0.0:8080` |
| Cold container → first SDK call answered | **~26** | 18 s of load plus Modal's container scheduling and GPU allocation |
| Warm call | **~4–10** | the model is resident and the port is open |
| Primaries download | ~48 GB | `artemis_31b` 23.5 GB + 1.2 GB projector, `gemma4_31b_heretic_util` 21.8 GB + 1.2 GB projector |

So the ~18 s the log shows *is* the cold boot — it is llama-server loading, and
it happens inside `@modal.enter()`, before the first call rather than inside it.
Anything slower than that in Modal's own "cold booting" banner is container
scheduling. If Modal reports cold-booting for minutes while the log already says
`listening`, the container is crash-looping after start, not booting slowly —
which is exactly what a missing dependency in the image looks like.

### Thinking mode: do not try to disable it

These models emit `reasoning_content` before prose. `--reasoning-budget 0` looks
like the fix and is the opposite: it stops llama.cpp *separating* the two, so the
chain of thought lands in `content` and is shown to the reader as prose. The
default keeps it in `reasoning_content`, which the OpenAI-compatible reader
already drops.

What actually matters is the token floor. Reasoning consumes `max_output_tokens`
before any prose is written, so a small budget produces an **empty reply with no
error anywhere** — `completion_tokens` is spent, `content` is `""`,
`finish_reason` is `stop`. Every `rp` sampler therefore carries
`max_tokens: 2048`, which a per-chat sampler still overrides.

## What breaks and how to read it

### A model with no weights must REPORT, not crash-loop

`@modal.enter()` raising for a missing download is the obvious move and the
wrong one. Modal retries enter and then re-creates the container on every call,
so a missing weight becomes an infinite container crash-loop that burns GPU on a
thing that can never succeed.

`@modal.enter()` therefore succeeds for any permanent condition and records
`unavailable_reason`. The methods report it:

- `health()` answers `{"status": "not_downloaded", "reason": ...}` — an
  actionable state, ~7 s, no model load
- `complete()` / `stream()` raise the same reason as a plain non-retryable error

A caller polling health sees "not downloaded yet", which is the state the
frontend needs, rather than a crash-loop it has to infer from retries.


## Known-unverified

This directory has never been deployed. Before relying on it:

- **Gemma 4 chat template.** GGUFs built before roughly May 2026 may carry a
  broken template where the model runs past its turn and prints raw turn tokens.
  Test three turns per model. If it happens, add
  `"extra_args": ["--chat-template-file", "/models/chat-template.jinja"]` to
  that model.
- **Cross-repo vision.** The abliterated `util` models use the *stock* Gemma 4
  projector. That normally works for abliterations, but is untested here.
- **`magnum_diamond_24b`'s filename is a glob.** Its repo has not been listed, so
  the first deploy will fail loudly if it does not match exactly one file.
- **VRAM.** 31B at 32k with `q8_0` KV may not fit one L40S. On OOM: lower `ctx`
  or set `kv` to `q4_0`.
- **Cold start.** Run `modal run deployables/modal/llm/app.py::bench --key <id>` when the
  model has been idle, and send the number back so the `fallback` order can be
  reordered by measured latency rather than by community report.
- **Four models are benched** (`dark_thoughts_v2_31b`,
  `split_untied_31b`, `goetia_26b_a4b`, `styletune_v2_26b_a4b`) —
  fully specified, download nothing until enabled.
