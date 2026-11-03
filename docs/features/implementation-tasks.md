# Implementation Tasks — All 10 Features

Branch: `feature-all-improvements-2026-11-03` (created, not yet pushed)

## Phase 1 — P1 Features

### Feature 1: Voice cloning + per-character voices (Roleplay Chat)
Status: ~90% built; needs frontend wiring

Backend (done):
- Voice models with `character_id` FK (`core/entities.py`)
- TTS workflow builder (`tts_workflow_builder.py` — 3 graphs)
- `/voices/*` API routes (`world_vault/voices.py`)
- `/chats/{chat_id}/messages/{message_id}/narrate` TTS route (`world_vault/chats.py`)
- `submit_tts_job` in `job_submission_service.py`

Frontend (done):
- `Voices.jsx` page with design/clone/preview
- `useVoices.js` hooks
- `MessageItem.jsx` with `onGenerateTTS` prop + volume button
- `ChatWorkspaceContext` with `handleGenerateTTS`

Missing (to implement):
- Voice assignment in CharacterDetailsModal / Characters page (link voice_model_id to character)
- TTS audio playback UI in MessageItem (play/pause audio from narrate job)
- Connect `handleGenerateTTS` → narrate endpoint → audio_url on message

### Feature 2: Comic strip assembly UI (Story Sandbox)
Status: Backend done, frontend missing

Backend (done):
- `comic_exporter.py` — full pipeline (panels → images → CBZ + HTML reader)
- Job submission + WS completion events

Missing (to implement):
- Frontend comic assembly page (select chapter, panel count/layout, character→visual tag mapping, seed per panel)
- Job polling + download link for CBZ + HTML reader

### Feature 3: Story branching UI / alternate timelines (Story Sandbox)
Status: Backend done, frontend missing

Backend (done):
- `branches.py` API route + `useBranches.js` hook
- Branch CRUD at data layer

Missing (to implement):
- Frontend branch-tree view on story chapters
- Fork from any message/chapter
- Switch between timelines, side-by-side comparison

## Phase 2 — P2 Features

### Feature 4: World templates / starter packs (World Building)
Status: Missing entirely

Missing (to implement):
- Backend: template JSON definitions (high fantasy, cyberpunk, gothic horror, space opera)
- Frontend: template picker in onboarding flow

### Feature 5: Cross-story character portability UI (World Building)
Status: Backend done, frontend missing

Backend (done):
- `character_portability.py` — bundle export/import

Missing (to implement):
- Frontend: export character bundle (download), import bundle (upload)

### Feature 6: Interactive world map (World Building)
Status: Missing entirely

Missing (to implement):
- Backend: location coordinates (x/y or lat/lng) — entity migration
- Frontend: canvas/SVG map with location pins, character links, chapter navigation

## Phase 3 — P3 Features

### Feature 7: Character relationship timeline (Roleplay Chat)
Status: Missing entirely

Missing (to implement):
- Backend: query messages/memories tagged with character pairs + timestamps
- Frontend: timeline view of relationship milestones

### Feature 8: Image-to-story reverse pipeline (Image Generation)
Status: Missing entirely

Missing (to implement):
- Backend: image-to-text endpoint (VLM/captioning) → chat_pipeline
- Frontend: upload image → story prompt → chapter generation

### Feature 9: Batch story chapter generation (Image/Story)
Status: Partially built (BatchGenerate.jsx exists)

Missing (to implement):
- Frontend: batch chapter variants from one prompt, side-by-side preview, "continue with this one"

### Feature 10: Provider cost & usage dashboard (Provider System)
Status: Partially built (Providers page UX done, provider_telemetry_service.py exists)

Missing (to implement):
- Backend: cost aggregation per provider/model over time windows
- Frontend: dashboard with cost charts, rate-limit warnings, budget alerts
