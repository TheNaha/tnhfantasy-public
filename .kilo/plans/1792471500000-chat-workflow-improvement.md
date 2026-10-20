# Chat Workflow Improvement Plan

**Scope:** make Laya's routing decision actually reach the model, add the axes the design calls for, make the LLM Studio show the real runtime, and let the Illustrator author a real per-scene ComfyUI graph.

**Status:** implementation-ready

---

## 1. Context

The 6-stage pipeline is now manifest-driven and tested (`.kilo/plans/1792422707658-roleplay-system-remediation.md`), and the four defects that made it half-dead are fixed. The **shape** of the workflow matches the intended design almost exactly:

1. User sends a message → 2. backend assembles context → 3. **Laya routes** (never decides the story) → 3a. Fate & Skill Check → 4. the actor agent generates → 5. **Laya audits** → gates fire → **Updater** writes state → 5a. incomplete → continuation (not a turn) → 5b. image trigger → **Illustrator** → 6. **Laya picks the next speaker** → back to 4, max 4 turns → 7. back to the user.

What is missing is the **last mile of the routing decision**. Laya is asked which *prompt variant* to use, Laya answers, and the answer is discarded on the normal chat path. Six seeded variants exist and none of them can change a prompt a user would actually see.

Eight gaps were found. This plan closes all of them.

### The eight gaps

| # | Gap | Severity |
|---|---|---|
| 1 | `selected_variant` is discarded on the normal chat path (`api/routes/world_vault/chats.py:1173-1254`) | **critical** |
| 2 | The chain path's character variant is written to `workflow["character_system_prompt"]`, which **no engine reads** | **critical** |
| 3 | *(misdiagnosis — see §1.6)* the chain's triage was already asking about the right agent | — |
| 4 | No per-model prompt axis exists anywhere — "variations for various LLMs" is not a dimension the system has | high |
| 5 | The Updater's prompt is not gate-specific; only its *schema* is | medium |
| 6 | The LLM Studio shows a parallel question list, not the runtime one | medium |
| 7 | The Illustrator writes prompt *text*; a real per-scene ComfyUI graph is not possible today | medium |
| 8 | Continuation allows 5 generations, not 4 | low |
| 9 | A variant with no `selection_hint` and no `description` can never be selected by Laya — `get_agent_variant_options` only offers variants that have one | medium |

### Locked decisions

| # | Decision |
|---|---|
| D1 | Scope: **everything, including per-scene ComfyUI graphs** |
| D2 | Per-LLM prompt axis: **per-agent, per-model variants** (nullable `model_scope` on `AgentPromptVariant`) |
| D3 | Continuation: **4 total attempts** (1 original + 3 continuations) |

---

## 2. Phase 1 — Make Laya's routing decision real

*The point of the phase: Laya picks the best agent *and* the best prompt. Today it picks the agent and throws the prompt away.*

### 1.1 The main send path honours the variant

`backend_v2/api/routes/world_vault/chats.py:1173-1254` has three branches. Each must resolve the agent profile **and** Laya's chosen variant.

- **Narrator (`:1174`)** — currently uses the hardcoded `get_system_prompt_blocks()["narrator"]` or `NARRATOR_SYSTEM_PROMPT`. Change to `resolve_agent(session, "narrator", variant_slug=selected_variant)`, and when a variant resolves, use its rendered `prompt_template` as the system message. The narrator has no character card, so a variant **replaces** the base prompt — which is exactly how the seeded narrator variants are written ("You are the scene narrator during a moment of action…").
- **Custom agent (`:1197`)** — `resolve_agent(session, chosen_agent_slug)` at `:1202` must become `resolve_agent(session, chosen_agent_slug, variant_slug=selected_variant)`. The render at `:1207` is already correct.
- **Character (`:1243`)** — this branch never resolves an `AgentProfile` at all. It must.

### 1.2 The character variant is an *overlay*, and it needs a real merge point

