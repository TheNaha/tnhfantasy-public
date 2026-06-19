# Synthesis Report — Milestone 6 Monolith Decomposition Plan

## Consensus
All three Explorer subagents agree that `Dashboard.jsx` (546 lines) is a monolith containing visual layout logic, modal controls, and state orchestration.
To achieve clean separation of concerns and high maintainability, they agree on extracting:
1. **Header & Controls Toolbar**: Combines header, filtering, and selection toolbars (`DashboardHeaderToolbar.jsx` or `DashboardControls.jsx`).
2. **Gallery Grid View**: Manages timelines, skeletons, empty states, and infinite scrolling (`DashboardGalleryGrid.jsx` or `DashboardGrid.jsx`).
3. **Modals & Overlays Manager**: Coordinates image lightbox, job details, comparisons, collections, stats panels (`DashboardOverlays.jsx` or `DashboardModals.jsx`).
4. **Floating Generator Button**: Mobile floating action button to jump to generator page (`GeneratorFloatingButton.jsx`).

## Reconciled Strategy
We will adopt the following structure for implementation:
- **Container Page (`Dashboard.jsx`)**: Coordinates the React Query and custom store hooks. It remains the single source of truth for the dashboard's state, subscribing to Zustand and React Query hooks and passing the resolved state and callbacks to child components.
- **Presenter Components (`frontend_v2/src/components/dashboard/`)**:
  - `DashboardHeaderToolbar.jsx` (controls, views, filters, selections)
  - `DashboardGalleryGrid.jsx` (timeline, grouped, skeletons, empty, scroll sentinel)
  - `DashboardOverlays.jsx` (lightbox, comparison, jobs modal, collections panel, stats)
  - `GeneratorFloatingButton.jsx` (FAB)

This approach minimizes the complexity of introducing extra state management files (such as separate custom action hooks) while reducing `Dashboard.jsx` to a clean, readable orchestrator (~150 lines).

## Refactoring Steps
1. Create `GeneratorFloatingButton.jsx`
2. Create `DashboardOverlays.jsx`
3. Create `DashboardGalleryGrid.jsx`
4. Create `DashboardHeaderToolbar.jsx`
5. Refactor `Dashboard.jsx` to import and compose these components.
6. Verify via `npm test` and `npm run lint`.
