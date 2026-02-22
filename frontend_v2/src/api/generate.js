/**
 * Generate API
 * Image generation API calls.
 */

import api from './client';

export const generateApi = {
    // Simple generation
    simple: (params) => api.post('/api/generate', params),

    // Advanced/workflow generation
    workflow: (workflow, params = {}) => api.post('/api/generate/workflow', {
        workflow,
        ...params,
    }),

    // Get generation presets
    getPresets: () => api.get('/api/generate/presets'),

    // Save preset
    savePreset: (preset) => api.post('/api/generate/presets', preset),
};

export default generateApi;