The seeded character variants are personality overlays, not replacements:

> "You are roleplaying as {{char}}. The moment is tense: let emotion leak into word choice…"

so the character card must survive. The card is assembled by `build_context` and lands as `all_msgs[0]` (a `system` message) at `backend_v2/services/context_builder.py:1595-1598`:

```python
if system_prompt:
    all_msgs = [{"role": "system", "content": system_prompt}] + example_messages + msg_list
```

`workflow["character_system_prompt"]` is a **redundant duplicate** of that message — which is why the chain path's variant was silently lost: it was put in the duplicate, not the message.

**Do not** do string surgery on `context[0]["content"]`. Add a proper section instead:

- `backend_v2/services/context_builder.py` — `build_system_prompt_sections()` gains an `agent_variant_prompt: str | None` parameter, emitted as its own section immediately **after** the character block (the ordering is documented at `:615-623`: char card → char append → chat append → the rest).
- `chat_context_kwargs()` (`:1782`) must let a caller override `agent_variant_prompt`. Note the existing trap: `kwargs` is built from the entity and then only *specific* overrides are re-applied (`:1887-1899`), so an unlisted override is **silently dropped** — the same bug the comment at `:1878-1885` describes for `story_scenario`. The new override must be re-applied explicitly.
- `build_context()` (`backend_v2/services/context_builder.py:2037`) passes it through.

The variant is then rendered through `render_agent_template` (`backend_v2/services/chat_utils.py:328`) so `{{char}}` / `{{user}}` / `{{location}}` / `{{time}}` resolve. `{{char}}` is used by three of the six seeded variants, so this is load-bearing, not cosmetic.

### 1.3 The chain path

- `backend_v2/services/pipeline_stages.py:447-449` — `primary_slug = char_obj.slug` is a **character-card** slug, guarded by `hasattr(char_obj, "slug")`. `Character` has no `slug` column, so SQLModel drops the attribute and the guard always fell through to "character" — the agent slug. The chain was therefore already asking the right question. Replace it with the explicit constant `"character"` and a comment, so a Character that grows a `slug` field cannot silently change which agent's variants are offered. *(This was misdiagnosed as a live bug in the first draft of this plan; the test below is what caught it.)*
- `backend_v2/services/pipeline_stages.py:542-559` — the character branch passes the variant template as `system_prompt=`, which lands in the dead `workflow["character_system_prompt"]`. It must instead go through the same `agent_variant_prompt` overlay path as 1.2. **This is the real chain bug.**
- `backend_v2/services/pipeline_stages.py:480-492` — the narrator branch is already correct (`messages[0] = narrator_prompt`), but it uses `resolved_agent.prompt_template` **raw**, without `render_agent_template`. The seeded narrator templates happen to contain no macros, so it works today; a user-authored one containing `{{char}}` would emit the literal braces. Render it.

### 1.4 The dead key

`workflow["character_system_prompt"]` is written at `backend_v2/services/llm_workflow.py:92-93` and read by **nothing** — the LLM engines only read `workflow["messages"]` (`backend_v2/services/engines/llm_engine.py:450, 991, 1319`).

**Remove it.** All sixteen call sites pass a system prompt that is already the first message of `messages`, because `context_builder.build_chat_context_with_sections` puts the character card there (`:1595-1598`). The key is a duplicate of something already being sent, and its presence is what made the chain-path bug invisible.

The parameter is removed rather than left as a no-op, so the next person cannot make the same mistake.

### 1.5 A variant with no hint is invisible to Laya

`backend_v2/services/laya_questions.py:52-55` — a variant is only offered to Laya if it has a `selection_hint` or a `description`. A user-created variant with neither can never be selected, and nothing says so: it appears in the Studio, it appears in the API, and Laya is never offered it.

Make the Studio say so — a variant with no hint gets a visible "not selectable by Laya" marker, and the variant editor explains that a hint is what makes it a choice.

