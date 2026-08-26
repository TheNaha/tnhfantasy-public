import { api } from './index';

const BASE = '/api/settings';

export const settingsApi = {
    get: () => api.get(BASE),
    update: (data) => api.put(BASE, data),

    getSystemPrompts: () => api.get(`${BASE}/system-prompts`),
    updateSystemPrompts: (data) => api.put(`${BASE}/system-prompts`, data),

    getBranding: () => api.get(`${BASE}/branding`),
    updateBranding: (data) => api.post(`${BASE}/branding`, data),

    getFavorites: () => api.get(`${BASE}/favorites`),
    updateFavorites: (favorites) => api.post(`${BASE}/favorites`, { favorites }),
};

export const TTS_ENABLE_PAYLOAD = { ai: { ttsEnabled: true } };
