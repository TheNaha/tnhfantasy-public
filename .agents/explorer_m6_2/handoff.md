# Handoff Report: Dashboard.jsx Monolith Decomposition

## 1. Observation
Currently, `frontend_v2/src/pages/Dashboard.jsx` is a **546-line monolith** (Lines 1 to 546) that acts as both the logic controller and the layout presenter for the primary application dashboard.

### Key Observations of Current Monolith Structure:
1. **Heavy Imports and State Hooks (Lines 1-54):**
   - Consumes 14 distinct custom hooks (e.g., `useGallery`, `useDashboardItems`, `useDashboardSelection`, `useActiveJobs`, `usePullToRefresh`, etc.).
   - Directly references Zustand stores (`useGeneratorStore`, `useSettingsStore`, `useStore`) and React Query client (`useQueryClient`).
2. **Business Logic & Event Subscriptions (Lines 57-347):**
   - Directly handles WebSocket events for `JOB_COMPLETED` (Lines 109-114):
     ```javascript
     useEffect(() => {
         return ws.on(ws.EventTypes.JOB_COMPLETED, (event) => {
             const job = event.data?.job || event;
             setLastCompletedJob(job);
         });
     }, []);
     ```
   - Integrates parameters reuse, batch selection execution, image deletion confirmations, and pull-to-refresh coordination directly in the component body.
3. **Inline Presentation Rendering (Lines 348-545):**
   - Combines structural wrappers (motion wrappers, spacing containers) with:
     - Control bars (Header, Toolbar, FilterBar, SelectionToolbar).
     - Grid layout content (Skeleton loading, Empty states, TimelineView, GroupedDashboardContent).
     - Modals and Overlay Panels (ImageLightbox, JobDetailsModal, ImageComparison, CollectionsPanel, SelectCollectionModal, StatsPanel).
     - Mobile-only Floating Action Button (FAB).

---

## 2. Logic Chain

1. **High Cognitive Load:** Because layout markup, transition animations, state orchestration, API callback mutations, and subscription cleanups are co-located in one file, changes to layout risk breaking business logic, and vice versa.
2. **Separation of Concerns (Container/Presenter Pattern):**
   - If we extract all state setup, local states, refs, and callback definitions into a custom state controller hook (e.g., `useDashboardState.js`), the main `Dashboard` page component becomes a simple orchestrator.
   - If we extract the inline presentation layers (Grid, Controls, Modals, mobile FAB) into standalone functional components under `src/components/dashboard/`, each file will remain small (<150 lines), readable, and easily testable.
3. **Prop-Drilling vs. Context:** Because the proposed sub-components will be direct, 1-level-deep children of the main `Dashboard` container, they can receive state properties and callback handlers directly via props. This avoids the overhead of introducing React Context and keeps the data flow explicit and predictable.

---

## 3. Caveats
- **Chokidar & HMR in Docker:** Verification of frontend rendering during actual changes must take place in an environment where hot reloading is running, potentially utilizing chokidar polling in Docker environments as specified in `AGENTS.md`.
- **Keyboard Shortcuts Hook:** `useKeyboardShortcuts` hooks directly inside `Dashboard.jsx`. Moving it to the state hook is appropriate, but we must ensure its context behaves properly on ESC keypresses.
- **Pull-To-Refresh Ref:** `containerRef` returned by `usePullToRefresh` is attached to the outer container. We must pass this ref down to the `DashboardLayout` component cleanly.

---

## 4. Conclusion

### Proposed Decomposed Architecture

We propose introducing a single custom state hook and five modular presenter sub-components:

#### A. Custom State Hook: `useDashboardState`
* **Target Path:** `frontend_v2/src/hooks/useDashboardState.js`
* **Responsibility:** Consolidate all state declarations, settings selectors, store actions, API hooks, and event handlers.
* **Return Value:** An object containing all states, callbacks, refs, and config constants.

#### B. Component: `DashboardLayout`
* **Target Path:** `frontend_v2/src/components/dashboard/DashboardLayout.jsx`
* **Responsibility:** Renders the page container, handles entry/exit motion animations, and provides the pull-to-refresh wrapper target.
* **Props:**
  - `containerRef`: React Ref (for the pull-to-refresh target)
  - `pullDistance`: number
  - `isRefreshing`: boolean
  - `isPulling`: boolean
  - `children`: React.ReactNode

#### C. Component: `DashboardControls`
* **Target Path:** `frontend_v2/src/components/dashboard/DashboardControls.jsx`
* **Responsibility:** Group and arrange `DashboardHeader`, `DashboardToolbar`, `SelectionToolbar`, and `FilterBar`.
* **Props:**
  - `viewMode` / `setViewMode`
  - `gridCols` / `setGridCols`
  - `selectionMode` / `setSelectionMode`
  - `selectedFiles` / `setSelectedFiles`
  - `favorites` / `collections` / `activeCollection`
  - `setShowCollectionsPanel` / `setShowStatsPanel`
  - `onClearHistory` / `onRefetch`
  - `handleBatchDownload` / `handleBatchDelete` / `handleBatchFavorite`
  - `handleAddSelectionToCollection` / `handleRemoveSelectionFromCollection`
  - `handleCancelSelectionMode`
  - `filters` / `setFilters`

