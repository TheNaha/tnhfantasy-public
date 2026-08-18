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
     * Submit a raw ComfyUI workflow for execution.
     *
     * Use this for advanced workflows that cannot be expressed through the
     * simple generator (e.g. custom node graphs, multi-step pipelines).
     *
     * @param {object} workflow  - ComfyUI workflow JSON (node graph format).
     * @param {object} [params]  - Additional metadata to store with the job.
     * @returns {Promise<{job: object}>} Newly created job record.
     */
    workflow: (workflowOrOptions, params = {}, options = {}) => {
        const metadata = params?.metadata ?? params ?? {};
        const payload = { metadata };
        if (workflowOrOptions?.mode !== undefined || workflowOrOptions?.prompt !== undefined) {
            payload.options = workflowOrOptions;
        } else {
            payload.workflow = workflowOrOptions;
        }
        return api.post('/api/generate', payload, {
            idempotencyKey: options.idempotencyKey || createIdempotencyKey('generate-workflow'),
        });
    },

    /**
     * Submit multiple workflows in a single batch request.
     *
     * @param {Array<object>} workflows - Array of workflow entries (compiled graph,
     *   {workflow, options, metadata}, or bare generator options).
     * @param {object} [options]
     * @param {string} [options.idempotencyKey] - Re-uses the same batch response during the dedup window.
     * @returns {Promise<{jobs: object[], count: number}>} Created job records.
     */
    batch: (workflows, options = {}) =>
        api.post('/api/generate/batch', { workflows }, {
            idempotencyKey: options.idempotencyKey || createIdempotencyKey('generate-batch'),
        }),

};

export default generateApi;