### 1.6 Tests

New file `backend_v2/tests/test_variant_routing.py`:

- Laya's `selected_variant` reaches the character agent's system message on a **normal user message** — the headline regression test. Fails today.
- Laya's `selected_variant` reaches the **narrator**'s system message.
- A custom agent's `selected_variant` reaches its prompt.
- The **chained** turn asks the `character_variant` question (assert the question is present in the triage question set) and the answer reaches the prompt.
- `{{char}}` in a variant template is rendered, not emitted literally.
- The character card is still present in the system message when a variant overlay is applied — the overlay must not replace it.
- The variant is recorded in the job metadata (`agent_variant_slug`) and in the `DirectorTrace`.

---

## 3. Phase 2 — Per-agent, per-model variants

*Today the only axis is per-agent, chosen by scene content. There is no per-model dimension: `llm_router` varies which model runs and its sampler, never what is asked, and the Director's question list is byte-identical for every tier.*

### 2.1 Schema

`backend_v2/core/entities.py` — `AgentPromptVariant` gains:

```python
# Which model this variant is FOR. NULL means "any model".
model_scope: str | None = Field(default=None, index=True)
```

The value is a model id **or a role** (`rp`, `util`, `decisions`). A role scope means "any model currently bound to that role", which is what most people want — "a prompt for the utility model" rather than for one GGUF file.

Migration **107** in `backend_v2/infrastructure/migrations/steps.py`:
`_migration_107_variant_model_scope(conn)` — `ALTER TABLE agent_prompt_variants ADD COLUMN model_scope TEXT` + index, following the pattern of migration 104 (`:5278-5337`).

### 2.2 Selection

`backend_v2/services/laya_questions.py:31-62` `get_agent_variant_options` gains a `model_scope` filter: a variant is offered when `model_scope IS NULL` **or** it matches the model that will serve the turn (by id or by role).

The model that will serve the turn is already known at triage time — `model_for_kind("chat_reply", chat.llm_model, session)` resolves it. It must be threaded into `evaluate_pre_generation_triage` → `resolve_stage_questions`.

**Scoped variants are offered as their own question.** A model-scoped variant is not a scene-fit choice, it is a compatibility choice, so mixing them into one option list makes the question ambiguous. Instead:

- `get_agent_variant_options` returns two lists: `scene_variants` (unscoped) and `model_variants` (scoped to this model).
- `model_variants` are **not** asked about — they are applied automatically when they exist, because there is only one correct answer for a given model.
- If a model has several scoped variants, they are asked as a separate `{slug}_model_variant` question, so the choice is still Laya's.

That keeps the invariant that **Laya routes and never decides content** — a scoped variant is a compatibility fact, not a creative choice.

### 2.3 Observability

`DirectorTrace` (`backend_v2/core/entities.py`) gains `selected_variant_scope` so the trace records *which* variant was used and *for which model*. The LLM Studio's Decision Traces tab then shows it.

### 2.4 UI

`frontend_v2/src/pages/LLMStudio.jsx` — the variant editor (`AgentVariantsSection`, `:2652+`) gains a "Model scope" field: blank = any model, or pick a role/model id. The list shows the scope as a badge.

### 2.5 Tests

- A model-scoped variant is not offered to Laya for a different model.
- A model-scoped variant IS applied automatically for its model, without a question.
- A role-scoped variant applies to whichever model is bound to that role.
- The trace records the scope.

---

## 4. Phase 3 — Per-gate Updater prompts

*You described: "if laya detects the mood is changing, then the system prompt instructs the updater to only update the mood fields." Today only the **schema** is gate-specific, not the prompt.*

### 4.1 What already exists (and is good)

The field restriction is enforced **structurally**, twice:
- `backend_v2/services/decision_schema.py:134-159` `GATE_FIELD_MAP` — the canonical gate → field map.
- The unfired gate's field is **absent from the JSON schema** the Updater is shown (`backend_v2/services/updater_service.py:407-481`).
- Anything smuggled in is hard-dropped on the way back (`:661-672`).