#### D. Component: `DashboardGrid`
* **Target Path:** `frontend_v2/src/components/dashboard/DashboardGrid.jsx`
* **Responsibility:** Encapsulate the loading skeleton, empty states, and gallery display modes (timeline vs grouped grid) including the infinite scroll sentinel.
* **Props:**
  - `isLoading`: boolean
  - `viewMode`: string
  - `showFavorites`: boolean
  - `setShowFavorites`: function
  - `activeCollection`: string
  - `setActiveCollection`: function
  - `filters`: object
  - `setFilters`: function
  - `allItems`: array
  - `displayedItems`: array
  - `sortedGroupedEntries`: array
  - `formatDateLabel`: function
  - `gridCols`: number
  - `selectedFiles`: Set
  - `selectionMode`: boolean
  - `handleJobClick`: function
  - `handleImageClick`: function
  - `toggleSelection`: function
  - `fastIsFavorite`: function
  - `handleToggleFavorite`: function
  - `handleDelete`: function
  - `handleJobDelete`: function
  - `sentinelRef`: React Ref
  - `isFetchingNextPage`: boolean

#### E. Component: `DashboardModals`
* **Target Path:** `frontend_v2/src/components/dashboard/DashboardModals.jsx`
* **Responsibility:** Overlay container mounting lightbox, job details modal, comparison slider, collection selection dialog, collections slide-out, and statistics modal.
* **Props:**
  - `selectedImage` / `lightboxImages` / `handleLightboxNavigate`
  - `metadata` / `loadingMeta` / `closeSelectedImage`
  - `handleDelete` / `useParameters` / `isReusingParameters`
  - `selectedJob` / `handleJobDetailsClose` / `cancelJob` / `deleteJob` / `retryJob`
  - `showComparison` / `setShowComparison`
  - `allItems` / `selectedFiles` / `setSelectedFiles`
  - `showCollectionsPanel` / `setShowCollectionsPanel`
  - `showSelectCollection` / `setShowSelectCollection`
  - `collections` / `addToCollection` / `setSelectionMode`
  - `showStatsPanel` / `setShowStatsPanel`

#### F. Component: `MobileGenerateButton`
* **Target Path:** `frontend_v2/src/components/dashboard/MobileGenerateButton.jsx`
* **Responsibility:** Present the floating action button to jump to the generator page on mobile view.
* **Props:**
  - `onClick`: function

---

### Step-by-Step Refactoring Strategy

1. **Step 1: Create the Custom Hook**
   - Extract state variables, store hookups, and callback logic from `Dashboard.jsx` into `frontend_v2/src/hooks/useDashboardState.js`.
   - Re-export the state object cleanly.
2. **Step 2: Create Sub-Components (Presenter Phase)**
   - Create `DashboardLayout.jsx`, `DashboardControls.jsx`, `DashboardGrid.jsx`, `DashboardModals.jsx`, and `MobileGenerateButton.jsx`.
   - Copy relevant markup sections from the old `Dashboard.jsx` file to each new component file.
   - Establish correct explicit React PropTypes (or JSDoc typings) for the props.
3. **Step 3: Simplify the Monolith (`Dashboard.jsx`)**
   - Clean up imports in `Dashboard.jsx`.
   - Replace the entire component body with:
     ```jsx
     import { useDashboardState } from '../hooks/useDashboardState';
     import DashboardLayout from '../components/dashboard/DashboardLayout';
     import DashboardControls from '../components/dashboard/DashboardControls';
     import DashboardGrid from '../components/dashboard/DashboardGrid';
     import DashboardModals from '../components/dashboard/DashboardModals';
     import MobileGenerateButton from '../components/dashboard/MobileGenerateButton';
     import QueueVisualization from '../components/QueueVisualization';

     export default function Dashboard() {
         const state = useDashboardState();
         return (
             <DashboardLayout
                 containerRef={state.containerRef}
                 pullDistance={state.pullDistance}
                 isRefreshing={state.isRefreshing}
                 isPulling={state.isPulling}
             >
                 <QueueVisualization onJobClick={state.handleJobClick} />
                 <DashboardControls {...state} />
                 <DashboardGrid {...state} />
                 <DashboardModals {...state} />
                 <MobileGenerateButton onClick={state.navigateToGenerate} />
             </DashboardLayout>
         );
     }
     ```
4. **Step 4: Dry Runs & Quality Checks**
   - Verify code formatting and resolve all lint issues.
   - Verify all unit test suites run cleanly.

---

## 5. Verification Method

To verify the correctness of the refactored files:

1. **Linting Verification:**
   Run the project eslint script to ensure there are no syntax errors, undefined variables, or unused variables:
   ```bash
   cd frontend_v2 && npm run lint
   ```
2. **Unit Test Verification:**
   Run the Vitest test suites to check if existing mock contexts and custom hooks behavior remain intact:
   ```bash
   cd frontend_v2 && npm test
   ```
3. **Functional Verification (Manual/Integration):**
   - Invalidate by checking if pull-to-refresh indicator functions.
   - Verify lightbox modal successfully navigates image siblings.
   - Verify grid timeline toggling changes the view mode dynamic layouts.
