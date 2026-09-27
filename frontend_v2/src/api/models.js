/**
 * models.js - Model metadata API helpers (V2)
 *
 * The tag endpoints are the write side of a table that used to be
 * populate-only. Every `ModelTag` row in the app came from a CivitAI resync,
 * and a resync deletes its own rows wholesale — so there was nowhere to record
 * a tag the *user* cared about (this LoRA is the one for Character X, that one
 * is the kneeling-hands-up pose). Those models were unfindable by the one
 * thing the tag filter searches.
 *
 * Provenance is therefore load-bearing, not decoration: CivitAI owns the rows
 * it scraped, the user owns the rows they typed, and the backend refuses to
 * delete a CivitAI row because the next resync would recreate it. Hence the
 * `source` on every listed tag, and hence `removeTag` rejecting with a 404
 * `ApiError` (`error.status === 404`) that the caller must report rather than
 * swallow — a delete that "succeeded" while the tag is still there is worse
 * than one that visibly failed.
 */

import api, { API_V2_BASE } from './client';

const M = `${API_V2_BASE}/models`;
const MAINTENANCE = `${M}/maintenance`;

/** A user-typed tag is arbitrary text, so the path segment must be escaped. */
const tagPath = (modelId, tag) =>
    `${MAINTENANCE}/${encodeURIComponent(modelId)}/tags/${encodeURIComponent(tag)}`;

export const modelsApi = {
    // Delete model with provider sync (V2).
    deleteV2: (modelId) => api.delete(`${M}/${modelId}`),

    /**
     * Every tag on a model, with the provenance that decides who may remove it.
     * @param {string} modelId
     * @returns {Promise<{tags: Array<{tag: string, source: 'civitai'|'user'}>}>}
     */
    listTags: (modelId) => api.get(`${MAINTENANCE}/${encodeURIComponent(modelId)}/tags`),

    /**
     * Attach a `source='user'` tag.
     *
     * Idempotent by design: a tag that is already on the model — of either
     * source — comes back as `created: false` rather than a 409, because
     * (model_id, tag) is unique and "you already said that" is not an error.
     * @param {string} modelId
     * @param {string} tag
     * @returns {Promise<{tag: string, source: string, created: boolean}>}
     */
    addTag: (modelId, tag) => api.post(`${MAINTENANCE}/${encodeURIComponent(modelId)}/tags`, { tag }),

    /**
     * Remove a `source='user'` tag.
     *
     * Rejects with `ApiError` status 404 when there is no such *user* tag —
     * i.e. the tag is CivitAI-owned, or is already gone. The 404 is a refusal,
     * not a transport failure, and is the caller's job to explain.
     * @param {string} modelId
     * @param {string} tag
     */
    removeTag: (modelId, tag) => api.delete(tagPath(modelId, tag)),
};

export default modelsApi;
