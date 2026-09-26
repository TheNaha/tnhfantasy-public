/**
 * Jobs API
 * All job-related API calls.
 */

import api from './client';

export const jobsApi = {
    // List jobs with pagination
    list: (params = {}) => api.get('/api/jobs', { params }),

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

    /**
     * Retry a failed job.
     * Creates a new job linked to the original via diagnostics.retry_of.
     * @param {string} jobId
     * @param {object} [options]
     * @param {boolean} [options.keepProvider] - Keep the original preferred provider
     *   instead of letting the load balancer pick a healthy one.
     */
    retry: (jobId, options = {}) =>
        api.post(`/api/jobs/${jobId}/retry`, { keep_provider: !!options.keepProvider }),

    /**
     * Cancel a queued or in-flight job. Signals the provider worker and marks
     * the job cancelled. Rejects with 400 for terminal jobs.
     * @param {string} jobId
     * @param {string} [reason]
     */
    cancel: (jobId, reason = null) => api.post(`/api/jobs/${jobId}/cancel`, { reason }),

    /**
     * Failure diagnostics for a single job (provider, model, attempt history,
     * duration, failure kind, retryability).
     * @param {string} jobId
     */
    getDiagnostics: (jobId) => api.get(`/api/jobs/${jobId}/diagnostics`),

    /**
     * List failed jobs (newest first) with diagnostics and a page summary.
     * Acknowledged jobs are hidden unless explicitly asked for, so a user who
     * has already dealt with a failure does not keep seeing it.
     * @param {object} [params]
     * @param {number} [params.limit]
     * @param {number} [params.offset]
     * @param {string} [params.taskType]
     * @param {boolean} [params.includeAcknowledged] - Include acknowledged failures
     */
    getFailed: (params = {}) => {
        const query = {};
        if (params.limit != null) query.limit = params.limit;
        if (params.offset != null) query.offset = params.offset;
        if (params.taskType) query.task_type = params.taskType;
        if (params.includeAcknowledged) query.include_acknowledged = true;
        return api.get('/api/jobs/failed', { params: query });
    },

    /**
     * Acknowledge a failed job — the user has read it and does not want it
     * retried. Not a delete: the job and its history stay, but the job stops
     * being reported as an unacknowledged failure until it is restored.
     * Idempotent in both directions.
     * @param {string} jobId
     * @param {boolean} [acknowledged] - true acknowledges, false restores
     */
    acknowledge: (jobId, acknowledged = true) =>
        api.post(`/api/jobs/${jobId}/acknowledge`, { acknowledged: !!acknowledged }),

    /**
     * Acknowledge or restore every failed job at once. Applies to all
     * failures matching the filter regardless of their current acknowledged
     * state, so it is idempotent in both directions.
     * @param {object} [params]
     * @param {boolean} [params.acknowledged] - true acknowledges, false restores
     * @param {string|null} [params.taskType] - 'image' | 'llm' filter
     */
    acknowledgeAll: ({ acknowledged = true, taskType = null } = {}) =>
        api.post('/api/jobs/acknowledge-all', {
            acknowledged: !!acknowledged,
            task_type: taskType ?? null,
        }),

    /**
     * Requeue interrupted work and fail jobs wedged past the stale timeout.
     * @param {object} [params]
     * @param {number} [params.timeoutSeconds]
     */
    recover: (params = {}) => {
        const query = {};
        if (params.timeoutSeconds != null) query.timeout_seconds = params.timeoutSeconds;
        return api.post('/api/jobs/recover', {}, { params: query });
    },

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
    validate: (workflowOrOptions, preferredProviderId = null) => {
        const payload = { preferred_provider_id: preferredProviderId };
        if (workflowOrOptions?.mode !== undefined || workflowOrOptions?.prompt !== undefined) {
            payload.options = workflowOrOptions;
        } else {
            payload.workflow = workflowOrOptions;
        }
        return api.post('/api/jobs/validate', payload);
    },
};

export default jobsApi;

