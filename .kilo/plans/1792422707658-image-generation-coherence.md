# Image Generation System Coherence

## Context

A five-part audit of the image generation surface (Simple Generator + Enhancements,
Advanced Generator / workflow builder, Batch/Img2Img/Inpaint, Gallery, job system,
models/providers/discovery) found the following shape.

**The backend is well-factored. The frontend has four generator surfaces that each
invented their own model of "what is a generation request", and the job system
stacks three undocumented contract systems on top of a correct skeleton.**

Concretely:

- `POST /api/generate` accepts two body shapes, chosen by a runtime type-sniff in
  the frontend (`frontend_v2/src/api/generate.js:25-29`). Simple/Img2Img/Inpaint send
  `options` and the **backend** compiles the ComfyUI graph; Advanced sends `workflow`
  and the **browser** compiled it, so the backend skips prompt-shortcut expansion,
  embedding-existence validation and model-type routing entirely
  (`backend_v2/core/workflow_builder.py:441-457`).
- Batch sends a **third**, hand-rolled `options` object
  (`frontend_v2/src/pages/BatchGenerate.jsx:239-291`) carrying 15 of Simple's 36
  option fields, with no preflight.
- The Enhancements panel is the Simple Generator trying to express **graph
  fragments** (hires-fix, ADetailer, FreeU, PAG, latent-upscale) inside a parameter
  dict. That is why the backend needs a procedural graph assembler with node class
  names hardcoded in Python (`backend_v2/core/workflow_builder.py:224, 234, 331, 335, 551`)
  and why the panel can offer a node the target provider does not have.
- The job system has one table, one enum, one FSM and one `update_job` writer — but
  the LLM path bypasses all of it (`backend_v2/services/provider_client.py:196-274`)
  and five recovery paths bypass it too.

**Two job-system defects cost money and kill live work:**

1. A restart re-pays for generations that already completed. `api/lifecycle.py:492-510`
   documents an ordering that the code does not implement: `finalize_persisted_job_outputs`
   ends in `start_background_task(...)` (`backend_v2/services/job_processing.py:420-424`),
   so the `await` returns before finalization runs, and the next statement flips
   `POST_PROCESSING → PENDING` with `claimed_at = NULL` — satisfying the claim
   predicate (`backend_v2/services/job_queue.py:426`) — so a live worker re-runs the
   paid generation. Postgres only, i.e. production.
2. The dashboard "Recover" button fails jobs that are running normally.
   `STALE_JOB_TIMEOUT_SECONDS = 300` (`backend_v2/services/job_service.py:39`) against a
   legal image timeout of 3600 s (`backend_v2/config.py:92`), and
   `POST /api/jobs/recover` applies it to a live instance
   (`backend_v2/api/routes/jobs.py:438-455`) from a button
   (`frontend_v2/src/components/dashboard/FailedJobsPanel.jsx:286`).

## Decisions (agreed)

| # | Decision | Rationale |
|---|---|---|
| D1 | **All four layers, sequenced** | The job-system bugs cost money independently of the UI work. |
| D2 | **Two request kinds, one backend pipeline** | Fixes Advanced's missing validation without turning a 20-field form into a 40-node graph. |
| D3 | **Explicit target provider** | The only way the Enhancements panel can know what is possible. `preferred_provider_id` is **already** honoured end-to-end by the backend (`backend_v2/services/job_submission_service.py:102-110` → `metadata["preferred_provider_id"]` → `backend_v2/services/load_balancer.py`); the frontend simply never sends it. |
| D4 | **Migrate the LLM path onto the canonical job contract** | Otherwise the job system stays three stacked contracts and the frontend keeps needing a helper that accepts both `metadata` and `metadata_`. |

Deployment context that makes D3 tractable: `load-balancer/stats` reports
`total_providers: 1` — five of six providers are `enabled=false`
(`docs/STATUS.md:1043-1050`). "Explicit target provider" is therefore invisible in the
current deployment and correct when a second provider is enabled.

## Target architecture

