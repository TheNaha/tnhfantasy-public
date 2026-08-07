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
    workflow: (workflow, params = {}, options = {}) => {
        const metadata = params?.metadata ?? params ?? {};
        return api.post('/api/generate', {
            workflow,
            metadata,
        }, {
            idempotencyKey: options.idempotencyKey || createIdempotencyKey('generate-workflow'),
        });
    },

};

export default generateApi;
