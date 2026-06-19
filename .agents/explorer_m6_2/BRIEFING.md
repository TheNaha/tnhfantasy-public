# BRIEFING — 2026-06-19T14:12:08Z

## Mission
Investigate the frontend Dashboard.jsx monolith and propose a detailed modular decomposition and refactoring plan.

## 🔒 My Identity
- Archetype: explorer_m6_2
- Roles: Read-only investigator
- Working directory: /home/thenaha/containers/stacks/comfyui/.agents/explorer_m6_2
- Original parent: f3fe977c-2535-4010-aa01-d012ab0834b3
- Milestone: Dashboard refactoring (M6)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement.
- Code-only network mode (no external HTTP access).
- Follow codebase conventions in AGENTS.md (e.g. state management, routing, testing, ports).

## Current Parent
- Conversation ID: f3fe977c-2535-4010-aa01-d012ab0834b3
- Updated: not yet

## Investigation State
- **Explored paths**:
  - `frontend_v2/src/pages/Dashboard.jsx` (Monolith analysis)
  - `frontend_v2/src/hooks/useDashboardModals.js` (State/callbacks tracking)
  - `frontend_v2/src/hooks/useDashboardSelection.js` (State/callbacks tracking)
- **Key findings**:
  - `Dashboard.jsx` is 546 lines, containing heavy integration of custom hooks, callback handlers, and nested component structure.
  - Much of the state and actions are already split into hooks like `useDashboardModals` and `useDashboardSelection`, which makes extracting UI components easier as props can be direct passes of these hook values.
  - Core layouts (grid display logic, controls, modals overlay structure, and mobile generator FAB) are currently inline within `Dashboard.jsx` rendering code, and can be cleanly separated.
- **Unexplored areas**: None. The analysis of `Dashboard.jsx` is complete.

## Key Decisions Made
- Decompose the monolith into:
  1. `useDashboardState` (custom state hook)
  2. `DashboardLayout` (wrapper component)
  3. `DashboardControls` (sub-component for top controls/bars)
  4. `DashboardGrid` (sub-component for gallery grid/timeline display)
  5. `DashboardModals` (sub-component for overlay panels/modals)
  6. `MobileGenerateButton` (sub-component for mobile FAB)

## Artifact Index
- /home/thenaha/containers/stacks/comfyui/.agents/explorer_m6_2/handoff.md — Decompose plan and analysis report (TBD)