```
                    ┌──────────────────────────────────────────┐
                    │  ONE request builder                     │
                    │  useWorkflowBuilder.buildPayload()       │
                    │  (Simple · Img2Img · Inpaint · Batch)     │
                    └───────────────────┬──────────────────────┘
                                        │  { kind, options|workflow, metadata, preferred_provider_id }
                    ┌───────────────────▼──────────────────────┐
                    │  POST /api/generate  (discriminated)     │
                    │  kind="guided" → WorkflowBuilder         │
                    │  kind="graph"  → validated + normalized  │
                    │  BOTH → shared postprocess (shortcuts,   │
                    │         embeddings, capability filter)  │
                    └───────────────────┬──────────────────────┘
                                        │
                    ┌───────────────────▼──────────────────────┐
                    │  ONE job contract: update_job()          │
                    │  image + LLM + TTS, one event shape      │
                    └──────────────────────────────────────────┘

   ONE capability source:  GET /api/nodes/capabilities?provider_id=X
     derived from the EXISTING per-provider object_info digest
     (backend_v2/api/routes/nodes.py:143-177, cached per provider)

   ONE "can this provider run this exact file right now" function
     used by BOTH the availability badge and the submit-time gate
```

## Phases

Each phase is independently shippable and must land with its own tests. Order is
load-bearing: later phases depend on earlier contracts.

---

### Phase 0 — Unblock the worktree, then pin the contracts

**0.1 Resolve the uncommitted chat-pipeline tests.** The worktree carries three new
tests in `backend_v2/tests/test_chat_pipeline_execution.py` from the earlier
chat-workflow audit, **two of which fail against current code**:

- `test_the_turn_budget_stops_the_chain` — the "max 4 autonomous turns" limit is not
  enforced on the direct chain path (the gate lives only in `update_stage`,
  `backend_v2/services/pipeline_stages.py:373`, which only runs the chain when it
  *defers* it; the follow-up job also carries `autonomous_turn_count` unchanged, so
  the counter never advances).
- `test_the_turn_counter_advances`.

This is **chat workflow, not image generation** — out of scope for this plan. But
failing tests in the tree block CI. Fix them here (the fix is ~15 lines: move the
budget + strict-autonomy check into `chain_stage` and increment the counter) so the
image-generation work starts from a green tree. If the user prefers, revert the three
tests instead — but do not leave them failing.

**0.2 Contract tests before any refactor.** Extend the existing
`frontend_v2/src/test/eventContractInvariants.test.js` pattern (a vitest that reads
backend source) to pin the generation contract:

- `frontend_v2/src/test/generationContract.test.js`:
  - every field in `GeneratorOptions` (`backend_v2/core/workflow_builder.py:118-182`)
    is either sent by `useWorkflowBuilder.js` or explicitly marked backend-only;
  - `BatchGenerate.jsx`'s option keys equal `useWorkflowBuilder.js`'s option keys
    (**fails today** — mark `@pytest.mark.xfail`-equivalent with the issue id and
    flip it in Phase 4);
  - the `JobStatus` enum is the only vocabulary in `job.status` (no `'queued'`, no
    `'error'`, no `'evaluating_prompt'`).
- Backend: a pytest asserting `MODEL_LOADER_NODES`
  (`backend_v2/core/workflow_parser.py:9-48`) covers every node class
  `WorkflowBuilder` emits that loads a file.

**0.3 Decide and record the canonical option vocabulary.** Three vocabularies
currently exist for "the upscaler": `"Latent"` (frontend, `EnhancementsSection.jsx:73-80`),
`"Latent"|"Pixel"|<model>` (backend, `workflow_builder.py:161`), and
`"latent"|"bilinear"|"nearest-exact"` (`SceneHiresFixSpec`,
`backend_v2/core/workflow_limits.py:84`). The bridge at
`backend_v2/core/scene_graph.py:434` passes the scene value through **without
translating**, so the scene path's own default falls into the `UpscaleModelLoader`
branch and asks for a model named `latent`. Decide which is canonical, make the other
two map onto it explicitly, and pin with a test.

---

### Phase 1 — Job system: stop the money bugs, close the FSM holes

Backend-only. No frontend churn. This is the highest severity-per-line work in the plan.

