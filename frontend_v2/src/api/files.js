/**
 * Files API
 * Gallery/file-related API calls.
 */

import api, { ApiError } from './client';
import { getApiUrl } from './config';

export const filesApi = {
    // List files with pagination
    list: (params = {}) => {
        const query = new URLSearchParams(params).toString();
        return api.get(`/api/files${query ? `?${query}` : ''}`);
    },

    // Delete file
    delete: (filename) => api.delete(`/api/files/${encodeURIComponent(filename)}`),

    // Delete multiple files (from output directory)
    deleteMultiple: (filenames) => api.post('/api/batch/delete', {
        directory: 'output',
        files: filenames
    }),

    // Get file URL (for images)
    getUrl: (filename) => `${getApiUrl()}/api/files/${encodeURIComponent(filename)}`,

    // Get thumbnail URL
    getThumbnailUrl: (filename, size = 256) =>
        `${getApiUrl()}/api/files/thumbnail/${encodeURIComponent(filename)}?size=${size}`,

    // Upload file
    upload: async (file) => {
        const formData = new FormData();
        formData.append('file', file);
        return api.post('/api/files/upload', formData);
    },

    /**
     * Upload image for Img2Img or Inpainting.
     * Saves locally and syncs to the specified provider's Modal volume.
     * 
     * @param {File} file - Image file to upload
     * @param {string|null} providerId - Provider ID to sync to (optional)
     * @returns {Promise<{status, filename, path, width, height, sync_status}>}
     */
    uploadInput: async (file, providerId = null) => {
        const formData = new FormData();
        formData.append('file', file);

        const params = providerId ? `?provider_id=${providerId}` : '';

        const response = await fetch(`${getApiUrl()}/api/upload/input${params}`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.text();
            throw new ApiError('Upload failed', response.status, { detail: error });
        }

        return response.json();
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
    uploadMask: async (maskDataUrl, sourceFilename, providerId = null) => {
        const params = providerId ? `?provider_id=${providerId}` : '';

        const response = await fetch(`${getApiUrl()}/api/upload/mask${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mask_data: maskDataUrl,
                source_filename: sourceFilename
            })
        });

        if (!response.ok) {
            const error = await response.text();
            throw new ApiError('Mask upload failed', response.status, { detail: error });
        }

        return response.json();
    },
};

export default filesApi;
