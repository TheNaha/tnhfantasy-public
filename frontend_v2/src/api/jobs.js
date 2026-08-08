/**
 * Jobs API
 * All job-related API calls.
 */

import api from './client';

export const jobsApi = {
    // List jobs with pagination
    list: (params = {}) => {
        const query = new URLSearchParams(params).toString();
        return api.get(`/api/jobs${query ? `?${query}` : ''}`);
    },

    // Get single job
    get: (jobId) => api.get(`/api/jobs/${jobId}`),
    
    // Get all active jobs (pending/running)
    getActive: () => api.get('/api/jobs/active'),

    // Get queue status with per-task-type ETA estimates
    getQueueStatus: () => api.get('/api/jobs/queue'),

    // Delete job
    delete: (jobId) => api.delete(`/api/jobs/${jobId}`),

    // Clear all jobs
    clear: () => api.delete('/api/jobs'),

    // Retry a failed job
    retry: (jobId) => api.post(`/api/jobs/${jobId}/retry`),

    /**
     * Validate workflow model availability before submission.
     * Returns info about which providers can run this workflow.
     * 
     * @param {object} workflow - ComfyUI workflow object
     * @param {string|null} preferredProviderId - Optional preferred provider
     * @returns {Promise<{
     *   valid: boolean,
     *   eligible_providers: string[],
     *   missing_models: Object,
     *   global_missing: Object,
     *   can_trigger_download: boolean,
     *   required_models: Object
     * }>}
     */
    validate: (workflow, preferredProviderId = null) =>
        api.post('/api/jobs/validate', {
            workflow,
            preferred_provider_id: preferredProviderId
        }),
};

export default jobsApi;