That is stronger than a prompt instruction, and it stays.

### 4.2 What to add

A **per-gate prompt** for the Updater, so the prompt names the situation:

- `AgentPromptVariant` gains an optional `gate_scope: str | None` (nullable, like `model_scope`), so a gate prompt is just a variant scoped to a gate.
- `backend_v2/services/updater_service.py` `_resolve_updater_agent_prompt()` (added in the previous pass) resolves, in order: the variant scoped to the **fired gate** → the variant scoped to the model → the agent's active variant → the hardcoded fallback.
- When several gates fire, the prompt names all of them ("the mood shifted and the clock advanced") — the field sets are unioned by the existing schema builder, so the prompt and the schema agree.

This is a natural extension of D2's `model_scope`: one nullable scope column per axis, and the resolution is a precedence chain. **Implement `gate_scope` and `model_scope` together**, with one shared resolution helper, rather than as two unrelated mechanisms.

### 4.3 Tests

- One gate fired → the Updater's prompt names that gate, and the schema contains only that gate's fields.
- Two gates fired → the prompt names both, the schema is the union.
- A gate-scoped variant beats an unscoped one.

---

## 5. Phase 4 — The LLM Studio shows the runtime

*There are two code paths for the question list. The pipeline uses one; the Studio shows the other.*

### 4.1 One code path

`backend_v2/services/laya_questions.py:180-269` `list_all_pipeline_questions` is a **separate implementation** from `resolve_stage_questions` (`:81-177`). It calls `_default_triage_questions()` with no `available_agents` and hardcodes placeholder variant questions with a single `{"default": …}` option.

Make the Studio read the runtime:
- `list_all_pipeline_questions` calls `resolve_stage_questions` for each stage, with the real agent list and the real variant options.
- The Studio then shows the **actual** option sets, including the real variant slugs — which is the thing you most want to see, because those slugs are what Laya can return.

### 4.2 The playground honours overrides

`POST /api/v2/llm/decisions/evaluate` (`backend_v2/api/routes/world_vault/llm_config.py:146-195`) calls `svc.evaluate_scene(...)` → `backend_v2/services/decision_service.py:823` → `build_director_questions(...)` — the hardcoded 13-question set. It bypasses `resolve_stage_questions` entirely, so **overrides you make in the Studio do not affect what the playground runs.**

Route the playground through `resolve_stage_questions` too.

### 4.3 Score-question rubrics become overridable

`backend_v2/services/laya_questions.py:156-160` merges an override's `options` into the question, but the Laya runner reads `q.get("rubric")` for score questions (`backend_v2/services/laya_runner.py:113`). An override therefore cannot change a score question's rubric. Unify: one key for score-question prose, used by both the override and the runner.

### 4.4 The system-prompt collection becomes a collection

`frontend_v2/src/pages/LLMStudio.jsx:1675-1874` — "System Prompt Blocks & Templates" is a hardcoded 27-entry **frontend constant** (`SYSTEM_PROMPT_METADATA` at `:156-382`, `SYSTEM_PROMPT_DEFAULTS` at `:126-154`). You can edit, reset and search them. You **cannot add one**.

Make it a real collection:
- The backend's `config.json` `system_prompts` block becomes a list, not a fixed map, with the 27 as defaults. `config.get_system_prompt_blocks()` (`backend_v2/config.py`) keeps returning a dict for compatibility, plus a new accessor for the full list.
- The Studio gets "Add prompt" and "Remove prompt".
- The backend's config schema (`backend_v2/config.py`) must accept the new shape; a config migration is needed if the shape changes incompatibly.

### 4.5 A cross-agent prompt library

Today a variant is creatable only inside its owning agent's modal. Add a **Prompt Library** view: browse every variant across every agent, filter by agent / tags / model scope / gate scope, and edit in place. This is the "a way too many system prompts" surface you described, and it is the one thing the Studio cannot currently do.

