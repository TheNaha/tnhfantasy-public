# Plan: Prompt Shortcut & Textual Inversion Embedding Support for Simple Generator

Goal: Let users type Civitai-style embedding shortcuts (e.g. `lazypos`) in the Simple Generator prompt and have them expand to full quality-tag strings, plus validate and load `embedding:NAME` textual inversion files from `models/embeddings/`.

## Current state (verified against code)

- Frontend `ModelSection.jsx` already renders embedding chips that insert `embedding:NAME` into prompt/negativePrompt.
- Frontend `useWorkflowBuilder.js:8-20` `extractEmbeddingsFromPrompt()` extracts `embedding:NAME` tokens into `metadata.embeddings` — but this metadata is never consumed by the backend.
- Backend `WorkflowBuilder.build_core()` (`core/workflow_builder.py:354`) creates `CLIPTextEncode` nodes with `options.prompt` / `options.negativePrompt` passed **as-is** — no expansion, no embedding handling.
- Backend `workflow_parser.py:45-47` explicitly skips embeddings ("typically loaded by name reference in prompts... skip them for now").
- `models/embeddings` is a recognized directory (`services/engines/base.py:311`) and maps to `TextualInversion` model type (`services/model_reconciliation.py:18`), but no `EmbeddingLoader` node exists in `direct_comfy_engine.py:NODE_TO_DIRECTORY` (lines 89-102).
- `config.json` has `generator.default_checkpoint` but no shortcut registry.
- No shortcut expansion exists anywhere in the codebase.

## Design decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Shortcut expansion happens in the backend** `WorkflowBuilder.build_core()`, applied to `options.prompt` and `options.negativePrompt` before `CLIPTextEncode` nodes are created. | Covers all generation paths (Simple, Advanced, Img2Img, Inpaint, API `/api/generate`) from a single choke point. Frontend stays thin. |
| D2 | **Shortcuts registry lives in `config.json` under `generator.prompt_shortcuts`** as a `name: expansion` dict, e.g. `{"lazypos": "masterpiece, newest, absurdres, ...", "lazyneg": "worst quality, low quality, ..."}`. | Follows existing `generator.default_checkpoint` pattern. No new DB table or migration needed. Operators can edit config without redeploying code. |
| D3 | **`embedding:NAME` tokens are validated against `models/embeddings/`** before job submission. If the file doesn't exist, fail fast with a clear error naming the missing embedding. | Prevents wasted GPU time on jobs that ComfyUI would silently fail on. Mirrors existing LoRA/model availability validation. |
| D4 | **ComfyUI auto-loads embeddings referenced by name in CLIPTextEncode** — no `EmbeddingLoader` workflow node needed for basic support. ComfyUI natively resolves `embedding:NAME` from `models/embeddings/`. | Standard ComfyUI behaviour. Adding EmbeddingLoader nodes is optional future work. |
| D5 | **Frontend adds shortcut chips** alongside embedding chips in `ModelSection.jsx`, inserting the shortcut token (or expanded text) into the prompt. | Mirrors the existing embedding chip UX pattern. Users discover shortcuts the same way they discover embeddings. |
| D6 | **Frontend `extractEmbeddingsFromPrompt` is extended to also extract shortcut tokens** into `metadata.shortcuts`, so the backend can validate/record them. | Keeps frontend↔backend metadata contract consistent. |

## Affected boundaries

### Backend

1. `config.json` — add `generator.prompt_shortcuts` dict (default empty `{}`).
2. `core/workflow_builder.py` — `build_core()`: before creating `CLIPTextEncode` nodes:
   - Expand shortcut tokens (word-boundary match, longest-first to avoid partial overlaps) in `options.prompt` and `options.negativePrompt` using `config.generator.prompt_shortcuts`.
   - Parse `embedding:NAME` tokens from both prompts; validate each `NAME` file exists in `models/embeddings/` (`.safetensors`, `.pt`, `.bin`, `.ckpt`).
   - Raise `ValidationError` naming any missing embedding file.
3. `core/workflow_parser.py` — add `"EmbeddingLoader": ("embedding_name", "embeddings")` to `MODEL_LOADER_NODES` so embedding files are captured by `extract_models_from_workflow()` for availability validation.
4. `services/engines/direct_comfy_engine.py` — add `"EmbeddingLoader": "embeddings"` to `NODE_TO_DIRECTORY` (line 89-102) so the engine routes embedding file loads through the correct model directory.
5. `services/job_submission_service.py` — no change needed; `validate_workflow` will pick up embedding files via `workflow_parser` once D3/D4 are in place.

