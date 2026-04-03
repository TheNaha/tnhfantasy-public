import api from './client';

export const modelsApi = {
    // Delete model with provider sync (V2).
    deleteV2: (modelId) => api.delete(`/api/v2/models/${modelId}`),
};

export default modelsApi;