---

## 6. Phase 5 — Per-scene ComfyUI graphs

### 5.1 The design decision, and why

You asked for the Illustrator to "try to make a comfyui based workflow to generate the images". The literal reading — the LLM emits a raw ComfyUI graph — is **not safe to build**, and the reasons are concrete:

- **There is no node allow-list anywhere.** A repo-wide search finds no `class_type` validation. A raw graph can contain any node the provider has installed, including custom nodes that read files, hit the network, or spawn processes. The only server-side gate is ComfyUI's own validation, which happens **at dispatch, after the job is billed**.
- **There is no cost guard.** `core/upload_validation.py`'s `MAX_IMAGE_DIMENSION` applies to *uploaded image bytes*, not to `EmptyLatentImage.width/height`. A graph with `width: 16384, height: 16384`, `steps: 10000`, `batch_size: 64` and 500 samplers is currently accepted by `POST /api/generate`. An LLM in the loop would inherit and amplify that.
- **The gallery depends on the builder's metadata.** `build_image_job_workflow` populates `prompt`, `seed`, `steps`, `checkpoint`, `width`, `height` — which is what the assets table and `frontend_v2/src/utils/reuseParameters.js:373-532` (the API-format → generator-state reverse mapper) read. A raw LLM graph bypasses that and breaks "reuse parameters".

**So the LLM emits a constrained *scene graph spec* — the meaningful axes — and the backend renders the final graph with the existing `WorkflowBuilder`.** That is still node-level control over everything that actually matters (sampler, scheduler, steps, cfg, resolution, LoRA, hires fix, ControlNet, IPAdapter, detailer, seed), while the graph stays correct, bounded and gallery-compatible.

### 5.2 The spec

New pydantic model in `backend_v2/core/workflow_builder.py` (next to `GeneratorOptions` at `:118-182`):

```python
class SceneGraphSpec(BaseModel):
    prompt: str
    negative_prompt: str = ""
    composition: CompositionSpec          # width, height, batch_size
    sampler: SamplerSpec                  # name, scheduler, steps, cfg, denoise, seed
    lora: Optional[LoraSpec]              # name, strength_model, strength_clip
    hires_fix: Optional[HiresFixSpec]     # enabled, upscale_method, scale_by, steps, cfg
    controlnet: Optional[ControlNetSpec]  # name, strength
    ipadapter: Optional[IPAdapterSpec]    # name, weight
    adetailer: Optional[DetailerSpec]     # model
```

### 5.3 Rendering

`backend_v2/core/workflow_builder.py` — `WorkflowBuilder.build_scene(spec)` maps the spec onto `GeneratorOptions` and reuses `build_core` (`:185-612`). **No new graph emitter** — the node graph stays exactly the 7-node t2i (plus optional hires / adetailer / ControlNet / IPAdapter) shape the system already produces, with the existing `class_type` and input names.

`backend_v2/services/image_submission.py` — `submit_image_job` gains a `spec: SceneGraphSpec | None` parameter. When present, the graph is built from the spec instead of the flat prompt arguments. The existing signature and behaviour are unchanged when it is absent.

### 5.4 Validation and limits

New leaf module `backend_v2/core/workflow_limits.py` (mirroring `core/pipeline_limits.py`):

```python
MAX_SCENE_STEPS = 60
MAX_SCENE_HIRES_STEPS = 30
MAX_SCENE_WIDTH = 2048
MAX_SCENE_HEIGHT = 2048
MAX_SCENE_PIXELS = 4_000_000
MAX_SCENE_BATCH = 2
MAX_SCENE_LORA_STRENGTH = 1.5
```

A validator in `backend_v2/services/job_submission_service.py` `validate_workflow` (`:27-46`) — the single gate every job-creating route already passes through — clamps or rejects out-of-range values. Because the spec is rendered by the backend, a bad value is caught **before** dispatch, which is the whole point.

