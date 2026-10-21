/**
 * generate.js - Image generation API helpers
 *
 * Provides thin wrappers around the backend `/api/generate` endpoints.
 * For job lifecycle management (status, cancel, retry) see `jobs.js`.
 * For WebSocket-based real-time progress updates see `websocket.js`.
 */

import api, { createIdempotencyKey } from './client';

/**
 * The two request shapes the backend understands.
 *
 * The backend honours `kind` STRICTLY (`backend_v2/api/routes/generation.py`):
 * `kind == "guided"` compiles `request.options` into a ComfyUI graph, and
 * anything else compiles `request.workflow` as the graph.
 */
export const GUIDED = 'guided';
export const GRAPH = 'graph';

/**
 * The kind of a request.
 *
 * It is DECLARED, never inferred.
 *
 * It used to be inferred from the shape of the argument: an object with a
 * `mode` or a `prompt` key was read as options, and anything else as a
 * workflow. That inference was wrong for a hand-written ComfyUI graph in
 * API format - `{"prompt": {...}, "extra_data": {...}}` - whose top-level
 * `prompt` key made it look like options, so it was routed to `options` and
 * rejected by the option schema. The same misroute sent the graph to
 * `jobsApi.validate` as `options`, where the backend tried to compile it and
 * answered 422.
 *
 * So the kind comes from the caller, in one of two ways:
 *
 *   1. `options.kind` on the call itself - the explicit form.
 *   2. `payload.kind` on the payload - what the shared builder puts on the
 *      options it produces, so a caller that only has the payload still
 *      states which shape it is.
 *
 * With neither, the request is a GRAPH. That is the strict path: the backend
 * refuses a graph it cannot compile, rather than silently compiling a
 * request as options and sending the wrong thing to the provider.
 */
export function resolveGenerationKind(payload, explicitKind) {
    if (explicitKind === GUIDED || explicitKind === GRAPH) {
        return explicitKind;
    }
    const declared = payload && typeof payload === 'object' ? payload.kind : null;
    if (declared === GUIDED || declared === GRAPH) {
        return declared;
    }
    return GRAPH;
}

/**
 * The payload without its `kind` marker.
 *
 * The marker is a frontend-side contract, not a generator option: the
 * backend's `GeneratorOptions` ignores unknown keys, but the request body
 * should not carry a field the backend does not read.
 */
export function stripGenerationKind(payload) {
    if (!payload || typeof payload !== 'object') return payload;
    if (!Object.prototype.hasOwnProperty.call(payload, 'kind')) return payload;
    const { kind: _kind, ...rest } = payload;
    return rest;
}

export const generateApi = {
    /**
     * Submit a generation request.
     *
     * @param {object} payload - `{kind, options}` or `{kind, workflow}`.
     * @param {object} [params]  - Additional metadata to store with the job.
     * @param {object} [options]  - `{idempotencyKey, preferredProviderId}`.
     * @returns {Promise<{job: object}>} Newly created job record.
     */
    submit: (payload, params = {}, options = {}) => {
        const metadata = params?.metadata ?? params ?? {};
        const body = { ...payload, metadata };
        if (options.preferredProviderId) {
            body.preferred_provider_id = options.preferredProviderId;
        }
        return api.post('/api/generate', body, {
            idempotencyKey: options.idempotencyKey || createIdempotencyKey('generate-workflow'),
        });
    },

    /**
     * Submit a generation request, saying which of the two shapes it is.
     *
     *   - `guided` - the backend compiles the options into a ComfyUI graph.
     *   - `graph` - the caller compiled the graph and sends it whole.
     *
     * @param {object} payload - The options (guided) or the graph (graph).
     * @param {object} [params]  - Additional metadata to store with the job.
     * @param {object} [options]  - `{kind, idempotencyKey, preferredProviderId}`.
     * @returns {Promise<{job: object}>} Newly created job record.
     */
    workflow: (payload, params = {}, options = {}) => {
        const kind = resolveGenerationKind(payload, options.kind);
        const body = kind === GUIDED
            ? { kind, options: stripGenerationKind(payload) }
            : { kind, workflow: stripGenerationKind(payload) };
        return generateApi.submit(body, params, options);
    },

    /**
     * Submit multiple workflows in a single batch request.
     *
     * @param {Array<object>} workflows - Array of workflow entries (compiled graph,
     *   {workflow, options, metadata}, or bare generator options).
     * @param {object} [options]
     * @param {string} [options.idempotencyKey] - Re-uses the same batch response during the dedup window.
     * @param {string} [options.preferredProviderId] - Pin the jobs to one provider.
     * @returns {Promise<{jobs: object[], count: number}>} Created job records.
     */
    batch: (workflows, options = {}) =>
        api.post('/api/generate/batch', { workflows }, {
            idempotencyKey: options.idempotencyKey || createIdempotencyKey('generate-batch'),
        }),

};

export default generateApi;
