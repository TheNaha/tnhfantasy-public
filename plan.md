# Project Roadmap

See `AGENTS.md` and `docs/` for architecture, conventions, and API reference.

## Phases

### Phase 1: Foundation ✓
- FastAPI backend with SQLite, manual migrations, domain-driven structure
- React frontend with Zustand (UI) + React Query (server data), Vite on 5174
- Docker Compose stack (backend → frontend → providers)
- Provider container system for ComfyUI inference workers

### Phase 2: Refactoring & Consolidation ✓ (Batches B1-B6)
- 11 critical backend bugs, 8 high-severity fixes, 8 frontend fixes, 4 architecture cleanups
- 7 features: LB persistence, lifecycle cleanup, autopopulate, job/provider UI
- Autopopulate search unification with Discover page

### Phase 3: Harden & Production-Readiness (Current)
- Codebase hardening: fix N+1 queries, missing endpoints, DI violations, unreachable code
- Frontend state management: migrate server data from Zustand to React Query
- Provider container: fix protocol compliance, path handling, deletion logic
- Infra: clean up tracked patch files, unify Docker Compose docs, add plan.md