### 5.5 Model names

The LLM must not invent model names. Two mechanisms, both needed:

1. **Tell it what exists.** `ModelAvailabilityService.get_available_models(directory)` (`backend_v2/services/model_availability_service.py:283-340`) returns the installed checkpoints / loras / vae / controlnet / unet / clip for the enabled providers. The Illustrator's context gets the relevant lists.
2. **Repair what comes back.** Validate each name against those lists. A name that is not installed is dropped, and the fact is recorded — the same way `get_available_checkpoint` substitutes for checkpoints (`:342-366`) and `get_available_lora` returns `None` rather than substituting (`:368-377`).

### 5.6 A separate completion path

The illustrator's completion is currently routed by `backend_v2/services/job_processing.py:740-771` (`metadata.source == "scene_prompt"`) into `backend_v2/services/world_integration_service.py:213-260` `_handle_scene_prompt`, which treats the output as prompt text.

A graph needs its own event type so the text path is not disturbed:
- `metadata.source = "scene_graph"` → a new branch in `job_processing.py` → a new handler in `_EVENT_DISPATCH` (`backend_v2/services/world_integration_service.py:1492-1508`).
- The handler parses the JSON spec, validates it, resolves model names, and calls `submit_image_job(..., spec=spec)`.
- A parse or validation failure falls back to the **text** path: the same LLM output treated as a prompt. The illustration still happens; it just is not node-customised. This is the important resilience property.

### 5.7 The prompt the Illustrator gets

`backend_v2/services/illustrator_service.py:24-75` `_illustration_context` currently ends with "Write the image prompt now. Respond with the prompt text only (comma-separated Danbooru tags)." The graph variant asks for the spec JSON instead, and must include the available model names (§5.5).

Note that `_illustration_context` already carries `character_expression`, `character_outfit`, `weather`, location and time from the state snapshot (`:44-52`) — so the Updater's expression decision does reach the Illustrator. That division of labour (Laya decides *whether*, the Updater decides *what the expression is*, the Illustrator decides *how it looks*) is already correct and is preserved.

### 5.8 Cost

There is no per-image cost accounting anywhere in the system — no credits, no quota, no ledger. The only controls are the per-exchange image *count* (2) and the LLM hop cap.

For a graph-authored image, the meaningful cost axis is steps × pixels. Add a per-chat **image cost budget** in the same shape as the existing `TOOL_BUDGETS` table (`backend_v2/services/orchestrator_service.py:53-59`): a spec's cost is derived from its steps and resolution, the chat's budget is decremented on submission, and a spec that would exceed it is refused (with the refusal recorded). The budget itself is a `core/pipeline_limits.py` constant plus a per-chat override column, matching `MAX_AGENTIC_IMAGES`.

### 5.9 Tests

- A valid spec renders the expected node graph (node count, class types, input values).
- An out-of-range spec is rejected **before** dispatch — assert no job was created.
- An uninstalled model name is dropped and recorded, not passed through.
- A malformed LLM response falls back to the text path and still produces an image.
- The image lands in the transcript with the right `image_context`, and its `workflow` metadata still carries `prompt` / `seed` / `steps` / `checkpoint` so the gallery and "reuse parameters" keep working.

---

## 7. Phase 6 — Semantics

