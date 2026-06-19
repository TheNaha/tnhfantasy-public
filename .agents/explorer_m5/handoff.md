# Milestone 5 Handoff Report — Frontend State & WebSocket Cleanup

This report synthesizes the investigation of the frontend state management and WebSocket lifecycle in `frontend_v2/`, identifying areas of blurred data ownership and detailing a refactoring strategy to separate concerns.

---

## 1. Observation

Direct observations and code locations within the `frontend_v2/` codebase:

### A. Server State Cached in Zustand (`useStore.js` and `promptStore.js`)
*   **Collections Cache in `frontend_v2/src/store/useStore.js` (Lines 52-284):** 
    The global `useStore` mixes local UI states (like `viewMode` and `activeCollection`) with server-side collection records. It includes loading and initialization flags (`collectionsLoading`, `collectionsInitialized`) and manual asynchronous syncing methods:
    ```javascript
    // Lines 58-64
    initCollections: async () => {
        if (get().collectionsInitialized) return;

        set({ collectionsLoading: true });
        // ... calls collectionsApi.listCollections() and maps it
    ```
    ```javascript
    // Lines 228-231
    addToCollection: async (collectionId, images) => {
        try {
            await collectionsApi.addImagesToCollection(collectionId, images);
            // ... manual state merging and thumbnail calculations
    ```

*   **Prompts Cache in `frontend_v2/src/store/promptStore.js` (Entire file):**
    This store holds only server-side data (`prompts: []`, `categories: []`) and functions calling the `promptsApi`:
    ```javascript
    // Lines 27-33
    export const usePromptStore = create((set, get) => ({
        // State
        prompts: [],
        categories: ['All', 'Portrait', 'Landscape', 'Anime', 'Abstract', 'Realistic', 'Custom'],
        isLoading: false,
        error: null,
        initialized: false,
    ```

### B. Tight Coupling Between WebSockets and Zustand (`useJobStore.js` and `useWebsocket.js`)
*   **WebSocket Handler Calls in `frontend_v2/src/hooks/useWebsocket.js` (Lines 3-12, 117-122):**
    The `useWebsocket` hook pulls multiple dispatcher functions directly from the Zustand `useJobStore`:
    ```javascript
    import { useJobStore } from '../store/jobStore';
    // ...
    export function useWebsocket() {
        const isConnected = useJobStore(state => state.isConnected);
        const connectionError = useJobStore(state => state.connectionError);
        const setConnectionStatus = useJobStore(state => state.setConnectionStatus);
        const processMessage = useJobStore(state => state.processMessage);
        const fetchJobs = useJobStore(state => state.fetchJobs);
    ```
    And inside its connection handlers, it feeds all real-time events directly into `processMessage`:
    ```javascript
    const eventUnsubscribers = eventTypes.map(eventType =>
        ws.on(eventType, (data) => {
            markEventReceived();
            processMessage(data); // <-- Tight coupling to Zustand
        })
    );
    ```

*   **Active Jobs List in `frontend_v2/src/store/jobStore.js` (Lines 18-30):**
    The `useJobStore` manages the real-time active jobs state, containing server-backed jobs array and single tracking pointers (`lastCompletedJob`, `lastFailedJob`, `lastCancelledJob`) which are updated via raw WebSocket message processing:
    ```javascript
    export const useJobStore = create((set, get) => ({
        jobs: [],
        lastCompletedJob: null,
        lastFailedJob: null,
        lastCancelledJob: null,
        // ...
        processMessage: (data) => {
            // ... parses job.created, job.progress, job.completed, etc.
        }
    ```

### C. Component Consumption & Local State Bypasses
*   **Modals State in `frontend_v2/src/hooks/useDashboardModals.js` (Lines 15-17):**
    The hook directly manipulates Zustand store values without going through store actions:
    ```javascript
    useJobStore.setState(state => ({
        jobs: state.jobs.filter(j => j.id !== jobId)
    }));
    ```
*   **Job Completion Tracking in `frontend_v2/src/pages/SimpleGenerator.jsx` (Lines 176-200):**
    Uses a single global `lastCompletedJob` variable to determine if the user's specific submitted generation is complete:
    ```javascript
    if (lastCompletedJob?.id === currentJobId) {
        setGenerating(false);
        // ...
        toast.success('Generation complete!', { icon: '✨' });
    }
    ```

