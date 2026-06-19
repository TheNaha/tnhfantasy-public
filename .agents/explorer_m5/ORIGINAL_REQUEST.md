## 2026-06-19T13:55:27Z
You are the teamwork_preview_explorer for Milestone 5 (Frontend State & WebSocket Cleanup).
Your working directory is /home/thenaha/containers/stacks/comfyui/.agents/explorer_m5/.
Your task is to analyze the frontend state management and WebSocket lifecycle.
1. Inspect `frontend_v2/` files, particularly `src/store/`, `src/hooks/`, `src/api/`, and files managing WebSocket connections.
2. Determine where UI state, form drafts, and cache are stored. Evaluate if there is blurred data ownership between Zustand and React Query (as noted in context.md and AGENTS.md).
3. Analyze how WebSocket events are handled. Are they coupled with the Zustand store?
4. Recommend a clear refactoring strategy to separate concerns:
   - Establish clean boundaries between Zustand (for transient UI state, local selections, drafts) and React Query (for server state, history list, provider lists).
   - Extract WebSocket setup/cancellation out of the global Zustand store to a decoupled listener/hook.
5. Provide detailed file paths, line numbers, and code snippets of the components and hooks that need modification.
6. Write your report to `/home/thenaha/containers/stacks/comfyui/.agents/explorer_m5/handoff.md`. Do not implement any changes.
