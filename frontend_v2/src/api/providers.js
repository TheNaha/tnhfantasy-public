/**
 * providers.js - Provider management API helpers
 *
 * A "provider" is a serverless compute backend (e.g. Modal, Beam) that runs
 * ComfyUI inside a container.  Multiple providers can be configured, and the
 * load balancer routes jobs between them.
 */

import api, { API_V2_BASE } from './client';

const P = `${API_V2_BASE}/providers`;

/**
 * Every read takes a trailing `options` and forwards it to the client, so a
 * React Query `queryFn` can pass the `AbortSignal` from its context. The
 * providers list is mounted app-wide (the layout polls it for the status dot),
 * so an unmounted subscriber leaving its request in flight was the common case,
 * not the exception.
 */
export const providersApi = {
    /** Fetch all configured providers. */
    list: (options = {}) => api.get(P, options),

    /**
     * Register a new provider.
     * @param {object} config - Provider configuration including `id`, `type`,
     *   `credentials`, and `config` fields.
     */
    create: (config) => api.post(P, config),

    /**
     * Partially update a provider's configuration.
     * @param {string} providerId - Provider to update.
     * @param {object} updates    - Fields to change (only supplied fields are modified).
     */
    update: (providerId, updates) => api.patch(`${P}/${providerId}`, updates),

    /**
     * Delete a provider and cascade-remove all its model status records.
     * @param {string} providerId - Provider to remove.
     */
    delete: (providerId) => api.delete(`${P}/${providerId}`),

    // -------------------------------------------------------------------------
    // Load Balancing
    // -------------------------------------------------------------------------

    /**
     * Get the current load balancing strategy configuration.
     * Canonical endpoint: /api/v2/providers/config/load-balancing
     */
    getLoadBalancing: (options = {}) => api.get(`${P}/config/load-balancing`, options),

    /**
     * Update the load balancing strategy.
     * @param {object} config - e.g. { strategy: 'least-connections' }
     */
    updateLoadBalancing: (config) => api.put(`${P}/config/load-balancing`, config),

    /**
     * Trigger a full model reconciliation for a single provider.
     * Reconciliation compares what models the provider has on disk against the
     * database and downloads/deletes as needed.
     * @param {string} providerId
     */
    reconcile: (providerId) => api.post(`${P}/${providerId}/reconcile?force=true`),
    quickSync: (providerId) => api.post(`${P}/${providerId}/reconcile?force=true&quick_sync=true`),

    /** Clear persisted provider model sync status to force a clean reconciliation pass. */
    resetModelStatus: (providerId) => api.delete(`${API_V2_BASE}/models/providers/${providerId}/reset-status`),

    /** Clean orphaned provider state and stale downloading entries. */
    cleanupState: () => api.post(`${P}/state/cleanup`),

    /**
     * Scan running containers (tnhcomfy-* naming) and register any that are
     * missing as providers. Also reports containers already known to the
     * backend. Safe to call any time; heartbeats self-register compose workers.
     */
    detect: () => api.post(`${P}/detect`),

    /** Ping enabled provider containers to wake them from cold start. */
    wake: () => api.post(`${P}/wake`),

    // -------------------------------------------------------------------------
    // Modal-specific operations
    // -------------------------------------------------------------------------

    /** Fetch live metrics directly from the remote provider container. */
    getLiveMetrics: (providerId, options = {}) => api.get(`${P}/${providerId}/live-metrics`, options),

    /** Fetch container logs for the provider. */
    getLogs: (providerId, options = {}) => api.get(`${P}/${providerId}/logs`, options),

    /**
     * Deploy the latest provider app from the backend orchestrator.
     * Beam runs three deploy steps: comfy_gpu, comfy_storage, and comfy_download.
     */
    deploy: (providerId) => api.post(`${P}/${providerId}/deploy`),

    /**
     * Run initial Modal setup (create volumes, upload base files, etc.).
     * Only needed once when a Modal provider is first configured.
     */
    setup: (providerId) => api.post(`${P}/${providerId}/setup`),
};

export default providersApi;