- **6.1** Continuation threshold: `MAX_CONTINUATIONS = 4` → the budget becomes **4 total attempts** (1 original + 3 continuations). `backend_v2/core/pipeline_limits.py:30` → rename to `MAX_CONTINUATION_ATTEMPTS = 4` and change the comparison in `backend_v2/services/pipeline_stages.py:167` from `continuation_count < MAX_CONTINUATIONS` to `continuation_count + 1 < MAX_CONTINUATION_ATTEMPTS`. Update `backend_v2/services/chat_pipeline.py`'s manifest limit name to match.
- **6.2** The stale "13 questions" label. The real counts are triage 6 base + injected variant questions, audit 20, chaining 2, unified 28. It appears in `backend_v2/services/chat_pipeline.py` and in the Studio's "System 1 Director Playground (13 Questions)" tab label (`frontend_v2/src/pages/LLMStudio.jsx:869`). Both must stop asserting a number that is not derived from the code — ideally the counts are computed from the question builders.
- **6.3** `frontend_v2/src/components/chat/DirectorReasoningHUD.jsx:24-41` — the hardcoded 16-gate list is already superseded by `GET /llm/director/gates` (done in the previous pass); this phase only removes the last hand-copied duplicate if one remains.

---

## 8. Phase 7 — Docs

- `docs/STATUS.md` — a new section for this pass: the variant axis, the per-scene graph spec, the Studio's single question path, and the corrected counts.
- `docs/api.md` — the new endpoints (`/llm/agents/{id}/variants` gains the scope fields; the graph spec is not a new endpoint, it rides the existing image job).
- `docs/provider-architecture.md` — the scene-graph spec, the limits, and the deliberate refusal to accept a raw LLM-authored graph, with the reason.
- `.kilo/plans/` — this file, committed alongside the change.

---

## 8a. Implementation notes — what changed from the plan

Recorded after the work, because two of the plan's diagnoses were wrong and
one of its designs turned out to be unsafe as written.

**Gap 3 was a misdiagnosis.** The chain's triage was reported as asking
about "the wrong character's variants". It was not. The chain passed
`char_obj.slug` — the character CARD's slug — guarded by
`hasattr(char_obj, "slug")`, and `Character` has no `slug` column, so
SQLModel dropped the attribute and the guard always fell through to
"character", which is the agent slug. The chain was asking the right
question. The code now says `primary_slug = "character"` explicitly, so a
Character that grows a `slug` field cannot change it silently, and the test
pins the question that is actually asked.

**The per-model axis was redesigned during the work.** The plan described a
model-scoped variant as "applied automatically when there is exactly one, and
asked as a separate question when there are several". That is more machinery
than the idea needs, and it splits Laya's choice into two questions about
different things. What shipped is a **filter**: a model-scoped variant is
only OFFERED to Laya when the agent it belongs to will answer with that
model, and the scopes are per agent because each agent can be bound to a
different model. Laya still makes one choice, from a list that is already
correct for the model about to run. `gate_scope` is the same shape.

**`model_scope` and `gate_scope` are one mechanism, not two.** The plan had
them as separate features; they are the same nullable scope column with a
different axis, and they share one resolution helper
(`services/agent_variants.py`). An unscoped, INACTIVE variant is never
auto-applied — the built-in sub-variants are seeded that way on purpose,
as examples Laya picks by name, and auto-applying the first one
alphabetically would have replaced the agent's default persona with an
example.

**The prompt library is a new config section, not a change to
`system_prompts`.** The plan said the `system_prompts` block "becomes a
list". That would have broken the fixed-key lookup the whole codebase uses,
and it would have needed a config migration for a shape change. Instead
`system_prompt_library` is a new list section, and its entries are merged
into `get_system_prompt_blocks()` so a prompt of your own is usable by key
everywhere a built-in one is.

**`update_config` could not write a list-valued section at all.** Found
while testing the library: `_split_unset` filtered the updates with `if
isinstance(body, dict)`, so a list section never reached the validator or
the merge, and `update_config` returned success having written nothing.

**The event-loop analyser was wrong, not the eleven routes.** The plan
assumed the onboarding routes were genuinely blocking. They are not: the
analyser collected `ast.Await` but not `ast.AsyncFor`, so it could not see
that `async for event in engine.inference(...)` really does suspend on
`await client.post(...)`. The analyser was fixed instead. It still flags all
23 routes registered as known debt.

