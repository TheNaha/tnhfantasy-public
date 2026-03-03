# Frontend Documentation

The frontend of TNHComfy (`tnhcomfy-frontend`) is built with **React** and **Vite**, focusing on speed, modularity, and a modern developer experience.

## Key Technologies
- **React:** Component-based UI rendering.
- **Vite:** Extremely fast local development server and bundler.
- **Zustand:** Client-side state management (e.g., UI state, form inputs, WebSocket integration).
- **React Query:** Server data fetching and caching (e.g., fetching jobs, models, configurations).
- **Lucide React:** Icon library used throughout the UI.

## State Management Architecture
As outlined in the `STATE_MANAGEMENT.md`, the frontend strictly separates client state from server state:

### 1. Zustand (Client State)
Zustand is used for things that don't need a server round-trip or are driven by real-time events.
- **UI State:** Modal states, active tabs, sidebar toggles.
- **Form State:** Draft inputs, temporary selections before submission.
- **WebSocket State:** Real-time job updates via `jobStore`.

### 2. React Query (Server State)
React Query is used exclusively for fetching, caching, synchronizing, and updating server state.
- **HTTP Data Fetching:** GET requests to API endpoints.
- **Server State Caching:** Auto-caching with configurable stale times.
- **Mutations:** POST/PUT/DELETE operations with automatic cache invalidation.

## Core Features
- **Job Tracking:** Real-time job status updates (pending, processing, completed, failed) via WebSockets.
- **Image Gallery:** Visual display of generated images fetched from the backend.
- **Generation Parameters:** Interfaces for adjusting prompts, negative prompts, steps, CFG scale, models, and LoRAs.
- **Optimistic Updates:** Immediate UI feedback for actions like deleting a job before the server confirms.

## Development Setup
1. Ensure `node` and `pnpm` are installed. (The repository strictly mandates using `pnpm`).
2. Navigate to `frontend_v2`:
   ```bash
   cd frontend_v2
   pnpm install
   ```
3. Start the development server:
   ```bash
   pnpm dev
   ```

## Styling
The frontend likely uses standard CSS/SCSS or a utility-first framework like Tailwind CSS (check `package.json` for specific dependencies). It ensures responsive design for different screen sizes.
