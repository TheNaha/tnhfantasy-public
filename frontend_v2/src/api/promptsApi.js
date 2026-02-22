// Prompts API client - Server-side prompt library with FTS5 search

const API_BASE = '/api/prompts';

/**
 * List prompts with optional search and filtering
 */
export async function listPrompts({ q, category, favorite, limit = 100, offset = 0 } = {}) {
    const params = new URLSearchParams();
    if (q) params.append('q', q);
    if (category) params.append('category', category);
    if (favorite !== undefined) params.append('favorite', favorite);
    params.append('limit', limit);
    params.append('offset', offset);

    const response = await fetch(`${API_BASE}?${params}`);
    if (!response.ok) throw new Error('Failed to fetch prompts');
    return response.json();
}

/**
 * Get all categories
 */
export async function getCategories() {
    const response = await fetch(`${API_BASE}/categories`);
    if (!response.ok) throw new Error('Failed to fetch categories');
    return response.json();
}

/**
 * Get favorite prompts
 */
export async function getFavorites(limit = 20) {
    const response = await fetch(`${API_BASE}/favorites?limit=${limit}`);
    if (!response.ok) throw new Error('Failed to fetch favorites');
    return response.json();
}

/**
 * Get most used prompts
 */
export async function getMostUsed(limit = 10) {
    const response = await fetch(`${API_BASE}/most-used?limit=${limit}`);
    if (!response.ok) throw new Error('Failed to fetch most used');
    return response.json();
}

/**
 * Get a single prompt by ID
 */
export async function getPrompt(id) {
    const response = await fetch(`${API_BASE}/${id}`);
    if (!response.ok) throw new Error('Prompt not found');
    return response.json();
}

/**
 * Create a new prompt
 */
export async function createPrompt(data) {
    const response = await fetch(API_BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error('Failed to create prompt');
    return response.json();
}

/**
 * Update an existing prompt
 */
export async function updatePrompt(id, data) {
    const response = await fetch(`${API_BASE}/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error('Failed to update prompt');
    return response.json();
}

/**
 * Delete a prompt
 */
export async function deletePrompt(id) {
    const response = await fetch(`${API_BASE}/${id}`, { method: 'DELETE' });
    if (!response.ok) throw new Error('Failed to delete prompt');
    return response.json();
}

/**
 * Increment usage count (call when prompt is used)
 */
export async function incrementUsage(id) {
    const response = await fetch(`${API_BASE}/${id}/use`, { method: 'POST' });
    if (!response.ok) throw new Error('Failed to increment usage');
    return response.json();
}

/**
 * Bulk import prompts (for localStorage migration)
 */
export async function importPrompts(prompts) {
    const response = await fetch(`${API_BASE}/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompts })
    });
    if (!response.ok) throw new Error('Failed to import prompts');
    return response.json();
}

/**
 * Export all prompts
 */
export async function exportPrompts() {
    const response = await fetch(`${API_BASE}/export`);
    if (!response.ok) throw new Error('Failed to export prompts');
    return response.json();
}

export default {
    listPrompts,
    getCategories,
    getFavorites,
    getMostUsed,
    getPrompt,
    createPrompt,
    updatePrompt,
    deletePrompt,
    incrementUsage,
    importPrompts,
    exportPrompts
};
