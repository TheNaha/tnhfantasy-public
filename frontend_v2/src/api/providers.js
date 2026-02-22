/**
 * Providers API
 * Provider management API calls.
 */

import api from './client';

export const providersApi = {
    // List all providers
    list: () => api.get('/api/providers'),

    // Get single provider
    get: (providerId) => api.get(`/api/providers/${providerId}`),

    // Create provider
    create: (config) => api.post('/api/providers', config),

    // Update provider
    update: (providerId, updates) => api.patch(`/api/providers/${providerId}`, updates),

    // Delete provider
    delete: (providerId) => api.delete(`/api/providers/${providerId}`),

    // Get load balancing config
    getLoadBalancing: () => api.get('/api/providers/load-balancing'),

    // Update load balancing config
    updateLoadBalancing: (config) => api.put('/api/providers/load-balancing', config),

    // Reconcile models for provider
    reconcile: (providerId) => api.post(`/api/providers/${providerId}/reconcile`),

    // Get provider status/health
    getStatus: (providerId) => api.get(`/api/providers/${providerId}/status`),

    // Alias for backward compatibility (uses backend_v2 path)
    getLoadBalancerConfig: () => api.get('/api/providers/config/load-balancing'),

    // Alias for Providers.jsx compatibility
    updateLoadBalancerConfig: (config) => api.put('/api/providers/load-balancing', config),

    // Container management
    getContainerStatus: (providerId) => api.get(`/api/providers/${providerId}/container/status`),
    getAllContainerStatuses: () => api.get('/api/providers/containers/status'),
    startContainer: (providerId) => api.post(`/api/providers/${providerId}/container/start`),
    stopContainer: (providerId) => api.post(`/api/providers/${providerId}/container/stop`),
    restartContainer: (providerId) => api.post(`/api/providers/${providerId}/container/restart`),
    getContainerLogs: (providerId) => api.get(`/api/providers/${providerId}/container/logs`),

    // Modal-specific operations
    deploy: (providerId) => api.post(`/api/providers/${providerId}/deploy`),
    setup: (providerId) => api.post(`/api/providers/${providerId}/setup`),
};

export default providersApi;
