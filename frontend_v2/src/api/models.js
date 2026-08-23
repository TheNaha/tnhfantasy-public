import api, { API_V2_BASE } from './client';

export const modelsApi = {
    // Delete model with provider sync (V2).
    deleteV2: (modelId) => api.delete(`${API_V2_BASE}/models/${modelId}`),
};

export default modelsApi;
