# Frontend State Management Guide

## Overview

This project uses **Zustand** for all client-side state management and **React Query** exclusively for server data fetching/caching.

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
- **WebSocket State**: Real-time job updates via `jobStore`

**Example Stores:**

- `jobStore.js` - Real-time job updates via WebSocket
- `settingsStore.js` - User preferences (branding, theme)

### React Query - Server Data

Use React Query for:

- **HTTP Data Fetching**: GET requests to API endpoints
- **Server State Caching**: Auto-cache with 5min stale time
- **Background Refetching**: Keep data fresh on window focus
- **Mutations**: POST/PUT/DELETE with automatic cache invalidation

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
// In jobStore.js
connect: async () => {
  await ws.connect();
  await ws.subscribe("job");

  ws.on("job.completed", (data) => {
    get()._processMessage(data); // Update store
  });
};
```

### 3. Server Data with React Query

Fetch and cache server data:

```javascript
const { data, isLoading, refetch } = useQuery({
  queryKey: ["providers"],
  queryFn: async () => {
    const response = await fetch("/api/providers");
    return response.json();
  },
  staleTime: 1000 * 60 * 5, // 5 minutes
});
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

### jobStore.js

- **Purpose**: Real-time job tracking via WebSocket
- **State**: `jobs[]`, `activeJobs[]`, `lastCompletedJob`
- **Methods**: `connect()`, `fetchJobs()`, `cancelJob()`, `deleteJob()`

### settingsStore.js

- **Purpose**: User preferences and branding
- **State**: `branding`, `theme`, `defaults`
- **Methods**: `updateBranding()`, `resetToDefaults()`

## Best Practices

✅ **DO:**

- Use Zustand for UI state and WebSocket data
- Use React Query for HTTP requests
- Implement optimistic updates for better UX
- Subscribe to state changes with `useStore` hook

❌ **DON'T:**

- Store server data in Zustand (use React Query)
- Duplicate state between Zustand and React Query
- Manually manage HTTP cache (let React Query handle it)

## Migration Notes

All client state has been unified to Zustand. React Query is now used exclusively for server data fetching and caching, not for state management.