**1.1 Make post-processing recovery actually wait.** `recover_post_processing_jobs`
(`backend_v2/api/lifecycle.py:515-553`) awaits
`finalize_persisted_job_outputs`, which schedules a background task and returns
(`backend_v2/services/job_processing.py:420-424`). Give the finalizer a
**synchronous mode** (an `await_completion` flag or a separate
`finalize_persisted_job_outputs_sync`) and use it from the recovery path. Add a
**second** guard: the startup sweep
(`backend_v2/services/job_queue.py:928-960`) must exclude `POST_PROCESSING` rows that
recovery has claimed, so a failure in 1.1 cannot re-pay.

**1.2 Derive the stale threshold from the job timeout.** `STALE_JOB_TIMEOUT_SECONDS`
is a global 300 s against a 3600 s image timeout. Make it per-task-type, derived from
`get_job_timeout(task_type)` (`backend_v2/config.py:1147-1160`), and **exclude
`POST_PROCESSING`** from the stale sweep — a job writing its outputs is not wedged.
Also: `POST /api/jobs/recover` must not sweep a live instance by default; make the
stale sweep opt-in (`force=true`) and make the route's default action a *report* of
what is stale, not a mutation. Correct the docstring at
`backend_v2/api/routes/jobs.py:439-440` — it claims "there is no frontend consumer"
and there is one.

**1.3 Repair the FSM.** `JOB_STATUS_TRANSITIONS` (`backend_v2/services/job_service.py:73-93`):
- add `SENT_TO_PROVIDER → PENDING` — provider failover does exactly this
  (`backend_v2/services/job_runner.py:77`) and it is currently rejected on every
  failover, so the job never returns to PENDING and **no event is emitted at all**;
- add `PENDING → COMPLETED` — otherwise a job can hold persisted outputs, stay
  `pending`, and emit no event (the frontend polls forever).

The test suite currently encodes both sides of this contradiction:
`backend_v2/tests/test_job_service.py:269-279` (`test_in_flight_cannot_reset_to_pending`)
forbids the transition its own class docstring says the runner performs. Rewrite the
class so the docstring, the runner and the tests agree, and pin the failover behaviour.

**1.4 Route the recovery writes through the atomic guard.** `fail_stale_running_jobs`
(`backend_v2/services/job_service.py:546-556`) and `fail_stranded_pending_jobs`
(`:612-620`) write the ORM directly, with no `WHERE status = …` predicate. A cancel
racing a recovery is overwritten, and both a `job.cancelled` and a `job.failed` event
are emitted for the same id. Use `repo.update_where_status` — the same guard
`update_job` uses (`job_service.py:790-791`).

**1.5 Fix the silent terminal transition.** `backend_v2/api/lifecycle.py:533` writes
`JobStatus.FAILED` with no `emit_job_event` anywhere in the function, so the frontend
never learns the job failed. Route it through `update_job`.

**1.6 Record a "recovery in progress" marker** so 1.1's second guard (a) has
something to key on and (b) is visible in the job's diagnostics.

**Tests:** pytest asserting (a) a restart with a `POST_PROCESSING` job does not
re-enqueue it and does not re-charge the provider, (b) a job running longer than the
stale threshold is not failed, (c) a failover returns the job to `PENDING` **and emits
an event**, (d) a `PENDING` job can complete, (e) a cancel racing a recovery is not
overwritten, (f) the post-processing recovery failure emits `job.failed`.

---

### Phase 2 — One job event contract (migrate the LLM path)

Per D4. Touches the chat system — that is the blast radius, and the chat/roleplay
suite is the safety net.

**2.1 Make the LLM reducer go through `update_job`.**
`backend_v2/services/provider_client.py:196-274` hand-builds an event payload and calls
`emit_job_event` directly, bypassing the FSM, the atomic guard, `_job_to_dict` and
event-type selection. It uses the metadata key `metadata_` instead of `metadata`, and
puts a **non-`JobStatus`** string (`"evaluating_prompt"`) in `status`.

- Move the LLM sub-states (`evaluating_prompt`, streaming) into a **separate `phase`
  field** on the job. `status` then always holds a `JobStatus`.
- The LLM progress event must still carry `stream_chunk` and `text`. Extend
  `update_job` with an optional extra-payload argument so a caller can add fields to
  the emitted event without bypassing it.
