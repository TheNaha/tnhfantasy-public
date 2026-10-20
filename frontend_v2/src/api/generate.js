/**
 * generate.js - Image generation API helpers
 *
 * Provides thin wrappers around the backend `/api/generate` endpoints.
 * For job lifecycle management (status, cancel, retry) see `jobs.js`.
 * For WebSocket-based real-time progress updates see `websocket.js`.
 */

import api, { createIdempotencyKey } from './client';

export const generateApi = {
    /**
     * Submit a generation request.
     *
     * `kind` says which of the two request shapes this is:
     *
     *   - `guided` - the backend compiles the options into a ComfyUI graph.
     *   - `graph` - the caller compiled the graph and sends it whole.
     *
     * It used to be inferred from the shape of the argument: an object with
     * a `mode` or a `prompt` key was read as options, and anything else as a
     * workflow. That inference was wrong for a hand-written ComfyUI graph
     * with a node keyed `prompt` or `mode` - it was routed to `options` and
     * rejected by the option schema - and it was a second, implicit copy of
     * the request contract. The backend takes the same `kind`, and omitting
     * it there still works.
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
     * Submit a raw ComfyUI workflow for execution.
     *
     * Use this for advanced workflows that cannot be expressed through the
     * simple generator (e.g. custom node graphs, multi-step pipelines).
     *
     * @param {object} workflow  - ComfyUI workflow JSON (node graph format).
     * @param {object} [params]  - Additional metadata to store with the job.
     * @param {object} [options]  - `{idempotencyKey, preferredProviderId}`.
     * @returns {Promise<{job: object}>} Newly created job record.
     */
    workflow: (workflowOrOptions, params = {}, options = {}) => {
        const isGuided =
            workflowOrOptions?.mode !== undefined || workflowOrOptions?.prompt !== undefined;
        return generateApi.submit(
            isGuided
                ? { kind: 'guided', options: workflowOrOptions }
                : { kind: 'graph', workflow: workflowOrOptions },
            params,
            options
        );
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
