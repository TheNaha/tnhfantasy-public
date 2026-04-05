/**
 * Files API
 * Gallery/file-related API calls.
 */

import api from './client';
export const filesApi = {
    // List files with pagination
    list: (params = {}, options = {}) => {
        const query = new URLSearchParams(params).toString();
        return api.get(`/api/files${query ? `?${query}` : ''}`, options);
    },

    // Delete file
    delete: (filename) => api.delete(`/api/files/${encodeURIComponent(filename)}`),

    // Delete multiple files (from output directory)
    deleteMultiple: (filenames) => api.post('/api/batch/delete', {
        directory: 'output',
        files: filenames
    }),

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
};

export default filesApi;