- Unify the metadata key on `metadata`. Keep `metadata_` accepted on read for one
  release, with a deprecation note.

**2.2 Frontend consequences.**
- `frontend_v2/src/hooks/useJobsRealtime.jsx:125` drops any event lacking
  `task_type`/`progress` — after 2.1 the LLM event has both, so the guard stops
  discarding it. Keep the guard but make it a *type* check, not a duck-type check.
- `frontend_v2/src/utils/jobStatus.js:38-45` (`jobMetadata()` accepting both key
  spellings) becomes a legacy shim.
- `frontend_v2/src/hooks/useChatStreaming.js:99,153` — the `'queued'` spelling it
  invents is classified as a **dead spelling** by the project's own canonical
  vocabulary test (`frontend_v2/src/utils/jobStatus.test.js:58-71`). Remove it.
- The `'error'` status handled by `useJobStatus.js:17` but not by `useGeneratorJob.js`
  is legacy; remove it from both.
- `frontend_v2/src/hooks/useChatStreaming.js:173` writes backend and frontend values
  into one store slot — after 2.1 there is one vocabulary.

**2.3 The dead producer.** `backend_v2/api/main.py:65` emits a `job.progress` whose
payload has no `task_type` and no `progress`, so every subscriber drops it — while its
docstring claims it exists "to emit the completion event so the UI can refresh". Either
give it a real payload or delete it.

**Tests:** extend `frontend_v2/src/test/eventContractInvariants.test.js` to assert
**every** job event carries `task_type` and a `JobStatus`-valued `status`; pytest
asserting the LLM path goes through `update_job` (e.g. an invalid FSM transition on
the LLM path is rejected and logged).

---

### Phase 3 — One canonical generation request

Per D2.

**3.1 Make the request kind explicit.** `backend_v2/api/routes/generation.py:44-48`
currently has `workflow` and `options` both optional, inferred by presence. Add an
explicit `kind: Literal["guided", "graph"]`, **defaulting to the current inference** so
existing clients keep working. Replace the frontend's runtime type-sniff
(`frontend_v2/src/api/generate.js:25-29`) with an explicit `kind` argument — that
sniff is also a latent bug: a hand-written ComfyUI graph in Advanced's Raw JSON mode
with a node keyed `"prompt"` or `"mode"` is routed to `payload.options` and fails
validation.

**3.2 Give the "graph" kind the same post-processing as "guided".** Today
`WorkflowBuilder.build_core` does prompt-shortcut expansion and embedding-existence
validation (`backend_v2/core/workflow_builder.py:441-457`); the Advanced path gets
neither. Extract those into a shared module and apply them to the graph kind by
walking every `CLIPTextEncode` node's `text` input.

For model-type routing (FreeU/PAG skipping, `DualCLIPLoader` layout), the graph kind
must **not** have its nodes rewritten — the user hand-placed them. Instead, report
`warnings` on the response: "FreeU_V2 is applied but this checkpoint is Flux". A
warning is the honest behaviour; silently skipping a node the user placed is not.

**3.3 Derive gallery metadata from a graph.** The Advanced path submits
`metadata: {}`, so the gallery shows "Unknown Model"
(`frontend_v2/src/components/dashboard/FeedCard.jsx:331`), "Reuse parameters" fails
(`frontend_v2/src/utils/reuseParameters.js:700-704`), and the PNG sidecar carries none
of the allowlisted keys (`backend_v2/services/image_processing.py:130-146`). Add
`backend_v2/core/workflow_metadata.py` that derives display metadata (prompt,
negative prompt, seed, steps, cfg, sampler, scheduler, width, height, checkpoint,
loras) from a graph, and use it for the graph kind. The frontend already knows how to
do this in reverse (`reuseParameters.js:500-509`); move that knowledge to the backend
where it can be tested.

**Tests:** pytest asserting the graph kind expands shortcuts and validates embeddings;
asserting a graph job carries derived metadata; vitest asserting the two kinds are
distinguished explicitly.

---

### Phase 4 — One request builder (Batch parity)

