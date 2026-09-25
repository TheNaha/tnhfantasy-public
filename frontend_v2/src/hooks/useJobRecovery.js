/**
 * useJobRecovery — failed-job diagnostics, retry and cancel.
 *
 * Owns the ['jobs','failed'] query (the same cache key useJobsRealtime
 * invalidates on JOB_FAILED) and the mutations that act on failed jobs:
 * retry, cancel and queue recovery. Every mutation refreshes the job, queue,
 * active and failed caches so the dashboard, queue panel and diagnostics view
 * never disagree about a job's state.
 */
import { useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { jobsApi } from '../api';

export const FAILED_JOBS_QUERY_KEY = ['jobs', 'failed'];

const DEFAULT_LIMIT = 10;

/** Invalidate everything that renders job state, in one place. */
function invalidateJobViews(queryClient) {
    return () => {
        queryClient.invalidateQueries({ queryKey: ['jobs'] });
        queryClient.invalidateQueries({ queryKey: ['gallery'] });
    };
}

/**
 * @param {object} [options]
 * @param {number} [options.limit] - Failed jobs to fetch (max 100 server-side)
 * @param {string|null} [options.taskType] - 'image' | 'llm' filter
 * @param {boolean} [options.enabled]
 */
export function useJobRecovery({ limit = DEFAULT_LIMIT, taskType = null, enabled = true } = {}) {
    const queryClient = useQueryClient();

    const query = useQuery({
        queryKey: [...FAILED_JOBS_QUERY_KEY, { limit, taskType }],
        queryFn: () => jobsApi.getFailed({ limit, taskType }),
        enabled,
        staleTime: 15_000,
        refetchOnWindowFocus: false,
    });

    const data = query.data;
    const jobs = Array.isArray(data?.jobs) ? data.jobs : [];
    const total = data?.total ?? jobs.length;
    const summary = data?.summary ?? null;

    const retryMutation = useMutation({
        mutationFn: (jobId) => jobsApi.retry(jobId),
        onSuccess: invalidateJobViews(queryClient),
    });

    const cancelMutation = useMutation({
        mutationFn: ({ jobId, reason } = {}) => jobsApi.cancel(jobId, reason ?? null),
        onSuccess: invalidateJobViews(queryClient),
    });

    const recoverMutation = useMutation({
        mutationFn: (options = {}) => jobsApi.recover(options),
        onSuccess: invalidateJobViews(queryClient),
    });

    const retryJob = useCallback((jobId) => retryMutation.mutateAsync(jobId), [retryMutation]);
    const cancelJob = useCallback(
        (jobId, reason) => cancelMutation.mutateAsync({ jobId, reason }),
        [cancelMutation]
    );
    const recoverJobs = useCallback(
        (options) => recoverMutation.mutateAsync(options),
        [recoverMutation]
    );

    return {
        jobs,
        total,
        summary,
        isLoading: query.isLoading,
        isFetching: query.isFetching,
        error: query.error,
        refetch: query.refetch,

        retryJob,
        cancelJob,
        recoverJobs,

        isRetrying: retryMutation.isPending,
        retryError: retryMutation.error,
        retryingJobId: retryMutation.variables ?? null,

        isCancelling: cancelMutation.isPending,
        cancelError: cancelMutation.error,

        isRecovering: recoverMutation.isPending,
        recoverError: recoverMutation.error,
        recoverySummary: recoverMutation.data ?? null,
    };
}

export default useJobRecovery;
