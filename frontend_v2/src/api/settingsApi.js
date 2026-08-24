import { api } from './index';

const BASE = '/api/settings';

export const settingsApi = {
    get: () => api.get(BASE),
    update: (data) => api.put(BASE, data),
    getSchema: () => api.get(`${BASE}/schema`),
    reset: () => api.post(`${BASE}/reset`),

    getSystemPrompts: () => api.get(`${BASE}/system-prompts`),
    updateSystemPrompts: (data) => api.put(`${BASE}/system-prompts`, data),

    getBranding: () => api.get(`${BASE}/branding`),
    updateBranding: (data) => api.post(`${BASE}/branding`, data),

    getFavorites: () => api.get(`${BASE}/favorites`),
    updateFavorites: (favorites) => api.post(`${BASE}/favorites`, { favorites }),

    getSession: () => api.get(`${BASE}/session`),
    updateSession: (data) => api.post(`${BASE}/session`, data),

    getPresets: () => api.get(`${BASE}/presets`),
};

export const TTS_ENABLE_PAYLOAD = { ai: { ttsEnabled: true } };
