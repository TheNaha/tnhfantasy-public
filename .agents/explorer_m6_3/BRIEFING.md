# BRIEFING — 2026-06-19T14:12:04Z

## Mission
Analyze the `Dashboard.jsx` monolith and propose a detailed refactoring/decomposition plan into modular sub-components without making any code changes.

## 🔒 My Identity
- Archetype: Explorer
- Roles: Teamwork explorer, Read-only investigator
- Working directory: /home/thenaha/containers/stacks/comfyui/.agents/explorer_m6_3
- Original parent: f3fe977c-2535-4010-aa01-d012ab0834b3
- Milestone: M6 (Decompose Dashboard Monolith)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- No internet access (CODE_ONLY mode)
- Output only metadata and reports to `.agents/explorer_m6_3/` (no code/test files here)
- Follow the Handoff Protocol and communicate results back via `send_message`

## Current Parent
- Conversation ID: f3fe977c-2535-4010-aa01-d012ab0834b3
- Updated: 2026-06-19T14:12:04Z

## Investigation State
- **Explored paths**:
  - `frontend_v2/src/pages/Dashboard.jsx` (the page container component)
  - `frontend_v2/src/hooks/useDashboardModals.js` (hook for modal visibility and jobs actions)
  - `frontend_v2/src/hooks/useDashboardSelection.js` (hook for batch actions and selections)
  - `frontend_v2/src/hooks/useGalleryAutoRefresh.js` (hook for auto-refreshing gallery)
- **Key findings**:
  - `Dashboard.jsx` is a coordinator (546 lines) that handles complex states and callbacks, but delegates actual layout rendering of lists/timeline to imported sub-components.
  - The return block contains 6 individual modal and drawer panels, cluttering the view.
  - The WebSocket event subscription (`JOB_COMPLETED`) is managed inside `Dashboard.jsx` and passed down, but could be encapsulated in `useGalleryAutoRefresh` to simplify the page logic.
  - Image parameter extraction is implemented in `Dashboard.jsx` but could be cleaner in a dedicated hook (`useReuseParameters.js`).
- **Unexplored areas**: None. Codebase investigation of the dashboard is complete.

## Key Decisions Made
- Decompose the JSX structure into logical visual wrappers: `DashboardHeaderToolbar`, `DashboardGalleryGrid`, `DashboardOverlays`, and `GeneratorFloatingButton`.
- Create new custom hooks (`useDashboardActions`, `useReuseParameters`) to strip coordinate logic and side-effects out of `Dashboard.jsx`.
- Encapsulate the WebSocket event handler directly within `useGalleryAutoRefresh` hook.


## Artifact Index
- `/home/thenaha/containers/stacks/comfyui/.agents/explorer_m6_3/handoff.md` — Final structured investigation report