**4.1 Batch calls the shared builder.** Delete the hand-rolled payload at
`frontend_v2/src/pages/BatchGenerate.jsx:239-291`; call
`useWorkflowBuilder.buildPayload` with a per-item prompt and seed. This alone closes
the largest frontend finding (21 missing fields).

**4.2 Give Batch the preflight and the guards the other three have.**
`BatchGenerate.jsx:308` calls `generateApi.batch` directly. Route it through
`runWithPreflight` (`frontend_v2/src/hooks/useGenerationPreflight.js:38-69`) and add
the checkpoint guard the Simple page has
(`frontend_v2/src/pages/SimpleGenerator.jsx:124-126`) — Batch currently can submit
`ckpt_name: ""` (`BatchGenerate.jsx:265`), which the Simple page's own comment
describes as an error that "blames the provider for something the client sent"
(`frontend_v2/src/components/generator/GenerateButtonBar.jsx:15-27`).

**4.3 Send `unet`/`clip`/`clip2`/`modelType` in every mode.** They are sent only in
the `t2i` branch (`frontend_v2/src/hooks/useWorkflowBuilder.js:80-85`), so a Flux UNET
is transmitted as `ckpt_name` and `modelType` falls back to `"sdxl"`
(`backend_v2/core/workflow_builder.py:141`).

**4.4 Fix `modelType` derivation.** `frontend_v2/src/utils/modelType.js:1-18` keys only
on `flux`/`aura`/`pony`, so SD3 and Illustrious collapse to `"sd15"` and get the
SD1.5 FreeU curve. The catalogue record already carries `base_model` — use it.

**4.5 Normalise `metadata.checkpoint` to the object shape everywhere.** It is an
object in three pages and a string in Batch, and four readers handle it three ways
(`frontend_v2/src/components/dashboard/JobCard.jsx:75`,
`frontend_v2/src/utils/modelDisplay.js:8-10`,
`frontend_v2/src/utils/reuseParameters.js:141-158`,
`frontend_v2/src/components/dashboard/FeedCard.jsx:196`).

**4.6 Stop duplicating `growMask: 6`.** It is hardcoded in the frontend
(`useWorkflowBuilder.js:121`) *and* in the backend
(`backend_v2/core/workflow_builder.py:511`).

**4.7 Consume `batch_index`/`batch_total`.** They are written and read by nobody, and
the backend's docstring promises UI grouping that does not exist
(`backend_v2/api/routes/generation.py:122-123`). Either group the gallery by them or
stop writing them.

**4.8 Report partial failure.** The backend's batch loop has no per-entry
try/except (`backend_v2/api/routes/generation.py:170-190`), so if entry 3 of 10
raises, entries 0-2 are created **and enqueued** (real GPU work committed), the
client gets a 5xx, and `setJobIds` never runs — so the Batch Jobs panel stays empty
(`frontend_v2/src/pages/BatchGenerate.jsx:308-319`) while N-1 images are being
produced. Return the jobs created so far alongside the error, and show them.

**4.9 Fix the lossy round-trip.** "Reuse parameters" restores 4 of 16 enhancement
fields; FreeU/PAG/LatentUpscale are in the metadata and never read back
(`frontend_v2/src/utils/reuseParameters.js`). Restore all of them and write all of
them to the metadata.

---

### Phase 5 — Provider capability discovery (the Enhancements panel)

This is the phase that answers the original complaint: the panel must stop
guessing what the provider can do.

**5.1 Add the capability endpoint.** `GET /api/nodes/capabilities?provider_id=X`,
derived from the **existing** per-provider cached digest
(`backend_v2/api/routes/nodes.py:143-177`). The digest already preserves combo option
lists (`_spec_digest`, `nodes.py:118-140` keeps `spec[0]`), so it already carries
"which model filenames does this provider have" and "does this provider have the
`FreeU_V2` node class". It does **not** carry numeric `min`/`max` (only `default`
survives `_OBJECT_INFO_SPEC_FIELDS`, `nodes.py:115`) — so if the panel should render
numeric ranges from server truth, add `min`/`max` to that tuple and accept the
wider payload, or keep the numeric bounds in the frontend as they are today.

Shape:

