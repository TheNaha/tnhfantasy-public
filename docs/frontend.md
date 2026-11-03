# Frontend Documentation

The frontend of TNHFantasy (`tnhfantasy-frontend`) is built with **React 19** and **Vite**, focusing on speed, modularity, and a modern developer experience. It runs on port **5174**.

## Package manager — bun only

This workspace is intentionally **bun-only**. The preinstall guard (`scripts/enforce-bun.cjs`) rejects npm, pnpm, and yarn.

```bash
cd frontend_v2
bun install        # or bun install --frozen-lockfile
bun run dev        # dev server on 5174
bun run lint && bun run test && bun run build   # == `bun run verify`, the CI order
bun run test -- src/path/to/file.test.jsx       # single file
bun run test:e2e                                 # Playwright; starts its own dev server on 5174
```

## Key technologies

- **React 19:** component-based UI rendering.
- **Vite:** fast local dev server and bundler. Dev port 5174; HMR uses polling in Docker (`usePolling: true` in `vite.config.js`).
- **Zustand:** client-side state (UI state, drafts, realtime job updates).
- **React Query:** server data fetching and caching (jobs, models, configuration).
- **Lucide React:** icon library.

## State management architecture

As outlined in `STATE_MANAGEMENT.md`, the frontend strictly separates client state from server state:

### 1. Zustand (client state)

Zustand is used for things that don't need a server round-trip or are driven by real-time events:

- **UI state:** modal states, active tabs, sidebar toggles.
- **Form state:** draft inputs, temporary selections before submission.
- **Collection UI state:** active collection selection in `useStore`.
- **Realtime job updates:** Socket.IO events bridge into job state.

### 2. React Query (server state)

React Query is used exclusively for fetching, caching, synchronising, and updating server state:

- HTTP data fetching (GET requests to API endpoints).
- Server state caching with configurable stale times.
- WebSocket state: realtime job updates bridged into React Query cache via `useJobsRealtime`.
- Mutations: POST/PUT/DELETE with automatic cache invalidation.
- Canonical provider data: `useProvidersPageData` owns `/api/v2/providers` and load-balancer data, and shares one realtime bridge across `Layout` and `Providers`.

**Rule:** do not store server data in Zustand. Persist World Vault relationships (a Story's `character_ids`, `lorebook_ids`, etc.) through mutations like `updateStory.mutate`, not through transient UI state.

## Provider data flow

Provider server data follows a single path:

1. `useProvidersPageData` fetches canonical provider records from `/api/v2/providers`.
2. The hook attaches one shared websocket subscription layer for provider, reconciliation, and model topics.
3. `Layout` and the `Providers` page read from the same React Query cache instead of maintaining duplicate provider stores or duplicate websocket listeners.

This keeps provider badges, cards, and realtime updates in sync without parallel caching layers.

## Collections flow

Collections are server-backed and bootstrapped during app startup:

1. `App.jsx` calls `initCollections()` once.
2. `useStore` loads collection metadata and canonical `imageCount` values from the backend.
3. Full `images[]` lists are loaded lazily with `loadCollectionImages()` when a collection is opened.

This avoids requiring eager image hydration just to display collection counts or filters.

## Core features

- **Job tracking:** real-time job status updates (pending, processing, completed, failed) via WebSockets (Socket.IO on `/socket.io`).
- **Image gallery:** visual display of generated images fetched from the backend.
- **Provider management:** shared provider status, reconciliation, and storage state via `/api/v2/providers`.
- **Generation parameters:** interfaces for adjusting prompts, negative prompts, steps, CFG scale, models, and LoRAs.
- **Optimistic updates:** immediate UI feedback for actions like deleting a job before the server confirms.

## Reaching the backend

In production, nginx proxies `/api/` to the backend. In development, Vite's proxy handles CORS. The fallback chain for the API URL is `VITE_PROXY_TARGET` → `VITE_API_URL` → `http://localhost:8002`. Only use an absolute URL when the user explicitly sets `VITE_API_URL` or `localStorage`.

The frontend is a reverse proxy to the API, so its bind address is the API's reach. `COMFY_FRONTEND_BIND` in `.env` names the one address to serve on; unset means loopback only. `0.0.0.0` publishes the whole unauthenticated API and `scripts/preflight.sh` fails on it.

## Styling

Tailwind CSS v4 with the `@tailwindcss/postcss` plugin, configured in `postcss.config.js`. Base styles are in `src/index.css` (`@import "tailwindcss"`).
