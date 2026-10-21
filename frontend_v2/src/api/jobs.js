/**
 * Jobs API
 * All job-related API calls.
 */

import api from './client';
import { GUIDED, resolveGenerationKind, stripGenerationKind } from './generate';

/**
 * Every read takes a trailing `options` and forwards it to the client, so a
 * React Query `queryFn` can pass the `AbortSignal` from its context. These are
 * the polling queries: an unmounted card or a job list that has moved on would
 * otherwise leave its request running to completion and then write a result
 * nobody is watching. Writes do not need it — a mutation is not cancelled by
 * changing keys.
 */
export const jobsApi = {
    // List jobs with pagination
    list: (params = {}, options = {}) => api.get('/api/jobs', { params, ...options }),

    // Get single job
    get: (jobId, options = {}) => api.get(`/api/jobs/${jobId}`, options),
    
    // Get all active jobs (pending/running)
    getActive: (options = {}) => api.get('/api/jobs/active', options),

    // Get queue status with per-task-type ETA estimates
    getQueueStatus: (options = {}) => api.get('/api/jobs/queue', options),

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
    getDiagnostics: (jobId, options = {}) => api.get(`/api/jobs/${jobId}/diagnostics`, options),

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
    getFailed: (params = {}, options = {}) => {
        const query = {};
        if (params.limit != null) query.limit = params.limit;
        if (params.offset != null) query.offset = params.offset;
        if (params.taskType) query.task_type = params.taskType;
        if (params.includeAcknowledged) query.include_acknowledged = true;
        return api.get('/api/jobs/failed', { params: query, ...options });
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
     * The payload goes into the field that matches its shape: `options` for a
     * guided request (the backend compiles it and checks the models it names)
     * and `workflow` for a graph.
     *
     * The shape is stated, not sniffed. It used to be read off the payload -
     * "an object with a `mode` or a `prompt` key is options" - so a ComfyUI
     * graph in API format, whose top-level key IS `prompt`, was sent as
     * options: the backend tried to compile it as generator options and
     * answered 422 for a request that was perfectly valid as a graph.
     *
     * @param {object} payload - The generator options (guided) or the ComfyUI graph.
     * @param {string|null} preferredProviderId - Optional preferred provider
     * @param {string|null} [kind] - `'guided'` or `'graph'`. Defaults to the
     *   kind the payload declares, and to `'graph'` when it declares none.
     * @returns {Promise<{
     *   valid: boolean,
     *   eligible_providers: string[],
     *   missing_models: Object,
     *   global_missing: Object,
     *   can_trigger_download: boolean,
     *   required_models: Object
     * }>}
     */
    validate: (payload, preferredProviderId = null, kind = null) => {
        const resolved = resolveGenerationKind(payload, kind);
        const body = { preferred_provider_id: preferredProviderId };
        if (resolved === GUIDED) {
            body.options = stripGenerationKind(payload);
        } else {
            body.workflow = payload;
        }
        return api.post('/api/jobs/validate', body);
    },
};

export default jobsApi;

