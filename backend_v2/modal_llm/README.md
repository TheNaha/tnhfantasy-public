# TNH LLM — roles, models, and how they are chosen

This directory is the **one place** model choices live. Nothing in the Modal app
or the backend hardcodes a model id; both read `models.json`.

```
modal_llm/
  models.json    <- THE file you edit. Roles, fallback order, per-model config.
  registry.py    <- parses it, applies defaults, validates. Shared by both sides.
  app.py         <- the Modal deployment. Registers one function per enabled model.
  README.md      <- this file.
backend_v2/services/llm_router.py  <- job kind -> role. Reads the same registry.
```

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
modal deploy modal_llm/app.py                       # pick up the new registry
modal run modal_llm/app.py                          # download any new weights
modal run modal_llm/app.py::urls                    # refresh the URL manifest
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
- **Cold start.** Run `modal run modal_llm/app.py::bench --key <id>` when the
  model has been idle, and send the number back so the `fallback` order can be
  reordered by measured latency rather than by community report.
- **Four models are benched** (`dark_thoughts_v2_31b`,
  `split_untied_31b`, `goetia_26b_a4b`, `styletune_v2_26b_a4b`) —
  fully specified, download nothing until enabled.