```json
{
  "provider_id": "modal-primary",
  "nodes": {"FreeU_V2": true, "PerturbedAttentionGuidance": true,
            "FaceDetailer": true, "UltralyticsDetectorProvider": true},
  "models": {"upscale_models": ["4x-UltraSharp.pth"],
             "bbox": ["face_yolov8n.pt"]},
  "unsupported_enhancements": ["enablePAG", "adetailer"]
}
```

**5.2 Gate the builder on it.** `WorkflowBuilder` must not emit a node class the
target provider lacks. Two layers, because the target provider is not always known
at build time:
- **build time** — when the request carries `preferred_provider_id` (D3), the builder
  consults that provider's digest and records a warning instead of emitting a node
  that would fail at dispatch;
- **dispatch time** — the safety net. Before the workflow is handed to the engine,
  prune node classes the *chosen* provider lacks and record what was pruned in
  `job.metadata_.diagnostics`. Pruning is strictly better than the alternative
  ("node type not found" = hard failure), but it changes output, so it must be
  recorded loudly. There must be exactly one "prepare workflow for this provider"
  step; find it and put the filter there.

**5.3 Add the provider selector.** The generator resolves its target provider
(defaulting to the single eligible image provider, or "Auto" = load balancer) and
sends `preferred_provider_id` — which the backend already honours. The Advanced
Generator's silent `providers.filter(p => p.enabled)[0]`
(`frontend_v2/src/pages/AdvancedGenerator.jsx:36-39`) becomes that selection, so the
`object_info` it reads is the one the job will run on.

**5.4 Render the panel from capabilities.** The panel hides or disables FreeU, PAG,
ADetailer and hires-fix when the target provider lacks the node class; the upscaler
and detector dropdowns list that provider's actual files, not the union catalogue;
the hardcoded `"face_yolov8n.pt"` default (`frontend_v2/src/store/generatorStore.js:161`)
goes away.

**5.5 Fix the dead control.** `adetailerInpaintMasked` is declared
(`backend_v2/core/workflow_builder.py:174`) and sent, and read by nobody — the value
it should drive, `noise_mask`, is hardcoded `True` at `workflow_builder.py:352`.
Either drive it or remove it from the UI.

**5.6 Fix the panel's copy.** "or a Pixel upscaler for structural preservation"
(`frontend_v2/src/components/generator/EnhancementsSection.jsx:68`) describes an option
the dropdown does not offer and the backend's `"Pixel"` branch
(`workflow_builder.py:544`) cannot reach from the UI. "Ignored for Flux models"
(`:219`, `:243`) is a rule the backend implements (`workflow_builder.py:433, 436`) and
the frontend only *describes* — the checkbox stays live and silently no-ops. Make
the copy and the behaviour agree.

**5.7 One source for the defaults and the option vocabulary.** The frontend's
`hiresDenoise` 0.5 disagrees with the backend's 0.3, and the input renders a third
number (`EnhancementsSection.jsx:99`); `steps` 25 vs 20. The backend's defaults are
dead code for the guided path because the frontend always sends explicit values.
Add `GET /api/generate/schema` returning the defaults, the option vocabulary and the
capability mapping, and initialise the store from it. This is also the natural place
to publish the single canonical upscaler vocabulary from 0.3.

**5.8 Fix `preflightTick`.** Eleven setters that change hires/adetailer do not bump it
(`frontend_v2/src/store/generatorStore.js:254-267`), so the cached preflight verdict
is not invalidated when the upscaler or detector changes.

**5.9 Extend `MODEL_LOADER_NODES`.** It has no `UltralyticsDetectorProvider` entry
(`backend_v2/core/workflow_parser.py:9-48`), so the ADetailer detector model is never
preflight-validated; the same gap exists in
`backend_v2/services/engines/direct_comfy_engine.py:89-103`.

**Tests:** vitest asserting the panel renders disabled controls for a provider lacking
a node class; pytest asserting the builder does not emit an unsupported node class
and records a diagnostic; pytest asserting the dispatch-time filter prunes and
records; vitest asserting the store's defaults equal the schema endpoint's.

---

### Phase 6 — Models/providers arithmetic, and the Gallery

