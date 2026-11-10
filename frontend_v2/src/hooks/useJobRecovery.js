/**
 * useJobRecovery — failed-job diagnostics, retry, cancel and acknowledgement.
 *
 * Owns the ['jobs','failed'] query (the same cache key useJobsRealtime
 * invalidates on JOB_FAILED) and the mutations that act on failed jobs:
 * retry, cancel, acknowledgement (dismiss) and queue recovery. Every mutation
 * refreshes the job, queue, active and failed caches so the dashboard, queue
 * panel and diagnostics view never disagree about a job's state.
 */
import { useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { jobsApi } from '../api';
import { refetchNewestGalleryPage } from './useGallery';
import { reportError } from './useWorldVaultResource';

export const FAILED_JOBS_QUERY_KEY = ['jobs', 'failed'];

const DEFAULT_LIMIT = 10;

/** Invalidate everything that renders job state, in one place. */
function invalidateJobViews(queryClient) {
    return () => {
        queryClient.invalidateQueries({ queryKey: ['jobs'] });
        // Newest page only, not the bare ['gallery'] prefix: that walks every
        // page already loaded, sequentially, for one job state change. The
        // gallery is an infinite query, so a prefix invalidation is a request
        // per page — with fifteen pages loaded, on mobile, that is fifteen
        // round trips and a sentinel that moves as each one lands, which is
        // exactly the infinite-scroll jitter `useGallery` documents. `mounted`
        // matters here: recovery runs from the diagnostics view, where a
        // dashboard may or may not be live, and it just toggles the current
        // tab away and back.
        // A recovered image can also be new, so the gallery moves.
        void refetchNewestGalleryPage(queryClient, { mountedOnly: true });
    };
}

/**
 * @param {object} [options]
 * @param {number} [options.limit] - Failed jobs to fetch (max 100 server-side)
 * @param {string|null} [options.taskType] - 'image' | 'llm' filter
 * @param {boolean} [options.includeAcknowledged] - Include acknowledged
 *   failures in the page. Part of the query key, so toggling it refetches
 *   rather than re-filtering a cached page.
 * @param {boolean} [options.enabled]
 */
export function useJobRecovery({
    limit = DEFAULT_LIMIT,
    taskType = null,
    includeAcknowledged = false,
    enabled = true,
} = {}) {
    const queryClient = useQueryClient();

    const query = useQuery({
        queryKey: [...FAILED_JOBS_QUERY_KEY, { limit, taskType, includeAcknowledged }],
        queryFn: ({ signal }) => jobsApi.getFailed({ limit, taskType, includeAcknowledged }, { signal }),
        enabled,
        staleTime: 15_000,
        refetchOnWindowFocus: false,
    });

    const data = query.data;
    const jobs = Array.isArray(data?.jobs) ? data.jobs : [];
    const total = data?.total ?? jobs.length;
    const summary = data?.summary ?? null;
    // How many failures the server is holding back as acknowledged. It is 0
    // when acknowledged jobs were requested, so it is only a "there are more"
    // hint while they are hidden.
    const acknowledgedCount = data?.acknowledged_count ?? 0;

    const retryMutation = useMutation({
        mutationFn: (jobId) => jobsApi.retry(jobId),
        onSuccess: invalidateJobViews(queryClient),
        onError: (error) => reportError('retry job', error),
    });

    const cancelMutation = useMutation({
        mutationFn: ({ jobId, reason } = {}) => jobsApi.cancel(jobId, reason ?? null),
        onSuccess: invalidateJobViews(queryClient),
        onError: (error) => reportError('cancel job', error),
    });

    const recoverMutation = useMutation({
        mutationFn: (options = {}) => jobsApi.recover(options),
        onSuccess: invalidateJobViews(queryClient),
        onError: (error) => reportError('recover jobs', error),
    });

    /**
     * Acknowledgement is dismissal, not deletion: the job keeps its history and
     * can be restored, which is why the same mutation carries both directions.
     */
    const acknowledgeMutation = useMutation({
        mutationFn: ({ jobId, acknowledged = true } = {}) =>
            jobsApi.acknowledge(jobId, acknowledged),
        onSuccess: invalidateJobViews(queryClient),
        onError: (error) => reportError('acknowledge job', error),
    });

    const acknowledgeAllMutation = useMutation({
        mutationFn: ({ acknowledged = true, taskType = null } = {}) =>
            jobsApi.acknowledgeAll({ acknowledged, taskType }),
        onSuccess: invalidateJobViews(queryClient),
        onError: (error) => reportError('acknowledge all jobs', error),
    });

    /**
     * Destured, never depended on whole.
     *
     * `useMutation` returns a fresh result literal on every render in React
     * Query v5, so `[retryMutation]` as a dependency rebuilt all seven of these
     * callbacks on every render of every consumer — and a consumer that puts
     * one in a `useEffect` or a child's props then re-runs on every render
     * forever. `useFavorites.js` documents the same hazard; this is the same
     * fix applied to every mutation here.
     */
    const { mutateAsync: retryAsync } = retryMutation;
    const { mutateAsync: cancelAsync } = cancelMutation;
    const { mutateAsync: recoverAsync } = recoverMutation;
    const { mutateAsync: acknowledgeAsync } = acknowledgeMutation;
    const { mutateAsync: acknowledgeAllAsync } = acknowledgeAllMutation;

    const retryJob = useCallback((jobId) => retryAsync(jobId), [retryAsync]);
    const cancelJob = useCallback(
        (jobId, reason) => cancelAsync({ jobId, reason }),
        [cancelAsync]
    );
    const recoverJobs = useCallback(
        (options) => recoverAsync(options),
        [recoverAsync]
    );
    const acknowledgeJob = useCallback(
        (jobId) => acknowledgeAsync({ jobId, acknowledged: true }),
        [acknowledgeAsync]
    );
    const unacknowledgeJob = useCallback(
        (jobId) => acknowledgeAsync({ jobId, acknowledged: false }),
        [acknowledgeAsync]
    );
    const acknowledgeAll = useCallback(
        (options) => acknowledgeAllAsync({ acknowledged: true, ...options }),
        [acknowledgeAllAsync]
    );
    const unacknowledgeAll = useCallback(
        () => acknowledgeAllAsync({ acknowledged: false }),
        [acknowledgeAllAsync]
    );

    return {
        jobs,
        total,
        summary,
        acknowledgedCount,
        isLoading: query.isLoading,
        isFetching: query.isFetching,
        error: query.error,
        refetch: query.refetch,

        retryJob,
        cancelJob,
        recoverJobs,
        acknowledgeJob,
        unacknowledgeJob,
        acknowledgeAll,
        unacknowledgeAll,

        isRetrying: retryMutation.isPending,
        retryError: retryMutation.error,
        retryingJobId: retryMutation.variables ?? null,

        isCancelling: cancelMutation.isPending,
        cancelError: cancelMutation.error,

        isRecovering: recoverMutation.isPending,
        recoverError: recoverMutation.error,
        recoverySummary: recoverMutation.data ?? null,

        isAcknowledging: acknowledgeMutation.isPending,
        acknowledgeError: acknowledgeMutation.error,
        acknowledgingJobId: acknowledgeMutation.variables?.jobId ?? null,

        isAcknowledgingAll: acknowledgeAllMutation.isPending,
        acknowledgeAllError: acknowledgeAllMutation.error,
    };
}

export default useJobRecovery;