---

## 2. Logic Chain

### Step 1: Blurred Data Ownership Causes Boilerplate and Desync
Caching CRUD-based server state (Collections and Prompts) in Zustand violates the separation between client UI state and HTTP-backed server state. It forces the developer to manually write:
1. Loading, error, and initialization flags (`collectionsLoading`, `initialized`, `isLoading`).
2. Duplicated logic for cache invalidation (e.g., calling `refreshCollections()` or `refresh()` manually on modifications).
3. Complex, error-prone nested state updates to merge updates on the client side (e.g. updating model list stats inside `useStore.js`).
Using React Query directly eliminates all manual cache synchronization and metadata flags.

### Step 2: Global Variables for Specific Job Tracking Lead to Race Conditions
Using single global fields (`lastCompletedJob`, `lastFailedJob`, `lastCancelledJob`) to handle job lifecycle events assumes only one job is ever run. If a user runs multiple jobs in parallel or on different pages, a fast-completing job will overwrite these fields, causing slower jobs to miss their completion checks or trigger incorrect UI redirects. Tracking should be localized to a specific `jobId` query or custom hook.

### Step 3: WebSocket Event Streams Do Not Require Zustand
As proven by `useProvidersPageData.js` (which subscribes to provider WebSockets and updates the React Query cache using `queryClient.setQueryData`), server data streams do not need a global Zustand store. Active jobs, job progress, and job detail records are server-state items and can be managed directly via React Query, using a decoupled WebSocket listener to patch the cache.

---

## 3. Caveats

*   **Connectivity Status**: The codebase defines connection indicators (`isConnected`, `connectionError`) inside `useJobStore`, but our search confirms they are not currently rendered in the UI. If a connection warning indicator is ever added, it should be backed by a lightweight client-only store or a simple WebSocket connection hook, rather than bringing back the entire jobs list store.
*   **Vitest Test Suites**: Deleting `jobStore.js` and `promptStore.js` will break existing tests (`jobStore.test.js`, `promptStore.test.js`, `useWebsocket.test.js`). The implementing agent must rewrite these tests to mock the new React Query hooks and custom WebSocket listeners.

---

## 4. Conclusion & Refactoring Strategy

We recommend a clean separation of concerns:
*   **Zustand**: Strictly for local UI selections, form inputs/drafts (e.g. prompt settings), and layout preferences.
*   **React Query**: For all server-side collections, prompts, and active job/history queries.
*   **Decoupled WebSockets**: Listening to events and patching the React Query cache directly instead of dispatching to Zustand.

### Phase 1: Relocate Collections to React Query
1.  **Modify `useStore.js`**: Strip `collections`, `collectionsLoading`, `collectionsInitialized` and all methods matching `*Collection*` (except `activeCollection` / `setActiveCollection`).
2.  **Create `src/hooks/useCollections.js`**:
    *   `useCollections()`: Query for `['collections']` fetching `collectionsApi.listCollections`.
    *   `useCollectionImages(collectionId)`: Query for `['collections', collectionId, 'images']` fetching `collectionsApi.getCollection(collectionId, true)` (lazy hydration).
    *   `useCreateCollection()`, `useDeleteCollection()`, `useRenameCollection()`: Mutations calling their respective API endpoints and invalidating `['collections']`.
    *   `useAddImagesToCollection()`, `useRemoveImagesFromCollection()`: Mutations taking array of images, performing batch updates, and invalidating `['collections']` and `['collections', collectionId, 'images']`.

### Phase 2: Relocate Prompts to React Query
1.  **Delete `src/store/promptStore.js`**.
2.  **Create `src/hooks/usePrompts.js`**:
    *   `usePrompts({ q, limit })` -> Query `['prompts', { q, limit }]`.
    *   `usePromptCategories()` -> Query `['prompts', 'categories']`.
    *   Mutations for `useCreatePrompt`, `useUpdatePrompt`, `useDeletePrompt`, `useImportPrompts`, and `useIncrementPromptUsage`.