**6.1 Fix the availability badge denominator.**
`frontend_v2/src/utils/modelAvailability.js:58-98` counts every enabled provider whose
`runtime_state.status` is in `ONLINE_RUNTIME_STATES` — and that status is
`"in_process"` for every provider with an engine, **including LLM and TTS**
(`backend_v2/services/provider_runtime.py:115-117`). A checkpoint on both image
providers renders "Partial — 2/3 online providers ready". Count only providers that
can serve the model's class.

**6.2 Stop writing immortal `pending` rows.**
`backend_v2/services/model_downloader.py:60-77` writes `status="pending"` for every
enabled provider *before* the LLM/TTS skip at `:108-117`, so LLM/TTS providers
accumulate a permanent `pending` row for every image model — which then feeds 6.1.

**6.3 One "can this provider run this exact file right now" function.** The badge uses
a model-level aggregate; the submit-time gate uses the exact
`(directory, filename)` pair (`backend_v2/services/model_availability_service.py:115-136`).
They disagree about the same row
(`frontend_v2/src/utils/modelAvailability.js:73-80`). One implementation, used by both.

**6.4 Unify the two React Query caches of `/api/files`.** The Models Manager and
`ModelSelector` use `['models','list',…]`; Simple/Batch/Inpaint/Settings/Onboarding use
`['model-directory', dir]`. Only the former is invalidated on a reconcile
(`frontend_v2/src/hooks/useProvidersPageData.js:180, 215, 394-407`), so the generators
stay stale for 5 minutes after a model installs.

**6.5 Fix the dead query keys.** `CredentialsTab.jsx:124` and `DeployTab.jsx:126,152`
invalidate `['providers']` and `['provider-status-cards']`; the real keys are
`['providers-page','providers']` and `['providers-page','load-balancer']`
(`frontend_v2/src/constants/queryKeys.js:32-36`). Neither dead key matches anything, so
the Providers page does not refresh after a credential edit or a deploy.

**6.6 Fix `file.path`.** `frontend_v2/src/components/model-manager/ModelDetailsModal.jsx:556`
reads `file.path`, which the `/api/files` projection does not have
(`backend_v2/api/routes/files.py:1501-1539`) — so LLM providers are always filtered
out of the Provider Status list.

**6.7 Gallery fixes.**
- Replace the four full-invalidate sites
  (`frontend_v2/src/pages/Dashboard.jsx:354`,
  `frontend_v2/src/hooks/useDashboardSelection.js:123`,
  `frontend_v2/src/hooks/useDashboardModals.js:14, 27`) with
  `refetchNewestGalleryPage` — invalidating a `useInfiniteQuery` refetches every
  loaded page sequentially (`frontend_v2/src/hooks/useGallery.js:112-130`).
- Fix the completed-but-not-yet-indexed job that **vanishes** from the gallery
  (`frontend_v2/src/utils/dashboardItems.js:241-298` returns without pushing, and `:305`
  then excludes it because it is `completed`).
- Fix the desktop polling gap: with the socket down, the active-jobs list is never
  polled on desktop (`frontend_v2/src/hooks/useActiveJobs.js:27-33`).
- `useGalleryAutoRefresh.js:72-76` — the `invalidateQueries` branch is unreachable;
  remove it.

---

## Validation

| Layer | Command | Gate |
|---|---|---|
| Backend | `cd backend_v2 && pytest` | 0 failures. `-n auto` is the default (`pytest.ini`). |
| Backend lint | `cd backend_v2 && ruff check .` | clean (F rules only). |
| Frontend | `cd frontend_v2 && npm test` | 0 failures. |
| Frontend lint | `cd frontend_v2 && npm run lint` | 0 errors (12 warnings are pre-existing, `docs/STATUS.md:152-156`). |
| Frontend build | `cd frontend_v2 && npm run build` | clean. |
| E2E | `frontend-e2e.yml` (Playwright) | green. |

**Contract tests to add** (these are what make the refactors safe):
- `frontend_v2/src/test/generationContract.test.js` — the options schema, the two
  request kinds, the job status vocabulary (0.2).
- Extend `frontend_v2/src/test/eventContractInvariants.test.js` — every job event
  carries `task_type` and a `JobStatus` (2.2).
