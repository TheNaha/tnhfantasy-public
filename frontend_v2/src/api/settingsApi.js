import { api } from './index';

const BASE = '/api/settings';

export const settingsApi = {
    get: () => api.get(BASE),
    update: (data) => api.put(BASE, data),

    // Machine-readable documentation of config.json: per-field type, bounds,
    // default, env-var override and restart requirement. The Settings page
    // reads it to label its controls from the same source the API validates
    // against, instead of hardcoding ranges that can drift.
    getSchema: () => api.get(`${BASE}/schema`),

    // Restores config.json to DEFAULT_CONFIG on the server. "Reset All" used to
    // clear only this browser's localStorage, so it never touched the backend
    // values the job runner actually reads.
    reset: () => api.post(`${BASE}/reset`),

    getSystemPrompts: () => api.get(`${BASE}/system-prompts`),
    updateSystemPrompts: (data) => api.put(`${BASE}/system-prompts`, data),

    getBranding: () => api.get(`${BASE}/branding`),
    updateBranding: (data) => api.post(`${BASE}/branding`, data),

    getFavorites: () => api.get(`${BASE}/favorites`),
    updateFavorites: (favorites) => api.post(`${BASE}/favorites`, { favorites }),
};

export const TTS_ENABLE_PAYLOAD = { ai: { ttsEnabled: true } };
