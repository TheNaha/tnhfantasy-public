/**
 * Files API
 * Gallery/file-related API calls.
 *
 * Upload helpers apply the client-side size/type pre-check (clear errors
 * without a round trip) and accept `{ signal, onProgress }` so callers can
 * cancel a slow upload and show progress. The backend response is always
 * authoritative and its `{ error, code }` payload is surfaced in `error.message`.
 */

import api, { API_V2_BASE } from './client';
import { UPLOAD_LIMITS, assertUploadAllowed, uploadWithProgress } from './upload';

/** Route an upload through XHR when the caller wants progress, else fetch. */
function sendUpload(endpoint, formData, options) {
    if (options?.onProgress) {
        return uploadWithProgress(endpoint, formData, options);
    }
    const { onProgress, ...rest } = options || {};
    return api.post(endpoint, formData, rest);
}

export const filesApi = {
    list: (params = {}, options = {}) => api.get('/api/files', {
        params: Object.fromEntries(Object.entries(params).filter(([, v]) => v)),
        ...options,
    }),

    // Delete multiple files (from output directory)
    deleteMultiple: (filenames) => api.post('/api/batch/delete', {
        directory: 'output',
        files: filenames
    }),

    /**
     * Download multiple files as a ZIP archive.
     *
     * @param {string[]} filenames
     * @param {{signal?: AbortSignal, timeout?: number}} [options]
     * @returns {Promise<{blob: Blob, missing: string[], missingCount: number}>}
     *   the archive plus the files the backend could not find (reported via
     *   X-Missing-Files / X-Missing-Count).
     */
    batchDownload: async (filenames, options = {}) => {
        if (!Array.isArray(filenames) || filenames.length === 0) {
            throw new Error('Select at least one file to download');
        }
        if (filenames.length > UPLOAD_LIMITS.export.maxFiles) {
            throw new Error(
                `Too many files selected (${filenames.length}). ` +
                `Download at most ${UPLOAD_LIMITS.export.maxFiles} at a time.`
            );
        }

        const response = await api.post('/api/files/batch-download', { files: filenames }, options);

        // The endpoint answers with a zip; anything else means the server
        // refused the export and saving it would hand the user a broken file.
        let blob;
        if (response instanceof Blob) {
            blob = response;
        } else if (typeof response?.blob === 'function') {
            const contentType = response.headers?.get?.('content-type') || '';
            if (contentType && !contentType.includes('zip')) {
                let detail = '';
                try {
                    detail = (await response.text()).slice(0, 300);
                } catch {
                    detail = '';
                }
                throw new Error(`Download failed: ${detail || 'server did not return an archive'}`);
            }
            blob = await response.blob();
        } else {
            throw new Error('Download failed: unexpected response from server');
        }

        const headers = response?.headers;
        const missingHeader = headers?.get?.('x-missing-files') || '';
        const missingCount = Number(headers?.get?.('x-missing-count') || 0);

        return {
            blob,
            missing: missingHeader ? missingHeader.split(',').filter(Boolean) : [],
            missingCount,
        };
    },

    /**
     * Upload image for Img2Img or Inpainting.
     * Saves locally and syncs to all active providers.
     *
     * @param {File} file - Image file to upload
     * @param {string|null} providerId - Provider ID to sync to (optional)
     * @param {{signal?: AbortSignal, onProgress?: Function}} [options]
     * @returns {Promise<{status, filename, path, width, height, sync_status}>}
     */
    uploadInput: async (file, providerId = null, options = {}) => {
        assertUploadAllowed(file, 'input');

        const formData = new FormData();
        formData.append('file', file);

        const params = providerId ? `?provider_id=${providerId}` : '';
        return sendUpload(`/api/upload/input${params}`, formData, options);
    },

    /**
     * Upload mask for Inpainting.
     * Accepts base64 data URL from canvas export.
     *
     * @param {string} maskDataUrl - Base64 data URL of the mask (data:image/png;base64,...)
     * @param {string} sourceFilename - Filename of the source image (for naming)
     * @param {string|null} providerId - Provider ID to sync to (optional)
     * @returns {Promise<{status, filename, path, sync_status}>}
     */
    uploadMask: async (maskDataUrl, sourceFilename, providerId = null, options = {}) => {
        if (typeof maskDataUrl !== 'string' || !maskDataUrl) {
            throw new Error('Mask data is missing');
        }
        // base64 inflates by ~4/3; check the encoded size against the same budget.
        if (maskDataUrl.length > UPLOAD_LIMITS.input.maxBytes * 1.4) {
            throw new Error(
                `Mask is too large. Max size is ${Math.round(UPLOAD_LIMITS.input.maxBytes / (1024 * 1024))} MB.`
            );
        }

        const params = providerId ? `?provider_id=${providerId}` : '';
        const { onProgress, ...rest } = options || {};

        return api.post(`/api/upload/mask${params}`, {
            mask_data: maskDataUrl,
            source_filename: sourceFilename
        }, rest);
    },

    /**
     * Upload a chat attachment (image) to the chat attachments directory.
     *
     * @param {FormData} formData - FormData containing the file under the 'file' key
     * @param {{signal?: AbortSignal, onProgress?: Function}} [options]
     * @returns {Promise<{filename, path, ...}>}
     */
    uploadChatAttachment: (formData, options = {}) => {
        const file = formData?.get?.('file');
        if (file) assertUploadAllowed(file, 'file');
        return sendUpload('/api/upload?path=chat_attachments', formData, options);
    },

    // Fetch metadata for multiple images in a single request
    batchMetadata: (paths) => api.post('/api/files/metadata/batch', { paths }),
};

