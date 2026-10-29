/**
 * providers.js - Provider management API helpers
 *
 * A "provider" is a compute backend (e.g. Modal, Beam, a local ComfyUI
 * instance, an LLM API) that executes jobs through an in-process engine in
 * the backend. Multiple providers can be configured, and the load balancer
 * routes jobs between them.
 */

import api, { API_V2_BASE, getBaseUrl } from './client';

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

    /**
     * Trigger targeted model download for a single provider.
     * @param {string} providerId
     * @param {object} payload - { file_ids: string[], model_ids?: string[] }
     */
    downloadModels: (providerId, { file_ids = [], model_ids = [] } = {}) =>
        api.post(`${P}/${providerId}/models/download`, { file_ids, model_ids }),

    /**
     * Fetch sync manifest for a provider to inspect model statuses and missing items.
     * @param {string} providerId
     */
    getSyncManifest: (providerId = '', options = {}) => {
        const url = providerId
            ? `${API_V2_BASE}/models/providers/${providerId}/sync-manifest`
            : `${API_V2_BASE}/models/sync-manifest`;
        return api.get(url, options);
    },

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

    /** Purge GPU VRAM and reset model caching on remote worker engine. */
    freeVram: (providerId) => api.post(`${P}/${providerId}/free-vram`),

    /** Shut down a provider's worker (waits for active jobs first). */
    shutdown: (providerId) => api.post(`${P}/${providerId}/shutdown`),

    /** Fetch live models or voices discovered upstream from the in-process engine. */
    getDiscoveredModels: (providerId, options = {}) => api.get(`${P}/${providerId}/models/discovered`, options),

    /** Fetch deep real-time diagnostics and telemetry for a provider. */
    getDiagnostics: (providerId, options = {}) => api.get(`${P}/${providerId}/diagnostics`, options),

    /** Fetch activity, deployment logs, recent job errors, and probe state for a provider. */
    getLogs: (providerId, options = {}) => api.get(`${P}/${providerId}/logs`, options),

    // -------------------------------------------------------------------------
    // Credentials — write-only.
    //
    // There is no "read the token back" call here and there is not going to be
    // one: `getCredentials` returns which keys are SET plus a masked hint, never
    // a value. The form therefore cannot be pre-filled from the server, which
    // is the point — a masked value that round-trips into an input is a value
    // that has already left the backend.
    // -------------------------------------------------------------------------

    /** Which credentials are set, and whether the column is encrypted. */
    getCredentials: (providerId, options = {}) =>
        api.get(`${P}/${providerId}/credentials`, options),

    /** Merge (or, with `replace`, swap) credential values. */
    setCredentials: (providerId, credentials, { replace = false } = {}) =>
        api.put(`${P}/${providerId}/credentials`, { credentials, replace }),

    /** Remove one credential by name. */
    deleteCredential: (providerId, key) =>
        api.delete(`${P}/${providerId}/credentials/${encodeURIComponent(key)}`),

    // -------------------------------------------------------------------------
    // Deploy
    // -------------------------------------------------------------------------

    /** What can be deployed from the backend process, and whether it can see the script. */
    getDeployTargets: (options = {}) => api.get(`${P}/deploy/targets`, options),

    /**
     * Deploy a cloud worker by shelling out to `scripts/deploy.sh`.
     * Long-running and synchronous: the response carries the script's captured
     * output, so callers should show a progress state rather than assume a
     * quick reply.
     */
    deploy: (payload) => api.post(`${P}/deploy`, payload),

    /**
     * Deploy a cloud worker with live NDJSON output streaming.
     * @param {Object} payload - { target, dry_run, provider_id, timeout }
     * @param {Object} callbacks - { onChunk, onFinish, onError, signal }
     */
    deployStream: async (payload, { onChunk, onFinish, onError, signal } = {}) => {
        try {
            const url = `${getBaseUrl()}${P}/deploy`;
            const res = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ ...payload, stream: true }),
                signal,
            });

            if (!res.ok) {
                const errorData = await res.json().catch(() => ({}));
                const msg = errorData.detail || errorData.message || `Deploy failed with HTTP ${res.status}`;
                if (onError) onError(new Error(msg));
                return;
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // keep remainder

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed) continue;
                    try {
                        const parsed = JSON.parse(trimmed);
                        if (parsed.type === 'chunk') {
                            if (onChunk) onChunk(parsed.chunk);
                        } else if (parsed.type === 'finish') {
                            if (onFinish) onFinish(parsed.result);
                        } else if (parsed.type === 'error') {
                            if (onError) onError(new Error(parsed.error));
                        }
                    } catch {
                        if (onChunk) onChunk(trimmed + '\n');
                    }
                }
            }

            if (buffer.trim()) {
                try {
                    const parsed = JSON.parse(buffer.trim());
                    if (parsed.type === 'chunk' && onChunk) onChunk(parsed.chunk);
                    else if (parsed.type === 'finish' && onFinish) onFinish(parsed.result);
                    else if (parsed.type === 'error' && onError) onError(new Error(parsed.error));
                } catch {
                    if (onChunk) onChunk(buffer.trim() + '\n');
                }
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            if (onError) onError(err);
        }
    },
};

export default providersApi;
