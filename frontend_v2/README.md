# Frontend (TNHComfy)

React + Vite frontend for the TNHComfy serverless ComfyUI stack.

## Tech Stack

- **React 19** with Vite 7
- **Tailwind CSS 4** (`@tailwindcss/postcss` plugin)
- **Zustand 5** for client/UI state and WebSocket-driven realtime updates
- **React Query 5** (`@tanstack/react-query`) for HTTP data fetching and caching
- **Vitest 4** for testing (jsdom environment)

## Quick Start

```bash
npm install
npm run dev -- --host 0.0.0.0 --port 5174
```

## Commands

| Command | Description |
|---------|-------------|
| `npm run dev` | Start dev server (port 5174) |
| `npm run build` | Production build |
| `npm test` | Run tests |
| `npm run test:watch` | Run tests in watch mode |
| `npm run lint` | Run ESLint |

## State Management

Read `STATE_MANAGEMENT.md` before changing state logic.

- **Zustand** (`src/store/`): UI state, form drafts, realtime WebSocket job updates
- **React Query** (`src/hooks/`): HTTP fetching, caching, mutations

## Important

- This workspace is **npm-only**. `pnpm` and `yarn` are rejected by a preinstall guard.
- The dev server runs on **port 5174** (not 5173).
- Vite proxy fallback: `VITE_PROXY_TARGET` -> `VITE_API_URL` -> `http://localhost:8002`.