/**
 * Assets API (v2)
 * DB-backed gallery listing with keyset pagination.
 */
export const assetsApi = {
    list: (params = {}, options = {}) => api.get(`${API_V2_BASE}/assets`, {
        params: Object.fromEntries(Object.entries(params).filter(([, v]) => v)),
        ...options,
    }),

    /**
     * The faceted listing. Returns the SAME `items` / `has_more` /
     * `next_cursor` shape as `list`, the same sort vocabulary and the same
     * keyset cursor, and adds `facets`, `sessions` and `total_matched` — so this
     * is a strict superset and the gallery uses it instead of `list` rather than
     * running a second query to get the counts.
     *
     * `group_by` is capped server-side at 3 dimensions; the panel sends only the
     * dimensions it is showing.
     */
    facet: (params = {}, options = {}) => api.get(`${API_V2_BASE}/assets/facet`, {
        params: Object.fromEntries(
            Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
        ),
        ...options,
    }),

    /**
     * Per-day counts for the date rail, on the gallery's own
     * `coalesce(generated_at, created_at)` timeline, scoped by exactly the
     * filters the listing accepts — so a day's tick and that day's contents can
     * never disagree. Not `/api/statistics`' `images_by_date`, which buckets on
     * a different column and applies no scope at all.
     */
    dates: (params = {}, options = {}) => api.get(`${API_V2_BASE}/assets/dates`, {
        params: Object.fromEntries(Object.entries(params).filter(([, v]) => v)),
        ...options,
    }),

    /** The distinct tag vocabulary, most-used first. `prefix` is anchored. */
    tags: (params = {}, options = {}) => api.get(`${API_V2_BASE}/tags`, {
        params: Object.fromEntries(Object.entries(params).filter(([, v]) => v)),
        ...options,
    }),

    /** One image's tags with their provenance. */
    assetTags: (assetId, options = {}) =>
        api.get(`${API_V2_BASE}/asset/${encodeURIComponent(assetId)}/tags`, options),

    /** Add a `user` tag. Idempotent; the response reports `created: false` on a re-add. */
    addAssetTag: (assetId, tag, options = {}) =>
        api.post(`${API_V2_BASE}/asset/${encodeURIComponent(assetId)}/tags`, { tag }, options),

    /**
     * Remove a `user` tag. 404s when the tag is auto-derived rather than typed,
     * on purpose: a delete that appears to work and then resurrects itself on
     * the next rescan is worse than an honest 404.
     */
    removeAssetTag: (assetId, tag, options = {}) =>
        api.delete(
            `${API_V2_BASE}/asset/${encodeURIComponent(assetId)}/tags/${encodeURIComponent(tag)}`,
            options
        ),

    /**
     * The distinct tag vocabulary with use-counts, most-used first.
     *
     * Use-count order is the point: an alphabetical list of a few thousand booru
     * tokens is a list nobody scrolls. `prefix` is the typeahead's anchored mode,
     * `q` the looser substring search.
     */
    tagVocabulary: (params = {}, options = {}) =>
        api.get(`${API_V2_BASE}/tags`, {
            params: Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')),
            ...options,
        }),
};

export default filesApi;
