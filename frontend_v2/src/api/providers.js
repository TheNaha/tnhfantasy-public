/**
 * providers.js - Provider management API helpers
 *
 * A "provider" is a compute backend (e.g. Modal, Beam, a local ComfyUI
 * instance, an LLM API) that executes jobs through an in-process engine in
 * the backend. Multiple providers can be configured, and the load balancer
 * routes jobs between them.
 */

import api, { API_V2_BASE } from './client';

const P = `${API_V2_BASE}/providers`;

// The collection routes are declared `@router.get("/")` / `@router.post("/")`,
// so their canonical path carries a trailing slash. Asking for the bare path made
// FastAPI answer `307 Temporary Redirect` and re-issue the request, doubling
// every call this client makes with them. `list` runs app-wide on every page
// load — the layout status dot mounts `useProvidersPageData` — so that was one
// wasted round trip per page navigation, twice over, plus a redirect body to
// parse and discard.
//
// A second constant rather than a slash on `P`, because every sibling call is
// `${P}/${id}` and that would become a double slash.
//
// Guarded by `src/test/apiPathInvariants.test.js`, which fails if any literal
// client path needs a redirect to resolve.
const P_COLLECTION = `${P}/`;

// Exported so the path-shape guard can name the exact string rather than
// re-deriving it and drifting.
export const COLLECTION_PATH = P_COLLECTION;

/**
 * Every read takes a trailing `options` and forwards it to the client, so a
 * React Query `queryFn` can pass the `AbortSignal` from its context. The
 * providers list is mounted app-wide (the layout polls it for the status dot),
 * so an unmounted subscriber leaving its request in flight was the common case,
 * not the exception.
 */
export const providersApi = {
    /** Fetch all configured providers. */
    list: (options = {}) => api.get(P_COLLECTION, options),

    /**
     * Register a new provider.
     * @param {object} config - Provider configuration including `id`, `type`,
     *   `credentials`, and `config` fields.
     */
    create: (config) => api.post(P_COLLECTION, config),

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

    // -------------------------------------------------------------------------
    // Engine operations
    // -------------------------------------------------------------------------

    /** Fetch live metrics for the provider's in-process engine. */
    getLiveMetrics: (providerId, options = {}) => api.get(`${P}/${providerId}/live-metrics`, options),

    /**
     * Run initial engine setup (create volumes, upload base files, etc.).
     * Only needed once when a Modal provider is first configured.
     */
    setup: (providerId) => api.post(`${P}/${providerId}/setup`),

    /** Fetch declarative schemas for all supported provider engines. */
    getSchemas: (options = {}) => api.get(`${P}/schemas`, options),

    /** Test connection and authentication for an unsaved engine configuration. */
    testConnection: (payload) => api.post(`${P}/test-connection`, payload),

    /** Test connection and health of an existing provider. */
    testProvider: (providerId) => api.post(`${P}/${providerId}/test`),

    /** Fetch live models or voices discovered upstream from the in-process engine. */
    getDiscoveredModels: (providerId, options = {}) => api.get(`${P}/${providerId}/models/discovered`, options),

    /** Fetch deep real-time diagnostics and telemetry for a provider. */
    getDiagnostics: (providerId, options = {}) => api.get(`${P}/${providerId}/diagnostics`, options),
};

export default providersApi;
