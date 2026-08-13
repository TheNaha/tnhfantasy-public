// Collections API client - Server-side image collections

import api from './client';

const API_BASE = '/api/collections';

/**
 * List all collections with image counts
 */
export async function listCollections(workspace = null) {
    const params = workspace ? { workspace } : {};
    return api.get(API_BASE, { params });
}

/**
 * Get a single collection with its images
 */
export async function getCollection(id, includeImages = true) {
    return api.get(`${API_BASE}/${id}?include_images=${includeImages}`);
}

/**
 * Create a new collection
 */
export async function createCollection(data) {
    return api.post(API_BASE, data);
}

/**
 * Update a collection (name, color, description)
 */
export async function updateCollection(id, data) {
    return api.put(`${API_BASE}/${id}`, data);
}

/**
 * Delete a collection (images are NOT deleted)
 */
export async function deleteCollection(id) {
    return api.delete(`${API_BASE}/${id}`);
}

/**
 * Add images to a collection
 */
export async function addImagesToCollection(collectionId, images) {
    return api.post(`${API_BASE}/${collectionId}/images`, { images });
}

/**
 * Remove images from a collection
 */
export async function removeImagesFromCollection(collectionId, images) {
    return api.delete(`${API_BASE}/${collectionId}/images`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ images }),
    });
}

/**
 * Bulk import collections (for localStorage migration)
 */
export async function importCollections(collections) {
    return api.post(`${API_BASE}/import`, { collections });
}

/**
 * Move images from one collection to another (cross-workspace). Images are
 * added to the destination (duplicates skipped) and removed from the source.
 * The underlying files are never copied/deleted — only associations change.
 */
export async function moveImagesBetweenCollections(fromCollectionId, toCollectionId, images) {
    return api.post(`${API_BASE}/move`, {
        from_collection_id: fromCollectionId,
        to_collection_id: toCollectionId,
        images,
    });
}
