// Collections API client - Server-side image collections

import api from './client';

const API_BASE = '/api/collections';

/**
 * List all collections with image counts
 */
export async function listCollections() {
    return api.get(API_BASE);
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

export default {
    listCollections,
    getCollection,
    createCollection,
    updateCollection,
    deleteCollection,
    addImagesToCollection,
    removeImagesFromCollection,
    importCollections
};