**The "13 Questions" label was one of three question lists.** The Director
Playground ran `build_director_questions` — a third list, separate from
the stage builders and from the override system. It now runs the union of
the three stages' RESOLVED questions, so the Studio's overrides are in
force. The label is gone; the gate count was checked and is right (16 in the
registry; the other two `UPDATER_GATE_KEYS` are legacy aliases).

**The continuation budget was five attempts, not four.** `MAX_CONTINUATIONS
= 4` with `continuation_count < 4` is the original plus four continuations.
It is now `MAX_CONTINUATION_ATTEMPTS = 4` with `continuation_count + 1 < 4`,
and the manifest publishes `max_continuation_attempts`.

**The scene-graph path is a spec, and that was a deliberate narrowing.** The
plan's own argument for it held up on inspection — there is no node
allow-list, the workflow dimensions and step counts are unbounded, and the
gallery reads the builder's metadata — so the shipped design is the
closed spec the plan described, rendered by the existing builder.

## 9. Risks

| Risk | Mitigation |
|---|---|
| **Phase 1 changes what every chat turn sends.** The character card and the variant overlay must both survive, in the right order. | 1.5's tests assert the card is still present. The overlay goes through a real section (`1.2`), not string surgery. |
| **Phase 5 introduces LLM-authored generation parameters.** | The spec is a closed vocabulary rendered by the existing builder; the validator runs before dispatch (§5.4); the cost budget caps steps × pixels (§5.8). A raw-graph escape hatch is deliberately **not** offered. |
| **Phase 2/3 add two scope columns to a table with a migration.** | Nullable columns, additive migrations (107, 108), no backfill. `model_scope` and `gate_scope` share one resolution helper. |
| **Phase 4 changes the question list the Studio shows**, which changes what the playground runs. | The Studio and the pipeline converge on ONE function; the playground joins them. Anything that changes the runtime question set is visible in the Studio, which is the point. |
| **Phase 6 changes the continuation budget**, so a truncated reply now costs one fewer LLM call. | A one-line change plus the manifest limit rename; the continuation path already has tests. |
| The per-scene graph changes what an illustration looks like, so image output differs. | The text path stays as the default and the fallback; the graph path is opt-in per chat (`Chat.scene_graph_enabled`) until it is proven. |

---

## 10. Validation

```bash
cd backend_v2
.venv/bin/python -m pytest tests/test_variant_routing.py -q
.venv/bin/python -m pytest tests/test_chat_pipeline_execution.py tests/test_director_and_updater.py \
  tests/test_agent_variants.py tests/test_agent_profiles.py tests/test_scene_graph_spec.py -q
.venv/bin/python -m pytest -q
.venv/bin/ruff check .

cd ../frontend_v2
npx vitest run
npm run lint
npm run build
```

Manual acceptance:

1. A normal user message with a `character-playful` variant selected by Laya produces a reply whose system prompt contains the playful overlay **and** the character card.
2. The same chat, with the `character-tense` variant selected, produces a different tone.
3. A model-scoped variant applies for its model and is not offered for another.
4. The Updater's prompt names the gate that fired.
5. The LLM Studio's Laya Questions tab shows the **real** variant slugs, and the playground runs the same question set.
6. The Illustrator produces a spec; the resulting image job's workflow is the rendered graph; an out-of-range spec is refused before any job is created; a malformed response still yields an image via the text path.
7. A truncated reply costs 4 generations, not 5.

---

## 11. Out of scope

- Accepting a raw LLM-authored ComfyUI graph (see §5.1 — refused deliberately, with reasons).
- Per-image credit accounting (Phase 5.8 adds a *budget*, not a ledger).
- The `Character`-card `mes_example` handling, the World Architect's LLM analysis, and the onboarding 20-endpoint surface.
- A `laya` AgentProfile. Laya is the Director, not an actor; it has no prompt to vary.
- Changing the gate set (18 keys), the audit's 20 questions, or the triage's 6 base questions.
