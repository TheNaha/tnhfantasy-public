// Collections API client - Server-side image collections

const API_BASE = '/api/collections';

/**
 * List all collections with image counts
 */
export async function listCollections() {
    const response = await fetch(API_BASE);
    if (!response.ok) throw new Error('Failed to fetch collections');
    return response.json();
}

/**
 * Get a single collection with its images
 */
export async function getCollection(id, includeImages = true) {
    const response = await fetch(`${API_BASE}/${id}?include_images=${includeImages}`);
    if (!response.ok) throw new Error('Collection not found');
    return response.json();
}

/**
 * Create a new collection
 */
export async function createCollection(data) {
    const response = await fetch(API_BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error('Failed to create collection');
    return response.json();
}

/**
 * Update a collection (name, color, description)
 */
export async function updateCollection(id, data) {
    const response = await fetch(`${API_BASE}/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error('Failed to update collection');
    return response.json();
}

/**
 * Delete a collection (images are NOT deleted)
 */
export async function deleteCollection(id) {
    const response = await fetch(`${API_BASE}/${id}`, { method: 'DELETE' });
    if (!response.ok) throw new Error('Failed to delete collection');
    return response.json();
}

/**
 * Add images to a collection
 */
export async function addImagesToCollection(collectionId, images) {
    const response = await fetch(`${API_BASE}/${collectionId}/images`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ images })
    });
    if (!response.ok) throw new Error('Failed to add images');
    return response.json();
}

/**
 * Remove images from a collection
 */
export async function removeImagesFromCollection(collectionId, images) {
    const response = await fetch(`${API_BASE}/${collectionId}/images`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ images })
    });
    if (!response.ok) throw new Error('Failed to remove images');
    return response.json();
}

/**
 * Bulk import collections (for localStorage migration)
 */
export async function importCollections(collections) {
    const response = await fetch(`${API_BASE}/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ collections })
    });
    if (!response.ok) throw new Error('Failed to import collections');
    return response.json();
}

/**
 * Export all collections
 */
export async function exportCollections() {
    const response = await fetch(`${API_BASE}/export`);
    if (!response.ok) throw new Error('Failed to export collections');
    return response.json();
}

export default {
    listCollections,
    getCollection,
    createCollection,
    updateCollection,
    deleteCollection,
    addImagesToCollection,
    removeImagesFromCollection,
    importCollections,
    exportCollections
};
