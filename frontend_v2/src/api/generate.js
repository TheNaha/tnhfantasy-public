/**
 * generate.js - Image generation API helpers
 *
 * Provides thin wrappers around the backend `/api/generate` endpoints.
 * For job lifecycle management (status, cancel, retry) see `jobs.js`.
 * For WebSocket-based real-time progress updates see `websocket.js`.
 */

import api, { createIdempotencyKey } from './client';

const LEGACY_PRESET_STORAGE_KEY = 'comfy-generator-presets';

function readLegacyPresets() {
    if (typeof window === 'undefined') {
        return [];
    }

    try {
        const raw = window.localStorage.getItem(LEGACY_PRESET_STORAGE_KEY);
        if (!raw) {
            return [];
        }

        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function writeLegacyPresets(presets) {
    if (typeof window === 'undefined') {
        return;
    }

    window.localStorage.setItem(LEGACY_PRESET_STORAGE_KEY, JSON.stringify(presets));
}

export const generateApi = {
    /**
     * Submit a simple generation request.
     *
     * The backend converts the high-level params into a full ComfyUI workflow
     * internally, so callers do not need to manage the graph structure.
     *
     * @param {object} params - Generation parameters (prompt, model, steps, etc.)
     * @returns {Promise<{job: object}>} Newly created job record.
     */
    simple: (params, options = {}) => api.post('/api/generate', params, {
        idempotencyKey: options.idempotencyKey || createIdempotencyKey('generate'),
    }),

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

    /**
     * Fetch available generation presets from the server.
     *
     * Presets bundle common parameter sets (model + steps + sampler + …) into
     * a named configuration the user can apply with a single click.
     *
     * @returns {Promise<{presets: object[]}>}
     */
    getPresets: async () => ({ presets: readLegacyPresets() }),

    /**
     * Persist a new generation preset on the server.
     *
     * @param {object} preset - Preset object with `name`, `description`, and `data` fields.
     * @returns {Promise<object>} Saved preset record.
     */
    savePreset: async (preset) => {
        const presets = readLegacyPresets();
        const savedPreset = {
            ...preset,
            id: preset?.id ?? Date.now(),
        };
        presets.push(savedPreset);
        writeLegacyPresets(presets);
        return savedPreset;
    },
};

export default generateApi;
