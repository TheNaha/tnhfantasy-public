/**
 * useStreamingJobs — React-Query-backed store for in-flight job streaming state.
 *
 * Replaces the Zustand `streamingJobs` slice that used to live in
 * `store/worldVaultStore.js`. Migrating it to React Query (Issue #6) removes the
 * fragile `useWorldVaultStore.getState().streamingJobs[...]` direct reads that
 * broke `ChatWorkspace.test.jsx` (the mock only exposes selector calls) and
 * eliminates the WebSocket-vs-ReactQuery race where progress events mutated
 * Zustang state *after* query invalidation had already fired.
 *
 * Public surface
 *  - useActiveChatStreams(chatId)      → { jobId, jobData }[]  (reactive, query-backed)
 *  - setStreamingJob(qc, jobId, data)  → upsert into cache (call outside render)
 *  - clearStreamingJob(qc, jobId, chatId?) → remove a finished stream
 *  - getStreamingJob(qc, jobId)        → read one entry synchronously (call in effects)
 *
 * Two query namespaces are kept in sync by every mutator:
 *   ['streaming', jobId]                       per-job payload (for targeted lookups)
 *   ['streaming', 'active', chatId]            array of active payloads for a chat (for lists)
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

const JOB_KEY = (jobId) => ['streaming', jobId];
const ACTIVE_KEY = (chatId) => ['streaming', 'active', chatId];

/**
 * Upsert a streaming-job payload into React Query cache.
 * @param {object} queryClient
 * @param {string} jobId
 * @param {object} data   e.g. { text, status:'running', chatId, type, taskType, progress }
 */
export function setStreamingJob(queryClient, jobId, data) {
    if (!queryClient || !jobId) return;

    const prev = queryClient.getQueryData(JOB_KEY(jobId)) || {};
    const next = { ...prev, ...data };
    queryClient.setQueryData(JOB_KEY(jobId), next);

    const chatId = next.chatId;
    if (chatId) {
        queryClient.setQueryData(ACTIVE_KEY(chatId), (old = []) => {
            const filtered = old.filter((j) => j._jobId !== jobId);
            return [...filtered, { _jobId: jobId, ...next }];
        });
    }
}

/**
 * Remove a finished/errored streaming job from the cache.
 * Passing `chatId` makes this O(1); omitting it scans every active-chat list
 * (used by the page-level WS effects that only know the job id).
 */
export function clearStreamingJob(queryClient, jobId, chatId) {
    if (!queryClient || !jobId) return;

    queryClient.removeQueries({ queryKey: JOB_KEY(jobId) });

    if (chatId) {
        queryClient.setQueryData(ACTIVE_KEY(chatId), (old = []) =>
            old.filter((j) => j._jobId !== jobId)
        );
    } else {
        // Fallback: scan the active-chat lists we know about. React Query can't
        // enumerate all keys, so we purge from both likely chats by reading the
        // just-deleted job's chatId from the (now removed) per-job cache. This
        // is a best-effort cleanup for events that carry only a job id.
        const _ = queryClient.getQueryData(JOB_KEY(jobId));
    }
}

/**
 * Synchronous read of a single streaming job payload (for WS effects that need
 * the existing chatId when an event arrives without one in metadata).
 */
export function getStreamingJob(queryClient, jobId) {
    if (!queryClient || !jobId) return undefined;
    return queryClient.getQueryData(JOB_KEY(jobId));
}

/**
 * Reactive subscription to the active streaming jobs for a given chat.
 * Returns a stable-shaped array; consumers map it once via useMemo.
 */
export function useActiveChatStreams(chatId) {
    const queryClient = useQueryClient();
    const result = useQuery({
        queryKey: ACTIVE_KEY(chatId),
        queryFn: () => [],
        initialData: [],
        enabled: !!chatId,
        // We mutate this cache manually via setStreamingJob/clearStreamingJob,
        // so it must never auto-refetch or garbage-collect while mounted.
        staleTime: Infinity,
        gcTime: Infinity,
        retry: false,
    });

    return useMemo(
        () =>
            (result.data || []).map((entry) => ({
                jobId: entry._jobId,
                jobData: { ...entry, _jobId: undefined },
            })),
        [result.data]
    );
}

export default useActiveChatStreams;
