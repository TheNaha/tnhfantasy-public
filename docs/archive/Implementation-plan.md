> **ARCHIVED** — historical, kept for provenance only. This document was
> stale or superseded when archived and may contradict current code.
> **Archived. See docs/STATUS.md and docs/archive/README.md.**

# Implementation Plan: TNHComfy "Demo to Pro" & Future Frontiers

## Goal Description
This plan outlines the strategic steps to evolve TNHComfy from an image generation wrapper with "demo-like" new features into a polished, feature-complete **Comprehensive AI Fantasy Engine**. It addresses immediate technical debt, significantly expands Quality-of-Life (QoL) features for the newworkspaces, and maps out the integration of massive future capabilities (TTS, RAG, AI Parsing).

Once approved, the first execution step will be to formally document these future frontiers into `PLAN.md` and `VISION.md` at the project root for all future agents to reference.

## User Review Required
> [!WARNING]
> **Scope & Priority**: This is a massive roadmap. After you approve the overall direction, please indicate which specific section (e.g., Chat QoL,Story Sandbox, or System Consolidation) you want me to start coding *first*.

---

## Phase 1: "Demo to Pro" QoL Refinements
*Focus: Taking the new workspaces from basic implementations to feature-complete, power-user ready tools.*

### 1. Chat Workspace (Roleplay)
- **Swipes & Branching**: Allow users to swipe (regenerate) an AI response to get alternatives, keeping the history of swipes intact.
- **Message Management**: Add robust edit, delete, and insert capabilities for both User and AI messages anywhere in the chat history.
- **Group Chats (Foundation)**: Refactor the UI and backend data model to support multiple characters in a single chat room. This is a prerequisitefor the Agentic Idle Simulation.
- **Inline Generation**: Allow users to manually trigger image or audio generation for specific messages without relying entirely on the AI's autonomous tool calls.

### 2. Story Sandbox
- **Rich Text & Formatting**: Upgrade the editor to support rich text, headers, and scene breaks natively.
- **Inline Referencing**: Add UI components to instantly view and edit Character or Lorebook entries while staying inside the story editor.
- **Granular Control**: Add undo/redo history for AI generations. Allow users to manually accept, reject, or edit an AI-generated "beat" before committing it to the document.

### 3. World Vault & Characters
- **Organization**: Add folders, tagging, and advanced filtering to the Characters and Lorebooks views.
- **Drag-and-Drop**: Implement drag-and-drop for organizing collections and sorting lorebook priorities.

---

## Phase 2: System Consolidation & Hardening
*Focus: Paying down technical debt and optimizing the core engine.*

### 1. GeneratorShell Consolidation
- **Action**: Create a `useWorkflowBuilder(mode)` hook to centralize the ComfyUI payload assembly currently duplicated across Simple, Img2Img, and Inpaint pages. The pages will become thin wrappers around the `UnifiedGeneratorLayout`.

### 2. LLM Context Estimation
- **Action**: Replace the crude `chars / 3.5` heuristic in `context_builder.py` with a lightweight, robust tokenizer (e.g., `tiktoken` for OpenAI-compatibles) to guarantee we maximize context windows without crashing.

### 3. Engine Parity & Performance
- **Action**: Add full protocol translation tests to the Beam client. Transition any remaining `Zustand` server-state to `React Query` to prevent sync issues and memory leaks in large virtualized galleries.

---

## Phase 3: Immediate New Modalities (Audio & AI Import)

### 1. ComfyUI-Powered Audio / TTS
- **Architecture**: We will use ComfyUI as the engine for Audio/TTS, eliminating the need for a separate custom worker.
- **Implementation**: The backend will assemble audio workflows (e.g., XTTS v2 or Bark custom nodes) and dispatch them to the existing `image_worker` (which acts as a universal ComfyUI adapter). The Unified Protocol will stream back base64 audio chunks to be played in the Chat and Story interfaces.

### 2. AI Story Parsing & Import
- **Feature**: Allow users to paste a massive text dump (e.g., a PDF chapter or raw text).
- **Implementation**: Create a specialized LLM tool workflow that scans the text and automatically extracts entities, generating Character Cards, Locations, and Lorebook entries to instantly populate the World Vault.

---

## Phase 4: Massive Future Frontiers (To be added to project root)

1. **Autobiographical Memory (RAG)**: Indexing all past chat messages and story beats into `pgvector` so the LLM can perfectly recall distant events across long campaigns.
2. **Visual Novel / Comic Compiler**: An exporter that reads a Story Sandbox chapter and automatically generates images, panels, and speech bubblesto output a formatted web-comic or PDF.
3. **Relationship Graph UI**: A living, node-based wiki (similar to Obsidian) visualizing the connections between Characters, Locations, and Lorebooks.
4. **Agentic Idle Simulation**: Background cron jobs where characters autonomously live, craft, and interact while the user is offline, summarizingtheir actions upon return. (Requires Group Chats to be finished first).
5. **Video / Animation**: Expanding the ComfyUI payload to support AnimateDiff for looping character avatars.

---

## Verification Plan
### Automated Tests
- Write Vitest unit tests for the consolidated `useWorkflowBuilder`.
- Write Pytest integration tests for the new AI Story Parsing tool calls.

### Manual Verification
- Manually test editing, deleting, and swiping messages in Chat Workspace.
- Ensure ComfyUI TTS generates a valid `.wav`/`.mp3` in the frontend player.