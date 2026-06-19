## 2026-06-19T14:08:18Z

You are a worker assigned to Milestone 5 (Frontend State & WebSocket Cleanup) of the ComfyUI Wrapper project.
Your working directory is /home/thenaha/containers/stacks/comfyui/.agents/worker_m5_gen2.
Please perform the following tasks:
1. Fix the Temporal Dead Zone (TDZ) ReferenceError in frontend_v2/src/pages/Dashboard.jsx:
   In Dashboard.jsx, move the useStore hooks (accessing activeCollection, setActiveCollection, favorites, toggleFavorite) to the top of the Dashboard component (right after the settingsStore hooks and before the useActiveJobs / useCollections / useCollectionImages hooks).
2. Fix the outdated comment in frontend_v2/src/store/useStore.js:
   Update the comment referencing the deleted jobStore.js to reflect that job state lives in the React Query cache / useActiveJobs hook.
3. Verify your changes:
   Run frontend tests via `npm test -- --run` and linter via `npm run lint` in the frontend_v2 directory. Ensure there are no errors or failures.
4. Output your results:
   Create a handoff.md in your working directory (/home/thenaha/containers/stacks/comfyui/.agents/worker_m5_gen2/handoff.md) documenting:
   - What changes you made (files and lines modified)
   - Verification command outputs (npm test and npm run lint outputs)
   - Confirming that the TDZ issue is resolved.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.