### Frontend

6. `src/components/generator/ModelSection.jsx` — add a shortcuts chip row (same pattern as embedding chips, lines 163-206) that inserts the shortcut token into prompt/negativePrompt. Also display expanded preview on hover.
7. `src/hooks/useWorkflowBuilder.js` — extend `extractEmbeddingsFromPrompt()` to also extract shortcut tokens into `metadata.shortcuts`.
8. `src/store/generatorStore.js` — no change needed; shortcuts are just prompt text edits.

## Data flow

```
User types "lazypos, a catgirl" in Simple Generator prompt
  → Frontend sends {options: {prompt: "lazypos, a catgirl", ...}, metadata: {...}}
    → POST /api/generate
      → WorkflowBuilder.build(options)
        → build_core(): expand shortcuts → "masterpiece, newest, ..., a catgirl"
        → parse embedding:NAME tokens → validate models/embeddings/NAME.safetensors exists
        → create CLIPTextEncode nodes with expanded prompt
        → return ComfyUI workflow graph
      → create_and_enqueue_job(workflow, metadata)
        → validate_workflow() extracts EmbeddingLoader models → checks availability
        → enqueue job
        → ComfyUI executes, auto-loading embedding from models/embeddings/
```

## Failure modes & risks

- **Shortcut collision**: `lazypos` is a prefix of `lazypos_v2`. Expansion must match word boundaries and apply longest-first. Use regex `\b(lazypos_v2|lazypos)\b` sorted by length desc.
- **Missing embedding file**: `embedding:lazypos` typed but `models/embeddings/lazypos.safetensors` doesn't exist → `ValidationError` before job creation, clear message naming the missing file.
- **Embedding file present but wrong format**: ComfyUI will fail at runtime with a node error. Can't detect ahead of time without loading the file — acceptable, same as LoRA.
- **Shortcut appears in negative prompt too**: Expansion applies to both `prompt` and `negativePrompt` independently.
- **Backend config missing `prompt_shortcuts`**: Default to `{}` — no expansion, fully backward compatible.

## Rollout / migration path

1. Add `generator.prompt_shortcuts: {}` to `config.json` (default empty, no migration).
2. Add shortcut expansion + embedding validation to `core/workflow_builder.py`.
3. Add `EmbeddingLoader` to `core/workflow_parser.py` and `direct_comfy_engine.py`.
4. Add shortcut chips to frontend `ModelSection.jsx` and extend `extractEmbeddingsFromPrompt` in `useWorkflowBuilder.js`.
5. Seed `config.json` with lazypos/lazyneg (and other common Civitai lazy embedding names) as examples.
6. Run backend tests + frontend tests + ruff + eslint.
7. Manual verification: upload `lazypos.safetensors` to `models/embeddings/`, type `lazypos` in Simple Generator, generate, confirm expanded prompt reaches ComfyUI.

## Validation plan

- Backend: unit test `WorkflowBuilder.build_core()` expands `lazypos` → full string; test missing embedding file raises `ValidationError`; test `embedding:NAME` tokens pass through unchanged when file exists.
- Backend: `cd backend_v2 && ruff check .` and `cd backend_v2 && .venv/bin/python -m pytest`.
- Frontend: `cd frontend_v2 && npm test` and `npm run lint`.
- Manual: Simple Generator page shows shortcut chips; clicking one inserts token; generated job's prompt contains expanded text.

## Open questions (deferrable)

- Whether shortcuts should also be user-configurable via a settings UI (future enhancement; config.json is sufficient for v1).
- Whether `EmbeddingLoader` workflow nodes should be explicitly added to the graph (future; ComfyUI auto-resolves `embedding:NAME` in CLIPTextEncode text).
- Whether shortcuts should support nested expansion (shortcut A expands to text containing shortcut B) — v1 is single-pass only.

## Implementation note

This plan is implementation-ready but I cannot mutate files (plan mode). Switch to an implementation-capable agent and point it at `.kilo/plans/1792210000004-embedding-prompt-shortcuts-plan.md`.
