/**
 * Files API
 * Gallery/file-related API calls.
 */

import api from './client';
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

    // Download multiple files as a ZIP archive
    batchDownload: async (filenames) => {
        const response = await api.post('/api/files/batch-download', {
            files: filenames
        });
        return await response.blob();
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
        return api.post(`/api/upload/input${params}`, formData);
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

        return api.post(`/api/upload/mask${params}`, {
                mask_data: maskDataUrl,
                source_filename: sourceFilename
        });
    },

    /**
     * Upload a chat attachment (image) to the chat attachments directory.
     *
     * @param {FormData} formData - FormData containing the file under the 'file' key
     * @returns {Promise<{filename, path, ...}>}
     */
    uploadChatAttachment: (formData) => api.post('/api/upload?path=chat_attachments', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
    }),

    // Fetch metadata for multiple images in a single request
    batchMetadata: (paths) => api.post('/api/files/metadata/batch', { paths }),
};

/**
 * Assets API (v2)
 * DB-backed gallery listing with keyset pagination.
 */
export const assetsApi = {
    list: (params = {}, options = {}) => api.get('/api/v2/assets', {
        params: Object.fromEntries(Object.entries(params).filter(([, v]) => v)),
        ...options,
    }),

    move: (assetId, body) => api.post(`/api/v2/assets/${assetId}/move`, body),
};

export default filesApi;
