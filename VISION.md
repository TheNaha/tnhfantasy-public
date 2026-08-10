# Project Vision: The Unrestricted AI Fantasy Engine

## The Grand Vision
Originally conceived as **TNHComfy**, an unrestricted Image Generation Service wrapping ComfyUI via provider containers, this project is evolving into a **Comprehensive AI Fantasy Engine**. 

The ultimate goal is to create a centralized, private, and entirely unrestricted hub for multimodal storytelling, roleplay, and worldbuilding. By leveraging self-hosted or provider-based AI models (Image, Text, and eventually Audio/Video), the platform empowers the user to create highly immersive, persistent fantasies without the censorship or structural limitations of commercial services like TensorArt, CivitAI, or AI Dungeon.

---

## Core Pillars

### 1. Image Generation (The Foundation)
The current implementation of TNHComfy. A highly customized, user-friendly frontend that interfaces with remote serverless containers (Modal/Beam) running ComfyUI. 
*   **Purpose:** Unrestricted generation of high-quality images, managing checkpoints, LoRAs, and generation parameters with ease.

### 2. AI Roleplay Chatbot
A dedicated interface for interacting with individual AI personas, heavily inspired by SillyTavern and Perchance.
*   **Purpose:** Character-driven dialogue and roleplay.
*   **Integration:** Seamlessly connected to the Image Generation pillar. Users can request a "selfie" or a scene illustration mid-conversation, and the system will automatically inject the character's visual traits (and specific LoRAs) into the image generation prompt.

### 3. AI Storytelling & Sandbox
An interactive, narrative-focused module inspired by AI Dungeon and NovelAI. 
*   **Purpose:** Long-form worldbuilding, branching narratives, and unrestricted storytelling. 
*   **Integration:** Can function as an "Illustrated Novel." The system can quietly monitor the narrative flow and automatically generate background illustrations, character portraits, and scene depictions based on the unfolding story.

### 4. The World Vault (Lore & Character Management)
The glue that binds the text and image modalities together.
*   **Purpose:** A unified database storing Character Cards (V2 spec compatibility), Lorebooks, World Bibles, and persistent locations.
*   **Integration:** LLMs will dynamically retrieve lore for context during text generation. Simultaneously, image generation workflows will use the stored visual tags and base models associated with these characters/locations to maintain visual consistency.

---

## Technical Architecture Evolution: The Universal Adapter Pattern

To support this multimodal future and maximize flexibility, we are overhauling how the backend communicates with inference providers. We are moving to a **Universal Adapter Pattern**.

1.  **Unified Worker Containers (The Adapters):** 
    *   Instead of having separate, rigid codebases for a "Modal Worker" and a "Beam Worker", we will merge them into functional workers: **Image Worker**, **LLM Worker**, and **Audio Worker**.
    *   These worker containers act as localized proxies/adapters. The backend talks to them using one standardized API contract, completely unaware of where the actual inference is happening.
2.  **Engine Agnosticism (Bring Your Own Compute):**
    *   Workers are configured entirely via Environment Variables. 
    *   *Example 1 (Image):* You can set `ENGINE=modal` to use remote serverless GPUs, or `ENGINE=direct_url` with `COMFYUI_URL=http://localhost:8188` to point the worker at your own local/remote ComfyUI instance. The worker translates the commands automatically.
    *   *Example 2 (LLM):* You can set `ENGINE=openai_compat` and provide `API_URL=http://localhost:11434/v1` to seamlessly hook into a local Ollama instance, or point it to OpenRouter.
3.  **Unified Model Management:**
    *   Because the worker abstracts the execution engine, the backend's Model Management system can manage files regardless of where they live. For a Modal engine, it syncs to cloud storage. For a `direct_url` engine, the worker can download the models directly into your local ComfyUI `models/` directory.
