# TNHFantasy Documentation

## Table of contents

1. [Architecture Overview](architecture.md)
2. [Backend Documentation](backend.md)
3. [Frontend Documentation](frontend.md)
4. [Deployment Guide](deployment.md)
5. [API Reference](api.md) (generated from `app.openapi()`)
6. [Provider Architecture](provider-architecture.md) — which tree runs where, and why it is split
7. [Roleplay Coherence](roleplay-coherence.md) — World Vault ownership and prompt reachability
8. [SillyTavern Card Compatibility](sillytavern-compatibility.md)
9. [LLM Provider Handoff](llm-provider-handoff.md) — llama.cpp design brief
10. [Status and open work](STATUS.md)
11. [Host scripts](scripts.md) — preflight.sh, deploy.sh, generate_api_docs.py, and the backend maintenance scripts
12. [Audits](.audit/) — documentation audits; [maintenance/](maintenance/) — codebase maintenance audits
13. [Remote Agent](../remote_agent/README.md) — standalone worker runtime for Colab, remote ComfyUI, or a hosted agent
14. [Deployables](../deployables/README.md) — cloud worker source for Modal and Beam providers

## Introduction

TNHFantasy is an AI fantasy engine with three pillars — image generation, roleplay chat, and a story sandbox — sharing the World Vault data layer (Characters, Chats, Lorebooks, Stories, Personas, Worlds, Locations, Scenarios, Voices, Memories) in PostgreSQL + pgvector.

The backend is FastAPI + SQLModel with no Alembic (migrations are ordered steps in `infrastructure/migrations/steps.py`). The frontend is React 19 + Vite, bun only, on port 5174. Inference runs in-process via `backend_v2/services/engines/`; cloud workers are deployed only with `scripts/deploy.sh`.

## Conventions that matter

- Backend binds loopback only (`127.0.0.1` / one named address). The API has no authentication.
- Frontend dev port is **5174**, not 5173.
- `docs/api.md` is generated; run `scripts/generate_api_docs.py` after changing a router.
- `.env.example` is the canonical reference for every environment variable.
