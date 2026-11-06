# Where the provider code lives

Four trees run code that talks to a GPU. They used to be one, got split apart,
and were not fully re-described when they were — so the fastest way to find
something is to know which tree you are in.

| Tree | Runs where | Imported by the backend? | Deployed how |
| --- | --- | --- | --- |
| `backend_v2/services/engines/` | **in-process**, in the backend container | yes — this *is* the backend's provider layer | nothing to deploy |
| `deployables/` | on **Modal** and **Beam** | never | `bash scripts/deploy.sh <target>` |
| `deployables/modal/llm/` | on **Modal** (llama.cpp) | never | `bash scripts/deploy.sh llm` |
| `backend_v2/modal_llm/` | nowhere — it is the **shared registry** | yes (`llm_router`) and `remote_agent/` | not a deployable |
| `remote_agent/` | on **your own** Docker host | never | `docker compose` in that directory |

## The rule that explains the layout

**The backend never imports a deployable, and a deployable never imports the
backend.** Everything crossing that line crosses it over the network.

That is why `deployables/` and `remote_agent/` are not packages, why nothing in
`backend_v2/` imports them, and why the backend's test suite does not run them.
It is also why each deployable resolves its own imports from the repo root at
import time instead of assuming a sibling package — see the bootstrap at
`deployables/modal/image/modal_app.py:27`,
`deployables/modal/tts/modal_app.py:65` and `deployables/beam/beam_app.py:53`.
When `provider_core` moved out from next to the app files (commit `acc86aa3`),
every one of those assumptions broke at once and the whole tree became
un-deployable.

## The split that is not clean

The LLM registry is shared by three consumers — the backend's `llm_router`, the
Modal app, and `remote_agent/llama_server.py` — so it cannot live in
`deployables/` with the other things the backend never imports. What moved:

| File | Where it is now | Why |
| --- | --- | --- |
| `app.py` (the Modal deployment) | `deployables/modal/llm/` | it is a deployable like any other |
| `registry.py`, `models.json` | `backend_v2/modal_llm/` | three consumers import them; no reason to make two of them search |

So the Modal app now resolves its registry by walking up to the repo root rather
than by neighbour — the same bootstrap `deployables/modal/image/` and
`deployables/beam/` use, and for the same reason: a sibling assumption is
exactly what made those trees un-deployable when `provider_core` moved.

`backend_v2/modal_llm/` must stay *inside* `backend_v2/`: the backend container's
build context has no repo root above it, and moving the registry out 500ed
`GET /llm/routing` in Docker while every test passed on the host.

## Which engine owns which provider

`backend_v2/services/engines/engine_factory.py` is the only routing table, and
`backend_v2/services/engines/registry.py` owns provider *type* resolution.
16 provider types are backed by 14 engine classes — several types share a class,
which is deliberate:

- `direct_url` + `remote_comfy` → `DirectComfyEngine`
- `openai_compat` + `ollama` → `OpenAICompatLLMEngine`
- `modal_llm` (and legacy `modal_vllm`) → `ModalLlamaCPPEngine`

Provider *selection* is not in the factory: it is the load balancer's job, and it
filters by **capability**, not by worker type
(`backend_v2/services/load_balancer.py:447`, `provider.serves(task_type)`).

### One exception: the Director does not go through the load balancer

The Laya System 1 Director — the agent that routes a chat turn, audits the
reply, and decides whether the scene wants another turn — calls its engines
**directly**, out of band, with its own 15-second timeouts. It is not a
provider job, it produces no artefact, and it does not belong in the job
queue. But it does mean the Director's failures are not counted by the load
balancer's health accounting, which is worth knowing when a Director
decision is the thing that misbehaved.

Its Tier 3 — the generative fallback, used when the cheaper Laya tiers cannot
answer — selects its provider through the load balancer
(`get_next_provider(task_type="llm")`) so that a dead default provider does
not silently degrade the Director to its keyword heuristic. It used to read
the configured default directly, which ignored provider health entirely.

The TTS and image paths each have their own load-balancer runtime state
(`state_id=3` and `state_id=1`; LLM is `2`). They used to share one, which
meant a TTS outage incremented the failure count on a provider that was
healthy for images and could take it out of image rotation. `get_stats` had
the mirror-image bug: it built its per-modality breakdown out of ONE
modality's counters, so the three numbers it printed were the same number
three times.

### The Illustrator authors a spec, not a graph

The scene Illustrator may choose the generation PARAMETERS of an image —
the sampler, the resolution, the steps, the CFG, the LoRA, the hires pass,
ControlNet, IPAdapter, the detailer — and not only its prompt.

It does so by emitting a **spec** (`backend_v2/core/scene_graph.py`), and the
backend renders the graph with the same `WorkflowBuilder` the stock image job
uses. It is deliberately NOT a raw ComfyUI graph, for three concrete
reasons:

* **There is no node allow-list anywhere in the system.** A raw graph can
  contain any node the provider has installed, including custom nodes that
  read files, reach the network or spawn processes. The only server-side
  gate is ComfyUI's own validation, which runs at DISPATCH — after the
  job has been billed.
* **There is no cost guard.** `EmptyLatentImage.width` and `.height` are
  unbounded, `KSampler.steps` is unbounded, and `batch_size` is unbounded.
  `core/upload_validation.py`'s `MAX_IMAGE_DIMENSION` is about uploaded
  image BYTES and says nothing about the dimensions a workflow requests.
* **The gallery depends on the builder's metadata.** `prompt`, `seed`,
  `steps`, `checkpoint`, `width` and `height` are what the assets table and
  `frontend_v2/src/utils/reuseParameters.js` read. A raw graph bypasses that
  and breaks "reuse parameters".

So the spec is bounded by `backend_v2/core/workflow_limits.py` and checked
BEFORE the job is created, the model names it names are checked against what
is installed (a name that is not installed is dropped, not passed through),
and an answer that is not a spec at all falls back to the prompt-text path —
so the illustration still happens, it is just not node-customised.

The feature is opt-in per chat (`chat.scene_graph_enabled`), off by
default, and the prompt-text path is what it falls back to.

## Names are a contract

The engines look classes and functions up by name in someone else's cloud. The
table in `deployables/README.md` is the verified two-way map, and it is worth
reading before changing either side — an engine naming a method that no longer
exists fails at first dispatch, in the cloud, not in CI.

The health check cannot always see that class of break. `modal_engine.py:158`
probes only `list_models_with_metadata`, whose signature has been stable since
August — so a provider whose deployed build has drifted from the source in this
repo reports **healthy** while `get_file` fails. That is not hypothetical: the
live `modal-zetsuke` provider is in exactly that state, documented in
`deployables/README.md` under "This is a CLOUD artifact".

## Deploying

```bash
bash scripts/deploy.sh list      # targets and what each one builds
bash scripts/deploy.sh check     # preconditions only
bash scripts/deploy.sh image --dry-run
```

There is no `POST /providers/{id}/deploy`, on purpose. See the header of
`scripts/deploy.sh`.