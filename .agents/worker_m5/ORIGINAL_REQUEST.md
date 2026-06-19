## 2026-06-19T13:57:18Z
Implement Milestone 5 using the refactoring strategy from `/home/thenaha/containers/stacks/comfyui/.agents/explorer_m5/handoff.md`:
1. Relocate Collections state/CRUD operations from Zustand (in useStore.js) to React Query hooks (create useCollections.js).
2. Relocate Prompts state/CRUD operations from Zustand by deleting promptStore.js and creating usePrompts.js React Query hook.
3. Decouple WebSockets and Jobs State by deleting jobStore.js and creating useActiveJobs.js, useJobsRealtime.js, and useTrackJob(jobId) hooks.
4. Update all React frontend components, pages, hooks, and modals that consume the old Zustand stores or global state pointers (e.g. SimpleGenerator.jsx, Dashboard.jsx, useDashboardModals.js) to use the new React Query hooks and local trackers.
5. Run the frontend test suite using `npm test` and ensure all tests pass (fixing/mocking tests as needed). Run linting using `npm run lint`.
6. Write a detailed handoff report in `/home/thenaha/containers/stacks/comfyui/.agents/worker_m5/handoff.md` detailing all file changes, new hooks, and test results.
