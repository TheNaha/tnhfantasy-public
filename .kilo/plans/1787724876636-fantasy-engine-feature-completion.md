# Fantasy Engine Feature-Completion Plan

Status: ACTIVE (supersedes pillar-hardening notes for this effort)
Created: 2026-08-26
Baseline: `9158ac9` pushed to origin; backend 1553 passed / 2 skipped, frontend 563 passed, lint clean.
Audit basis: full-stack audit of 2026-08-26 (feature gaps vs SillyTavern / NovelAI / AI Dungeon / Civitai + cross-pillar integration map).

## User decisions (locked)

1. Implement ALL phases, in order.
2. Sampler controls: FULL set (temperature, top_p, max output tokens, frequency/presence penalties) per chat AND story, plus global defaults in Settings; mapped across all four LLM engines (openai_compat, anthropic, google, modal-vLLM).
3. Story agentic tools: IMPLEMENT (wire tool-calling into story jobs; keep MAX_AGENTIC_DEPTH semantics).
4. Group chats: add real speaker attribution (`Message.character_id` migration).

## Phase 1 — Broken UX quick wins (this commit series)

| Item | Fix | Files |
|---|---|---|
| Swipe hover-bar dead buttons ('prev'/'next' vs backend `left\|right\|select`) | send valid directions | MessageItem.jsx:278,288 |
| Branch timeline label always raw ID prefix | read `branch.messages[0].branch_name` | ChatTimeline.jsx:57 |
| Published-reader export dead ternary + short timeout | remove ternary, 180s export timeout | StoryReader.jsx:38-68 |
| Story chapter TTS generated but unplayable | inline `<audio>` player on `system_tts` beats | StoryBeatsPanel.jsx |
| Chat TTS ships disabled | `ttsEnabled` default true | settingsStore.js:54 |
| Locations PATCH `"name": null` → 500 | strict `name: str` in update schema (422 instead) | locations.py LocationUpdate |
| "Unified asset library" chip claims a nonexistent destination | rename to delivered reality ("Unified image gallery") | FantasyHub.jsx |

Verified NON-issue: campaign delete needs no reference scrubbing — no entity stores `campaign_id`; campaigns are pure aggregators (reference_cleanup has no campaign branch, correctly).

## Phase 2 — Full sampler controls

Backend:
- Add sampler fields to Chat + Story entities + migration step (`temperature`, `top_p`, `max_output_tokens`, `frequency_penalty`, `presence_penalty` — all nullable = inherit global).
- Thread through build_llm_workflow → job metadata → provider_client payload (only include overrides; fall back to global ai.temperature).
- Map to each engine in provider_containers/llm_worker: openai_compat (native), anthropic (top_k absent, temperature/top_p/penal→stop_sequences n/a: map penalties best-effort or omit where unsupported), google (generationConfig), vLLM (OpenAI-compatible params).
- Settings page: global defaults editor (extend existing ai block).

Frontend:
- ChatContextPanel + StoryContextPanel: collapsible "Sampling" section with sliders + "inherit global" resets.
- Live token meter near composer using existing tiktoken estimate endpoint (context window usage bar).

Acceptance: overriding temperature on a chat visibly changes request payload (provider log); resetting inherits global; all engines accept payload without error; suites green.

## Phase 3 — Story core loop

- Generic story-action support: extend continue endpoint usage — UI sends directive `prompt` (already supported); add rewrite-selection / expand / summarize-beats / retry-last endpoints modeled on continue (shared context builder).
- Beat lifecycle: PATCH+DELETE beat endpoints; expose narrator/system roles in beat composer; edit-in-place in StoryBeatsPanel.
- Word-count goal + progress display (story field + header progress ring/bar).
- POV setting (first/second/third) injected into context builder style directives.
- Lightweight revision snapshots: chapter snapshot rows on destructive ops (rewrite/replace) + restore UI.

## Phase 3b — Story agentic tools

- Attach AGENTIC_TOOLS-filtered set (generate_image, narrate_scene, recall/store_memory, update_world_state) to story workflows when enabled; relax job_processing gate from `job_type=="chat_reply"` to include story continuation jobs; persist tool outputs into beats/images; honor story.max_agentic_depth slider (currently dead).

## Phase 4 — Group chats & attribution

- Migration: `Message.character_id` nullable FK-ish column; backfill primary character for existing CHAR rows.
- Set attribution at creation sites (reply path, narrator tool, agentic replies); render speaker avatar/name from it in MessageTimeline/MessageItem.
- Optional auto turn-taking: round-robin across additional_character_ids when no explicit reply-as target.

## Phase 5 — Interop + integration hygiene

- SillyTavern chat JSONL import/export (frontend transform + internal JSON export wiring for orphaned GET /chats/{id}/export).
- Deduplicate orchestrator `_tool_generate_image` onto services/image_submission.submit_image_job.
- Route illustrate_chapter lorebook loading through rag_pipeline top-K instead of loading ALL entries (stories.py:995-1022 self-flagged).
- RAG degradation visibility: banner/indicator when embeddings are missing and fallback dumps first-N entries.
- Unbounded endpoints: pagination caps for export_chat/list_branches/add_message-heavy lists; timestamp ordering tiebreakers (id secondary sort).
- except Exception → ComfyError laundering fixes (×4 sites).

## Phase 6 — Performance / QoL

- Kill N+1 useCharacterCollection-per-card (Characters.jsx:650, AvatarGallery ×2) → batch hook.
- Split ChatWorkspaceContext (~120 values) into focused stores/selectors.
- RelationshipGraph O(n²) layout off main thread (worker or incremental layout).
- Grid virtualization for gallery/characters; BatchGenerate ws events instead of 4 s polling; civitai localStorage cache TTL.

## Known-good reference points

- Shared context builder is THE injection point: chat + story both call build_chat_context_async; keep new features there, not route-local.
- All LLM dispatch funnels through call_llm_provider NDJSON stream; sampler work must not fork this.
- Images converge on finalize_successful_job → asset_reconciler; never bypass reconciler.
- Migrations: append MigrationStep in infrastructure/migrations/steps.py.
- Tests: vi.mock factories must enumerate every new page hook; error envelope {error,code,field}.