- Backend pytest — the capability gate, the FSM edges, the recovery ordering.

**Manual verification of the user-visible sequences the audit found broken:**

1. Add a model in Discovery → it appears in the Models Manager → pick it in the Simple
   Generator → it must not produce a "Missing Models" dialog (6.1-6.4).
2. Restart the backend with a job in `POST_PROCESSING` → it must not re-run the
   generation (1.1). Check the provider's job list before and after.
3. Start a job that runs longer than 5 minutes → press "Recover" in the dashboard →
   it must not be failed (1.2).
4. Enable FreeU with a Flux checkpoint → the panel must disable the toggle, and the
   backend must warn rather than silently skip (5.4, 5.6).
5. Target a provider without Impact Pack → ADetailer must be disabled, and if a graph
   still contains `FaceDetailer` the dispatch filter must prune and record it (5.2).
6. Run a Batch with a Flux UNET → it must not be transmitted as `ckpt_name` (4.3).
7. Run a Batch of 10 with one bad entry → the 9 good jobs must be visible in the
   Batch Jobs panel (4.8).

## Risks

| Risk | Mitigation |
|---|---|
| **Phase 2 touches the chat system.** | The chat/roleplay suite is the safety net. Land 2.1-2.3 as one commit with no behavioural change beyond the `status`→`phase` move, and update the chat frontend in the same commit. |
| **Phase 5's dispatch-time pruning changes output** for users whose provider lacks a node. | The alternative is a hard "node type not found" failure. Prune, and record every pruned node class in `job.metadata_.diagnostics` so it is visible. |
| **Phase 3's request envelope breaks external clients.** | `kind` defaults to the current inference; the old body shape keeps working. |
| **Phase 4 changes Batch's request** for 21 fields. | Batch currently cannot express those fields, so this is additive — but the Batch test needs updating and a preflight failure can now block a submission that previously went through. |
| **Phase 1 changes recovery behaviour** on a production database. | The recovery path only runs at startup and on explicit request. Test against a Postgres instance, not SQLite (the `_DB_CLAIMS_ENABLED` gate is Postgres-only, `backend_v2/services/job_queue.py:28`). |
| **Phase 5's capability endpoint depends on a live provider.** | It reads the cached digest; a provider that is down has no digest. Return an explicit "capabilities unknown" rather than an empty capability set, and have the panel degrade to "unknown" rather than "unsupported". |

## Out of scope

- **The chat-workflow turn-budget bug** (Phase 0.1 resolves the failing tests; the
  fix itself is a separate plan).
- **Hash/integrity verification.** `ProviderVersionStatus.verified_at`
  (`backend_v2/core/entities.py:930`) has zero writers and `ModelFile.hash_sha256`
  conflates the upstream expected hash with the provider's locally computed one. The
  download gate is size + magic bytes
  (`remote_agent/provider_core/downloads.py:105-135`). Real, but low severity.
- **`jobs_cleanup` has zero consumers** — the `jobs` table grows without bound.
- **The "send to story sandbox" gallery action** — a feature, not a coherence fix.
  The flow is currently one-way (`StorySandbox.jsx:1146-1150` → `/batch-generate`).
- **Voice models** — a separate catalogue (`voice_models`), unrelated to the image
  catalogue.
- **`get_pending_downloads` has no per-provider assignment filter** — every provider
  converges on the whole catalogue. Coherent as a policy, but undocumented.
- **`/api/v2/models/catalog` returns the LLM registry, not models** — an API-surface
  decision, not a cleanup.

## Open questions

None blocking. Two decisions are recorded above and can be revisited during
implementation without changing the plan's shape:

- **0.3** — which upscaler vocabulary is canonical (`"Latent"`/`"Pixel"`/model name
  vs `"latent"`/`"bilinear"`/`"nearest-exact"`). The plan assumes
  `"Latent"`/`"Pixel"`/model-name, because that is what the backend already branches
  on and what the frontend already offers.
- **5.1** — whether the capability payload should also carry numeric `min`/`max`
  bounds. The plan assumes **not** (the digest deliberately drops them, and the
  frontend keeps its numeric bounds), because widening the digest reverses a
  measured size optimisation.
