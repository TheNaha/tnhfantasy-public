/**
 * Files API
 * Gallery/file-related API calls.
 */

import api from './client';
export const filesApi = {
    list: (params = {}, options = {}) => {
        const searchParams = new URLSearchParams();
        if (params.directory) searchParams.append('directory', params.directory);
        if (params.limit) searchParams.append('limit', params.limit);
        if (params.offset) searchParams.append('offset', params.offset);
        if (params.sort) searchParams.append('sort', params.sort);
        if (params.search) searchParams.append('search', params.search);
        
        if (params.base_model) searchParams.append('base_model', params.base_model);
        if (params.model_type) searchParams.append('model_type', params.model_type);
        if (params.show_nsfw !== undefined) searchParams.append('show_nsfw', params.show_nsfw);
        if (params.tags) searchParams.append('tags', params.tags);

        const query = searchParams.toString();
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
