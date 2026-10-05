// Prompts API client - Server-side prompt library with FTS5 search

import api from './client';

const API_BASE = '/api/prompts';

/**
 * Every call takes a trailing `options` and forwards it to the client.
 *
 * That is how a React Query `queryFn` passes the `AbortSignal` from its context.
 * `listPrompts` in particular is the library's search — keyed per keystroke —
 * so without it every superseded query ran to completion and then raced the one
 * that superseded it into the cache.
 */

/**
 * List prompts with optional search and filtering
 */
export async function listPrompts({ q, category, favorite, limit = 100, offset = 0 } = {}, options = {}) {
    return api.get(API_BASE, { params: { q, category, favorite, limit, offset }, ...options });
}

/**
 * Get all categories
 */
export async function getCategories(options = {}) {
    return api.get(`${API_BASE}/categories`, options);
}

/**
 * Create a new prompt
 */
export async function createPrompt(data, options = {}) {
    return api.post(API_BASE, data, options);
}

/**
 * Update an existing prompt
 */
export async function updatePrompt(id, data, options = {}) {
    return api.put(`${API_BASE}/${id}`, data, options);
}

/**
 * Delete a prompt
 */
export async function deletePrompt(id, options = {}) {
    return api.delete(`${API_BASE}/${id}`, options);
}

/**
 * Increment usage count (call when prompt is used)
 */
export async function incrementUsage(id, options = {}) {
    return api.post(`${API_BASE}/${id}/use`, undefined, options);
}

/**
 * Bulk import prompts (for localStorage migration)
 */
export async function importPrompts(prompts, options = {}) {
    return api.post(`${API_BASE}/import`, { prompts }, options);
}

/**
 * Export all prompts
 */
export async function exportPrompts(options = {}) {
    return api.get(`${API_BASE}/export`, options);
}

/**
 * Enrich a prompt via the LLM magic-prompt endpoint
 */
export async function magicPrompt(prompt, options = {}) {
    return api.post(`${API_BASE}/magic`, { prompt }, options);
}

export default {
    listPrompts,
    getCategories,
    createPrompt,
    updatePrompt,
    deletePrompt,
    incrementUsage,
    importPrompts,
    exportPrompts,
    magicPrompt
};