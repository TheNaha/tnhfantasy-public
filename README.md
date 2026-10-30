# TNHComfy

An AI fantasy engine with three pillars sharing one data layer (the World Vault): image generation, roleplay chat, and a story sandbox. See [docs/architecture.md](docs/architecture.md).

## Documentation

- [Architecture Overview](docs/architecture.md)
- [Frontend Documentation](docs/frontend.md)
- [Backend Documentation](docs/backend.md)
- [Deployment Guide](docs/deployment.md)
- [API Reference](docs/api.md) (generated)
- [Provider Architecture](docs/provider-architecture.md)
- [LLM Provider Handoff](docs/llm-provider-handoff.md)
- [SillyTavern Card Compatibility](docs/sillytavern-compatibility.md)
- [Roleplay Coherence](docs/roleplay-coherence.md)
- [Status / open work](docs/STATUS.md)

## Stack

- **tnhcomfy-db** — PostgreSQL 16 + pgvector
- **tnhcomfy-frontend** — React 19 + Vite (port 5174, bun only)
- **tnhcomfy-backend** — FastAPI on port 8002 (loopback/named addresses only; no auth)
- **Compute** — in-process engines in `backend_v2/services/engines/` talking to Modal, Beam, Direct ComfyUI, and remote agents over the network. There are no provider sidecar containers in this stack.

## Quick start

1. Copy `.env.example` to `.env` and configure. `.env.example` is the canonical reference for every environment variable the code reads.
2. On a new host, run `scripts/preflight.sh` first — it creates the external `metrics`/`proxy` networks and reports config that silently disables features.
3. Start the stack:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -V -d
   ```
   `-V` matters in dev (frontend `node_modules` anonymous volume).
4. Open the Web UI on port **5174**.

## Package manager

The frontend workspace in `frontend_v2` is **bun only**. `npm`, `pnpm` and `yarn` are rejected by the preinstall guard. Use `bun install`, `bun run dev`, `bun run test`, `bun run build`.

## Backend (host-only)

```bash
cd backend_v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8002 --reload
```

The host-only path uses SQLite by default (`sqlite:///./data/db/comfy.db`); the Compose stack uses PostgreSQL. They are different databases.

## Maintenance

Output images and the whole `data/` directory (PostgreSQL cluster, image output, generated `config.json`) are excluded from version control. There is no automated backup — see `docs/deployment.md`.