4.  **Health Checks & Cost Mitigation:**
    *   To avoid expensive serverless billing from continuous polling, the backend will only health-check the local worker container itself. The worker assumes the remote URL/engine is alive until an actual job is dispatched.
    *   The UI will feature a manual "Test Connection" button for providers so users can validate their endpoints on demand.
  5. **Streaming Standardization (The Unified Protocol) — IMPLEMENTED:**
     *   Parsing responsibility is shifted to the Worker. All workers (image + LLM) translate their native stream into a single `provider_core.models.TaskEvent` NDJSON schema (`event` ∈ started/progress/delta/node/completed/failed/cancelled, plus `text`, `tool_calls`, `outputs`, `value`, `retryable`). The backend has ONE reader (`services/provider_client.stream_task_events`) with thin per-task reducers instead of two divergent dialects. All engines (image modal/beam/direct_url, LLM openai_compat/anthropic/google/modal-vLLM) now emit this protocol; legacy dialects are translated at the worker edge.
  6. **Codebase Merger & Standalone Deployments — IMPLEMENTED:**
     *   `modal_worker`/`beam_worker` were merged into `image_worker` + `llm_worker` + shared `provider_core`. Standalone deploy apps `modal_app.py`/`beam_app.py` live at the engine roots (`image_worker/engines/{modal,beam}/`); deploy commands are hardcoded in the engine clients (`modal deploy /app/.../modal_app.py`). The orphaned `runpod` engine was removed (no backend registration ever existed).
 7. **Context Management (Backend-Authoritative) — CORRECTED:**
     *   The backend (`services/context_builder.py`) owns context assembly. This is intentional and correct: semantic lorebook retrieval needs `pgvector` server-side, and shipping the whole lorebook to the frontend to build a prompt would be wasteful and lose retrieval quality. The frontend sends text + flags (narrate/agentic/etc.); the backend builds, prunes (token budget), and injects lore. The frontend remains stateful for UI sync (React Query + optimistic updates) but does NOT assemble the final payload.
  8. **Asset Storage (Filesystem First + DB Indexer) — IMPLEMENTED:**
     *   All generated artifacts are stored on the filesystem in a `default_user/YYYY/MM/DD` tree (`/{user_id}/` partition live, single-user `default_user`), with a DB-backed `assets` indexer (`infrastructure/asset_reconciler.py` + keyset-paginated `_query_gallery_files`) as the tracker. `metadata["workspace"]` (`main`/`roleplay`/`story`) + `character_id`/`story_id` scopes assets for workspace galleries (VISION #13); re-scan can't resurrect tombstoned deletes.
 9. **Multi-Tenancy (Future-Proofing) — DEFERRED:**
     *   The core platform is a single-user private sandbox. Audio/TTS and multi-tenancy are explicitly deferred for now (see Future Frontiers). `metadata["workspace"]` + the planned `/{user_id}/` layout leave room for a future "Guest/Ephemeral" mode, but no auth/multi-tenant code is being built yet.
10. **Database Expansion (PostgreSQL + pgvector):**
    *   Migrating from SQLite to PostgreSQL to leverage `pgvector` for semantic search (vector embeddings) across `Lorebooks` and chat histories. Adding domains for tracking `Characters`, `Lorebooks`, and `Scenarios` (acting as metadata indexers for the filesystem storage), while abstracting the `providers` table to simply track `worker_type` and health status.
12. **Interoperability & Data Standards (Compatible + Extended):**
    *   Assets like Character Cards and Chat Logs will strictly adhere to community standards (e.g., V2/V3 PNG specs, Tavern JSON) to ensure users can import/export seamlessly to platforms like SillyTavern or Chub.ai. 
    *   However, TNHComfy will inject custom, non-destructive metadata (e.g., specific ComfyUI visual tags, LoRA triggers, voice profiles) to unlock exclusive platform features without breaking backwards compatibility.
13. **UI Paradigm (Workspace-Scoped Galleries):**
    *   The UI will be divided into distinct "Workspaces" (Pages) rather than a single chaotic screen: Image Generation, Roleplay, and Story Sandbox.
    *   Assets generated within a workspace belong to that workspace. Furthermore, assets generated by a specific AI Chatbot will contain metadata tying them directly to that character, allowing for character-specific gallery filtering. 
    *   These workspaces are completely interoperable. Users can freely migrate or reference images, audio, or text between any workspace.
14. **Execution Flow (Autonomous Agentic Loops):**
    *   The platform will heavily utilize Agentic Function Calling via the native OpenAI JSON Tool Calling spec. 
    *   The LLMs are empowered with **Autonomous Looping**, allowing them to string multiple tool calls together (e.g., generating a background, then a character, then replying with text). 
    *   A backend Orchestrator will enforce sensible limits (Max Tool Calls per turn) to prevent infinite loops and manage serverless costs. Manual prompting and tool overrides will always remain available to the user.

---

## Implementation Status (as of 2026-08-10)

| Area | Status | Notes |
|------|--------|-------|
| Pillar 1 — Image Gen | ✅ Working | Modal + Beam + direct_url engines; direct_url crash (NameError) fixed, health checks local-only |
| Pillar 2 — Roleplay | ✅ Working | Agentic mode, narrator, tool-calls as `Message.kind`; chat Illustrate route wired, UI button pending |
| Pillar 3 — Story | ✅ Working | Story continue + illustrate + branching (retry from beat) implemented |
| Pillar 4 — World Vault | ✅ Working | Characters, lorebooks (pgvector), semantic retrieval |
| #5 Unified Protocol | ✅ Implemented | `provider_core.models.TaskEvent`; all engines emit it (LLM anthropic/google/modal fixed 2026-08-10); single backend reader |
| #7 Context (backend-owned) | ✅ Implemented | `context_builder.py` authoritative; frontend sends text + flags |
| #8 Asset storage | ✅ Implemented | DB `assets` indexer + keyset gallery; `default_user/` partition; workspace/character/story scoping |
| #13 Story branching | ✅ Implemented | `parent_beat_id` + "retry from here" |
| #9 Multi-tenancy | ⏸️ Deferred | No auth/multi-tenant code yet (single-user by design) |
| Audio / TTS | ⏸️ Deferred | Not started |
| Video/Animation, Visual Novel | 🔮 Future | Post-core expansion |

**Known gaps being addressed (roadmap):**
- In-chat "Illustrate" UI button (route + backend complete; StorySandbox equivalent exists), virtualized `SceneGallery`, `GeneratorShell` consolidation (deferred), tool-call transcript chips.
- Per-engine integration tests inside `provider_containers` (protocol tests added; engine-level parity for beam/modal clients next).
- LLM context/token heuristics (`estimate_tokens`) remain approximate — acceptable for single user.

---
*Note to AI Agents: This document dictates the macro-level trajectory of the project. Any architectural decisions, database changes, or frontend refactors should keep this multimodal, unrestricted end-goal in mind.*
