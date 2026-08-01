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
5.  **Streaming Standardization (The Unified Protocol):**
    *   To accommodate the wildly different streaming formats of various engines (e.g., ComfyUI's NDJSON vs. OpenAI's SSE), parsing responsibility is shifted to the Worker.
    *   The Worker container will translate any engine's native stream into a single, unified stream format that the backend inherently understands. 
6.  **Codebase Merger & Standalone Deployments:**
    *   The fragmented `modal_worker` and `beam_worker` repositories will merge into `image_worker`. 
    *   Inside the worker, standalone deployment scripts (e.g., `modal_app.py`, `beam_app.py`) will reside to deploy the remote functions, with Modal prioritized as the primary production target.
7.  **Context Management (Stateful Frontend):**
    *   The platform will use a "SillyTavern Style" Stateful Frontend. The React frontend will be responsible for fetching all components (lore, chat history) and constructing the final massive prompt payload before sending it to the backend. This maximizes UI flexibility. Robust sync mechanisms (e.g., optimistic updates + React Query) will be required to prevent state desyncs.
8. **Asset Storage (Filesystem First & Partitioned):**
    *   All generated artifacts—Images, Audio, and Text (Chat logs, Stories)—will be stored directly on the filesystem in a robust, human-readable directory tree. 
    *   To future-proof for multi-tenancy, the filesystem will strictly enforce a `/{user_id}/` root partition immediately.
    *   The database acts merely as an indexer/tracker, allowing users to browse their creations via a standard OS file manager without vendor lock-in.
9.  **Multi-Tenancy (Future-Proofing):**
    *   The core platform will be built as a single-user private sandbox initially. 
    *   However, architectural choices will leave room for a future "Guest/Ephemeral" mode (cookie-based) to allow temporary sandboxed multi-tenancy once the core vision is completed.
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

## Future Frontiers
Once the core pillars (Image + Text + World) are integrated, the platform can expand into:
*   **Video/Animation:** Transforming static generated scenes into short animations using AnimateDiff or SVD.
*   **Visual Novel Mode:** An automated mode that turns roleplay logs or story generations into a playable, visual-novel style UI.

---
*Note to AI Agents: This document dictates the macro-level trajectory of the project. Any architectural decisions, database changes, or frontend refactors should keep this multimodal, unrestricted end-goal in mind.*
