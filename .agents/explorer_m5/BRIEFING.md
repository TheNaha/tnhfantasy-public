# BRIEFING — 2026-06-19T13:55:27Z

## Mission
Analyze frontend state management and WebSocket lifecycle in frontend_v2 to plan clean separation of Zustand and React Query.

## 🔒 My Identity
- Archetype: Teamwork explorer
- Roles: Read-only investigation: analyze problems, synthesize findings, produce structured reports
- Working directory: /home/thenaha/containers/stacks/comfyui/.agents/explorer_m5/
- Original parent: a9200e62-ab8a-41c8-9335-d46986461782
- Milestone: Milestone 5 (Frontend State & WebSocket Cleanup)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Code-only network restrictions (no external HTTP clients, use filesystem tools only)

## Current Parent
- Conversation ID: a9200e62-ab8a-41c8-9335-d46986461782
- Updated: not yet

## Investigation State
- **Explored paths**:
  - `frontend_v2/src/store/useStore.js`
  - `frontend_v2/src/store/promptStore.js`
  - `frontend_v2/src/store/jobStore.js`
  - `frontend_v2/src/hooks/useWebsocket.js`
  - `frontend_v2/src/hooks/useProvidersPageData.js`
  - `frontend_v2/src/pages/Dashboard.jsx`
  - `frontend_v2/src/pages/SimpleGenerator.jsx`
- **Key findings**:
  - Blurred data ownership: Collections (`useStore.js`), Prompts (`promptStore.js`), and Active Jobs (`jobStore.js`) cache server state inside Zustand, creating boilerplate for state validation, loading flags, and manual refetching.
  - WebSocket event handling in `useWebsocket.js` is tightly coupled to `useJobStore`, directly dispatching to Zustand instead of patching a React Query server cache.
  - Single-variable job tracking in stores (`lastCompletedJob` etc.) poses race condition risks in multi-job scenarios.
- **Unexplored areas**:
  - None.

## Key Decisions Made
- Outlined a phase-based refactoring strategy to shift Collections, Prompts, and Jobs to React Query, and decouple WebSockets into a dedicated query-patching listener.

## Artifact Index
- /home/thenaha/containers/stacks/comfyui/.agents/explorer_m5/handoff.md — Analysis and refactoring plan for state management and WebSockets.
- /home/thenaha/containers/stacks/comfyui/.agents/explorer_m5/progress.md — Progress report tracking steps.
