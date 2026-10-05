// Collections API client - Server-side image collections

import api from './client';

const API_BASE = '/api/v2/collections';

/**
 * Every call here takes a trailing `options` and forwards it to the client.
 *
 * `options` is how a React Query `queryFn` hands over the `AbortSignal` from its
 * context. Without the parameter the signal had nowhere to go: a superseded
 * search or an unmounted panel left the request running to completion, which is
 * one wasted round trip per keystroke on the search-shaped callers. `signal` is
 * optional, so every existing call site is unaffected.
 */

/**
 * List all collections with image counts
 */
export async function listCollections(workspace = null, options = {}) {
    const params = workspace ? { workspace } : {};
    return api.get(API_BASE, { params, ...options });
}

/**
 * Get a single collection with its images
 */
export async function getCollection(id, includeImages = true, options = {}) {
    return api.get(`${API_BASE}/${id}?include_images=${includeImages}`, options);
}

/**
 * Create a new collection
 */
export async function createCollection(data, options = {}) {
    return api.post(API_BASE, data, options);
}

/**
 * Update a collection (name, color, description)
 */
export async function updateCollection(id, data, options = {}) {
    return api.put(`${API_BASE}/${id}`, data, options);
}

/**
 * Delete a collection (images are NOT deleted)
 */
export async function deleteCollection(id, options = {}) {
    return api.delete(`${API_BASE}/${id}`, options);
}

/**
 * Add images to a collection
 */
export async function addImagesToCollection(collectionId, images, options = {}) {
    return api.post(`${API_BASE}/${collectionId}/images`, { images }, options);
}

/**
 * Remove images from a collection
 */
export async function removeImagesFromCollection(collectionId, images, options = {}) {
    return api.delete(`${API_BASE}/${collectionId}/images`, {
        ...options,
        headers: { 'Content-Type': 'application/json', ...options.headers },
        body: JSON.stringify({ images }),
    });
}

/**
 * Bulk import collections (for localStorage migration)
 */
export async function importCollections(collections, options = {}) {
    return api.post(`${API_BASE}/import`, { collections }, options);
}

/**
 * Move images from one collection to another (cross-workspace). Images are
 * added to the destination (duplicates skipped) and removed from the source.
 * The underlying files are never copied/deleted — only associations change.
 */
export async function moveImagesBetweenCollections(fromCollectionId, toCollectionId, images, options = {}) {
    return api.post(`${API_BASE}/move`, {
        from_collection_id: fromCollectionId,
        to_collection_id: toCollectionId,
        images,
    }, options);
}