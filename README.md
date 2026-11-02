# TNHFantasy

An open-source **AI fantasy engine** combining image generation, roleplay chat, and interactive story sandbox. Built on a unified data layer (the **World Vault**) backed by PostgreSQL + pgvector for semantic search and character persistence.

**Status:** Production-ready. Active development focusing on multi-modal coherence, performance optimization, and provider ecosystem expansion.

## Features

- **Image Generation** — In-process ComfyUI nodes + distributed compute via Modal, Beam, or remote agents
- **Roleplay Engine** — Multi-turn conversation with character coherence, SillyTavern card compatibility
- **Story Sandbox** — Interactive narrative generation with persistent world state
- **Unified Data Layer** — PostgreSQL + pgvector for semantic character/world indexing
- **Modular Providers** — Swap image backends and LLM providers without code changes
- **Open Protocol** — Provider-agnostic NDJSON streaming for real-time inference

## Quick Links

- [Architecture](docs/architecture.md) — System design and data flow
- [Deployment Guide](docs/deployment.md) — Production setup and scaling
- [API Reference](docs/api.md) — REST endpoints and WebSocket schema
- [Provider Setup](docs/provider-architecture.md) — Add custom compute backends
- [Conventions](.github/copilot-instructions.md) — Development workflow and conventions

## Tech Stack

| Component | Tech | Purpose |
|-----------|------|---------|
| **Database** | PostgreSQL 16 + pgvector | World state, character cards, embeddings |
| **Frontend** | React 19 + Vite + Tailwind | Web UI (port 5174, bun only) |
| **Backend** | FastAPI + async job queue | API + job lifecycle (port 8002) |
| **Compute** | ComfyUI, Modal, Beam, remote agents | Image generation backends |

## Getting Started

### Prerequisites
- Docker & Docker Compose (recommended) OR Python 3.13+ + PostgreSQL 16
- Bun for frontend development

### With Docker (recommended)

```bash
# 1. Clone and configure
git clone https://github.com/yourusername/tnhfantasy-public.git
cd tnhfantasy-public
cp .env.example .env
# Edit .env with your Modal/Beam/ComfyUI credentials

# 2. Setup external networks (first time only)
bash scripts/preflight.sh

# 3. Start the stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -V -d

# 4. Open http://localhost:5174
```

### Local Development (host-only)

**Backend:**
```bash
cd backend_v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8002 --reload
```

**Frontend:**
```bash
cd frontend_v2
bun install
bun run dev -- --host 127.0.0.1 --port 5174
```

> **Note:** Host-only backend uses SQLite by default; Docker Compose uses PostgreSQL. They are separate databases.

## Configuration

See `.env.example` for all environment variables. Config precedence:
1. `COMFY_*` environment variables
2. `config.json` (generated on first run)
3. Hardcoded defaults in `backend_v2/config.py`

## Project Structure

```
backend_v2/          FastAPI server + job queue + provider engines
├── api/             Routes and request handlers
├── core/            Domain logic, events, exceptions
├── services/        Business logic, repositories, job queue
├── infrastructure/  Database, migrations, caching
└── tests/           Pytest suite (run via `pytest`)

frontend_v2/         React + Vite web client
├── src/
│   ├── api/         HTTP client and WebSocket handlers
│   ├── stores/      Zustand state (client/realtime)
│   ├── components/  React components
│   └── hooks/       Custom React hooks
└── tests/           Vitest suite (run via `bun run test`)

remote_agent/        Optional remote compute agent
├── provider_core/   Shared library for provider integration
├── daemon.py        Agent lifecycle and NDJSON streaming
└── tnhfantasy-agent.spec  PyInstaller spec for standalone binary

docs/                Architecture, API, deployment guides
scripts/             Setup, build, and utility scripts
```

## Development

### Running Tests

```bash
# Backend (from backend_v2/, inside the container or with .venv on the host)
docker exec tnhfantasy-backend python -m pytest -q tests/test_job_service.py

# Frontend (from frontend_v2/)
bun run test --run
```

### Code Guidelines

- Follow existing patterns in route → service → repository architecture
- Emit domain events via `core/events.py` helpers (not direct WebSocket sends)
- Use `core/exceptions.py` for domain errors (not ad-hoc HTTPException)
- Keep state ownership strict: Zustand for client/realtime, React Query for server-fetched data
- See `.github/copilot-instructions.md` for detailed conventions

## Deployment

See [docs/deployment.md](docs/deployment.md) for production setup, scaling, monitoring, and backup strategies.

Key points:
- Backend is stateless and horizontally scalable
- Job queue persists pending/running jobs to DB; startup recovery is automatic
- Configure provider credentials in `.env` (Modal token, Beam API key, etc.)
- Use managed PostgreSQL (AWS RDS, Azure Database, etc.) for production

## Contributing

Contributions welcome! Please:
1. Fork and create a feature branch
2. Make focused, well-tested changes
3. Run the full test suite before opening a PR
4. Write clear commit messages

See [.github/copilot-instructions.md](.github/copilot-instructions.md) for architecture guidelines and [VISION.md](VISION.md) for the long-term roadmap.

## License

MIT — see [LICENSE](LICENSE)

## What's Next?

- [x] Rebranded and open-sourced
- [ ] Community providers (HuggingFace Inference API, local Ollama, etc.)
- [ ] Fine-tuned roleplay model
- [ ] Multi-user collaboration and world sharing
- [ ] Advanced story generation with branching narratives

See [docs/STATUS.md](docs/STATUS.md) and [VISION.md](VISION.md) for the full roadmap.

## Support

- **Issues:** GitHub Issues for bugs and feature requests
- **Discussions:** GitHub Discussions for ideas and architecture questions
- **Documentation:** Check [docs/](docs/) first — most questions are answered there

## Acknowledgments

Built with:
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) — Node-based image generation
- [FastAPI](https://fastapi.tiangolo.com/) — Modern Python web framework
- [React](https://react.dev/) — UI library
- [Modal](https://modal.com/) + [Beam](https://www.beam.cloud/) — Serverless compute
- [pgvector](https://github.com/pgvector/pgvector) — Vector similarity search
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
