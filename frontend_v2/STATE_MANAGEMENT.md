# Frontend State Management Guide

## Overview

This project uses **Zustand** for client-side UI/realtime state and **React Query** for canonical HTTP-backed server state.

## Architecture

```
┌─────────────────────────────────────────────┐
│           APPLICATION STATE                 │
├─────────────────────────────────────────────┤
│                                             │
│  ┌──────────────┐      ┌─────────────────┐ │
│  │   Zustand    │      │  React Query    │ │
│  │ (Client State)│      │ (Server Cache)  │ │
│  └──────────────┘      └─────────────────┘ │
│       │                       │             │
│       │                       │             │
│       ▼                       ▼             │
│  UI State, Forms      HTTP Requests,       │
│  Selections, etc.     Background Refetch   │
│                                             │
└─────────────────────────────────────────────┘
```

## State Responsibility

### Zustand - Client State

Use Zustand for:

- **UI State**: Modal open/closed, active tabs, sidebar collapsed
- **Form State**: Draft inputs, temporary selections
- **Client-only Data**: Theme preferences, UI layout settings
- **Realtime Process State**: Real-time job updates via `jobStore`
- **Collection UI Cache**: Active collection selection plus lazily hydrated collection images in `useStore`

**Example Stores:**

- `settingsStore.js` - User preferences (branding, theme)
- `useStore.js` - Gallery UI state, favorites, and active collection cache

### React Query - Server Data

Use React Query for:

- **HTTP Data Fetching**: GET requests to API endpoints
- **Server State Caching**: Auto-cache with 5min stale time
- **Background Refetching**: Keep data fresh on window focus
- **Mutations**: POST/PUT/DELETE with automatic cache invalidation
- **Shared Provider Cache**: Provider records from `/api/providers` via `useProvidersPageData`

**Example Usage:**

```javascript
const { data: models } = useQuery({
  queryKey: ["models", "v2"],
  queryFn: () => modelsApi.listV2(),
});
```

## Patterns

### 1. Optimistic Updates (Zustand)

For immediate UI feedback before server confirmation:

```javascript
// In jobStore.js
deleteJob: async (jobId) => {
  const previousJobs = get().jobs;

  // Optimistic: remove immediately
  set((state) => ({
    jobs: state.jobs.filter((j) => j.id !== jobId),
  }));

  try {
    await jobsApi.delete(jobId);
  } catch (error) {
    // Rollback on failure
    set({ jobs: previousJobs });
    throw error;
  }
};
```

### 2. WebSocket Integration (Zustand)

Real-time updates via WebSocket are handled in Zustand:

```javascript
// In src/hooks/useJobsRealtime.jsx
const { lastCompletedJob } = useJobsRealtime();
```

### 3. Server Data with React Query

Fetch and cache server data:

```javascript
const { providers, refreshAll } = useProvidersPageData();
```

### 4. Mutations with Cache Invalidation

```javascript
const mutation = useMutation({
  mutationFn: (newProvider) =>
    fetch("/api/providers", {
      method: "POST",
      body: JSON.stringify(newProvider),
    }),
  onSuccess: () => {
    // Invalidate and refetch
    queryClient.invalidateQueries(["providers"]);
  },
});
```

## Store Organization



### settingsStore.js

- **Purpose**: User preferences and branding
- **State**: `branding`, `theme`, `defaults`
- **Methods**: `updateBranding()`, `resetToDefaults()`

### useStore.js

- **Purpose**: Gallery UI state
- **State**: `viewMode`, `favorites[]`, `activeCollection`
- **Methods**: `setViewMode()`, `toggleFavorite()`, `setActiveCollection()`

### useProvidersPageData.js

- **Purpose**: Canonical provider server-state hook
- **State**: React Query cache for provider records and load-balancer config
- **Realtime**: Shares one websocket bridge between layout and providers page consumers

## Best Practices

✅ **DO:**

- Use Zustand for UI state and WebSocket data
- Use React Query for HTTP requests
- Implement optimistic updates for better UX
- Subscribe to state changes with `useStore` hook
- Bootstrap collections from the backend at app startup and lazy-load collection images only when a collection is opened
- Treat `useProvidersPageData` as the single source of truth for provider server data

❌ **DON'T:**

- Store server data in Zustand (use React Query)
- Duplicate state between Zustand and React Query
- Manually manage HTTP cache (let React Query handle it)
- Reintroduce parallel provider caches or standalone provider websocket hooks

## Migration Notes

Collections were migrated from a local-only model to a server-backed model with lazy image hydration. Provider server data was also consolidated onto `useProvidersPageData`, so shared UI like `Layout` and `Providers` consume the same React Query cache and websocket bridge.
