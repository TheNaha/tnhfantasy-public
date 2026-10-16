import { api } from './index';

const BASE = '/api/settings';

/**
 * Every read takes a trailing `options` and forwards it to the client, so a
 * React Query `queryFn` can pass the `AbortSignal` from its context.
 */
export const settingsApi = {
    get: (options = {}) => api.get(BASE, options),
    update: (data) => api.put(BASE, data),

    // Machine-readable documentation of config.json: per-field type, bounds,
    // default, env-var override and restart requirement. The Settings page
    // reads it to label its controls from the same source the API validates
    // against, instead of hardcoding ranges that can drift.
    getSchema: (options = {}) => api.get(`${BASE}/schema`, options),

    // Restores config.json to DEFAULT_CONFIG on the server. "Reset All" used to
    // clear only this browser's localStorage, so it never touched the backend
    // values the job runner actually reads.
    reset: () => api.post(`${BASE}/reset`),

    getSystemPrompts: (options = {}) => api.get(`${BASE}/system-prompts`, options),
    updateSystemPrompts: (data) => api.put(`${BASE}/system-prompts`, data),

    getBranding: (options = {}) => api.get(`${BASE}/branding`, options),
    updateBranding: (data) => api.post(`${BASE}/branding`, data),

    getFavorites: (options = {}) => api.get(`${BASE}/favorites`, options),
    updateFavorites: (favorites) => api.post(`${BASE}/favorites`, { favorites }),

    getSchedulerStatus: (options = {}) => api.get(`${BASE}/scheduler`, options),
    reconcileChatReplies: (params = {}) => api.post('/api/jobs/reconcile-chat-replies', null, { params }),
};

export const TTS_ENABLE_PAYLOAD = { ai: { ttsEnabled: true } };
