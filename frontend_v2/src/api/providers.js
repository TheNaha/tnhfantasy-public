/**
 * providers.js - Provider management API helpers
 *
 * A "provider" is a serverless compute backend (e.g. Modal, Beam) that runs
 * ComfyUI inside a container.  Multiple providers can be configured, and the
 * load balancer routes jobs between them.
 *
 * Container lifecycle (start / stop / restart / logs) is also managed here.
 * Modal-specific deployment operations use dedicated endpoints.
 */

import api from './client';

export const providersApi = {
    /** Fetch all configured providers. */
    list: () => api.get('/api/providers'),

    /**
     * Get a single provider by its unique ID.
     * @param {string} providerId - e.g. "modal-primary"
     */
    get: (providerId) => api.get(`/api/providers/${providerId}`),

    /**
     * Register a new provider.
     * @param {object} config - Provider configuration including `id`, `type`,
     *   `credentials`, and `config` fields.
     */
    create: (config) => api.post('/api/providers', config),

    /**
     * Partially update a provider's configuration.
     * @param {string} providerId - Provider to update.
     * @param {object} updates    - Fields to change (only supplied fields are modified).
     */
    update: (providerId, updates) => api.patch(`/api/providers/${providerId}`, updates),

    /**
     * Delete a provider and cascade-remove all its model status records.
     * @param {string} providerId - Provider to remove.
     */
    delete: (providerId) => api.delete(`/api/providers/${providerId}`),

    // -------------------------------------------------------------------------
    // Load Balancing
    // -------------------------------------------------------------------------

    /** Get the current load balancing strategy configuration. */
    getLoadBalancing: () => api.get('/api/providers/load-balancing'),

    /**
     * Update the load balancing strategy.
     * @param {object} config - e.g. { strategy: 'least-connections' }
     */
    updateLoadBalancing: (config) => api.put('/api/providers/load-balancing', config),

    /**
     * Trigger a full model reconciliation for a single provider.
     * Reconciliation compares what models the provider has on disk against the
     * database and downloads/deletes as needed.
     * @param {string} providerId
     */
    reconcile: (providerId) => api.post(`/api/providers/${providerId}/reconcile`),

    /** Get canonical status-card payloads for all providers. */
    getStatusCards: () => api.get('/api/providers/status-cards'),

    /** Get canonical status-card payload for one provider. */
    getStatusCard: (providerId) => api.get(`/api/providers/${providerId}/status-card`),

    /** Backward-compatible alias for single-provider status-card payload. */
    getStatus: (providerId) => api.get(`/api/providers/${providerId}/status-card`),

    // Aliases kept for backward compatibility with older call-sites
    getLoadBalancerConfig: () => api.get('/api/providers/config/load-balancing'),
    updateLoadBalancerConfig: (config) => api.put('/api/providers/load-balancing', config),

    // -------------------------------------------------------------------------
    // Container management
    // -------------------------------------------------------------------------

    /** Get the running/stopped status of a single provider's container. */
    getContainerStatus: (providerId) => api.get(`/api/providers/${providerId}/container/status`),

    /** Get container statuses for all providers in a single request. */
    getAllContainerStatuses: () => api.get('/api/providers/containers/status'),

    /** Start the Docker/Podman container for a provider. */
    startContainer: (providerId) => api.post(`/api/providers/${providerId}/container/start`),

    /** Stop the container for a provider. */
    stopContainer: (providerId) => api.post(`/api/providers/${providerId}/container/stop`),

    /** Restart the container for a provider (stop then start). */
    restartContainer: (providerId) => api.post(`/api/providers/${providerId}/container/restart`),

    /** Tail recent container logs (useful for debugging startup failures). */
    getContainerLogs: (providerId, tail) => api.get(
        `/api/providers/${providerId}/container/logs${tail ? `?tail=${tail}` : ''}`
    ),

    /** Read current model reconciliation status for a provider. */
    getReconciliationStatus: (providerId) => api.get(`/api/providers/${providerId}/reconciliation-status`),

    /** Clear persisted provider model sync status to force a clean reconciliation pass. */
    resetModelStatus: (providerId) => api.delete(`/api/v2/models/providers/${providerId}/reset-status`),

    /** Clean orphaned provider state and stale downloading entries. */
    cleanupState: () => api.post('/api/providers/state/cleanup'),

    // -------------------------------------------------------------------------
    // Modal-specific operations
    // -------------------------------------------------------------------------

    /**
     * Deploy the latest provider app from the backend orchestrator.
     * Beam runs three deploy steps: comfy_gpu, comfy_storage, and comfy_download.
     */
    deploy: (providerId) => api.post(`/api/providers/${providerId}/deploy`),

    /**
     * Run initial Modal setup (create volumes, upload base files, etc.).
     * Only needed once when a Modal provider is first configured.
     */
    setup: (providerId) => api.post(`/api/providers/${providerId}/setup`),
};

export default providersApi;