### Phase 3: Decouple WebSocket & Jobs State
1.  **Delete `src/store/jobStore.js`**.
2.  **Create `src/hooks/useActiveJobs.js`**:
    *   Query `['jobs', 'active']`: calls `jobsApi.getActive`.
3.  **Create `src/hooks/useJobsRealtime.js`**:
    A decoupled hook that coordinates WebSocket event subscriptions with the React Query cache:
    ```javascript
    import { useEffect } from 'react';
    import { useQueryClient } from '@tanstack/react-query';
    import * as ws from '../api/websocket';
    import toast from 'react-hot-toast';

    export function useJobsRealtime() {
        const queryClient = useQueryClient();

        useEffect(() => {
            void ws.connect().then(() => ws.subscribe('job'));

            const unsubs = [];

            // 1. Job Created -> Prepend to active jobs list
            unsubs.push(ws.on(ws.EventTypes.JOB_CREATED, (event) => {
                const job = event.data?.job || event;
                queryClient.setQueryData(['jobs', 'active'], (old = []) => {
                    if (old.some(j => j.id === job.id)) return old;
                    return [job, ...old];
                });
            }));

            // 2. Job Progress/Updated -> Update in active list & specific query
            const handleUpdate = (event) => {
                const job = event.data?.job || event;
                queryClient.setQueryData(['jobs', 'active'], (old = []) =>
                    old.map(j => j.id === job.id ? { ...j, ...job } : j)
                );
                queryClient.setQueryData(['jobs', job.id], job);
            };

            unsubs.push(ws.on(ws.EventTypes.JOB_PROGRESS, handleUpdate));
            unsubs.push(ws.on(ws.EventTypes.JOB_UPDATED, handleUpdate));
            unsubs.push(ws.on(ws.EventTypes.JOB_POST_PROCESSING, handleUpdate));

            // 3. Job Terminated -> Remove from active, update detail, invalidate gallery, show toast
            const handleTermination = (event, type) => {
                const job = event.data?.job || event;
                queryClient.setQueryData(['jobs', 'active'], (old = []) =>
                    old.filter(j => j.id !== job.id)
                );
                queryClient.setQueryData(['jobs', job.id], job);
                queryClient.invalidateQueries({ queryKey: ['gallery'] });

                if (type === 'completed') {
                    toast.success(
                        <div>
                            <strong>Image generated!</strong>
                            <br />
                            <span className="text-sm opacity-80">{job.metadata_?.prompt?.substring(0, 50) || 'Job complete'}</span>
                        </div>,
                        { icon: '✨' }
                    );
                } else if (type === 'failed') {
                    toast.error(`Job failed: ${job.error || 'Unknown error'}`);
                } else if (type === 'cancelled') {
                    toast('Job cancelled', { icon: '🛑' });
                }
            };

            unsubs.push(ws.on(ws.EventTypes.JOB_COMPLETED, (e) => handleTermination(e, 'completed')));
            unsubs.push(ws.on(ws.EventTypes.JOB_FAILED, (e) => handleTermination(e, 'failed')));
            unsubs.push(ws.on(ws.EventTypes.JOB_CANCELLED, (e) => handleTermination(e, 'cancelled')));

            return () => {
                unsubs.forEach(unsub => unsub?.());
                ws.unsubscribe('job');
            };
        }, [queryClient]);
    }
    ```
4.  **Create a local hook `useTrackJob(jobId)`** to watch specific active jobs inside generators (`SimpleGenerator.jsx` etc.) using:
    ```javascript
    export function useTrackJob(jobId) {
        return useQuery({
            queryKey: ['jobs', jobId],
            enabled: !!jobId,
            staleTime: Infinity, // updated reactively by WebSocket
        });
    }
    ```

---

## 5. Verification Method

### A. Automated Unit Tests
Run Vitest locally in `frontend_v2/` to ensure syntax validation and that modified hooks don't break general bundling:
```bash
cd frontend_v2
npm run lint
npm test
```

### B. Verification of Query Cache Updates
Verify via React Query DevTools in development browser:
1. Open the dev console.
2. Select collections or submit a prompt, and verify that the queries `['collections']`, `['prompts']`, and `['jobs', 'active']` are populated.
3. Observe real-time progress update streams mutating the cache without triggering complete page re-fetches.
