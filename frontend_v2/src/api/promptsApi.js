// Prompts API client - Server-side prompt library with FTS5 search

import api from './client';

const API_BASE = '/api/prompts';

/**
 * List prompts with optional search and filtering
 */
export async function listPrompts({ q, category, favorite, limit = 100, offset = 0 } = {}) {
    return api.get(API_BASE, { params: { q, category, favorite, limit, offset } });
}

/**
 * Get all categories
 */
export async function getCategories() {
    return api.get(`${API_BASE}/categories`);
}

/**
 * Get a single prompt by ID
 */
export async function getPrompt(id) {
    return api.get(`${API_BASE}/${id}`);
}

/**
 * Create a new prompt
 */
export async function createPrompt(data) {
    return api.post(API_BASE, data);
}

/**
 * Update an existing prompt
 */
export async function updatePrompt(id, data) {
    return api.put(`${API_BASE}/${id}`, data);
}

/**
 * Delete a prompt
 */
export async function deletePrompt(id) {
    return api.delete(`${API_BASE}/${id}`);
}

/**
 * Increment usage count (call when prompt is used)
 */
export async function incrementUsage(id) {
    return api.post(`${API_BASE}/${id}/use`);
}

/**
 * Bulk import prompts (for localStorage migration)
 */
export async function importPrompts(prompts) {
    return api.post(`${API_BASE}/import`, { prompts });
}

/**
 * Export all prompts
 */
export async function exportPrompts() {
    return api.get(`${API_BASE}/export`);
}

export default {
    listPrompts,
    getCategories,
    getPrompt,
    createPrompt,
    updatePrompt,
    deletePrompt,
    incrementUsage,
    importPrompts,
    exportPrompts
};
