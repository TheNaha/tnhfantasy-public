/**
 * Models API
 * Model cache and download-related API calls.
 */

import api from './client';
import { getApiUrl } from './config';

export const modelsApi = {
    // List models by directory
    list: (directory) => api.get(`/api/models/cache?directory=${directory}`),

    // Get all model directories
    getDirectories: () => api.get('/api/models/directories'),

    // Download model - REMOVED: Use V2 API (/api/v2/models) for imports

    // Delete model
    delete: (directory, filename) =>
        api.delete(`/api/models/${directory}/${encodeURIComponent(filename)}`),

    // Search models (CivitAI/HuggingFace) - V2 API
    search: (query, source = 'civitai') =>
        api.get(`/api/v2/models/external/${source}?query=${encodeURIComponent(query)}`),

    // Get model metadata
    getMetadata: (modelId) => api.get(`/api/v2/models/${modelId}`),

    // Get preview image URL
    getPreviewUrl: (previewPath) => `${getApiUrl()}${previewPath}`,

    // V2 Model APIs
    // Delete model with provider sync (V2 - proper way)
    deleteV2: (modelId) => api.delete(`/api/v2/models/${modelId}`),
};

export default modelsApi;
