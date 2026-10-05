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
 *  - clearStreamingJob(qc, jobId, chatId?) → settle a terminal job and remove it
 *  - getStreamingJob(qc, jobId)        → read one entry synchronously (call in effects)
 *  - isStreamingJobSettled(jobId)      → has its terminal event already been handled?
 *
 * Two query namespaces are kept in sync by every mutator:
 *   ['streaming', jobId]                       per-job payload (for targeted lookups)
 *   ['streaming', 'active', chatId]            array of active payloads for a chat (for lists)
 *
 * Terminal-state memory
 * ---------------------
 * A submitter learns its job id from the *HTTP response*, but the terminal
 * WebSocket event for that job can arrive before the response does. Measured on
 * the live stack: `job.created` at t=6123ms, `job.failed` at t=6174ms, the POST
 * returning 200 at t=6230ms. `settleStreamingJob` therefore records the id even
 * when there is nothing to remove, and `setStreamingJob` refuses to insert a
 * job whose terminal event already landed — otherwise the submitter re-inserted
 * a placeholder nothing would ever clear, leaving "X is thinking…" on screen
 * until a page reload. This is module state rather than query state on purpose:
 * it must be readable synchronously from `setStreamingJob`, which runs outside
 * React, and it is worthless after a reload.
 */
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

const JOB_KEY = (jobId) => ['streaming', jobId];
const ACTIVE_KEY = (chatId) => ['streaming', 'active', chatId];

/**
 * Job ids whose terminal event (completed/failed/cancelled) has been handled.
 * Bounded: a session dispatches far fewer than this, and evicting the oldest
 * entry can only re-open the race for a job from long ago, which is no longer
 * in flight.
 */
const SETTLED_CAP = 200;
const settledJobs = new Set();

export function isStreamingJobSettled(jobId) {
    return !!jobId && settledJobs.has(jobId);
}

/**
 * Upsert a streaming-job payload into React Query cache.
 * @param {object} queryClient
 * @param {string} jobId
 * @param {object} data   e.g. { text, status:'running', chatId, type, taskType, progress }
 */
export function setStreamingJob(queryClient, jobId, data) {
    if (!queryClient || !jobId) return;
    if (settledJobs.has(jobId)) return;

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
 * Mark a job as terminal: record the id so a later `setStreamingJob` for the
 * same id is refused, then remove whatever is still cached.
 *
 * Every caller of this is a terminal-event handler (completed / failed /
 * cancelled in `useChatStreaming.js`), which is why the settlement is recorded
 * here rather than at the call sites — a new terminal handler cannot forget it.
 * Passing `chatId` makes the removal O(1); omitting it falls back to the chatId
 * captured from the per-job payload before removal (used by handlers that only
 * know the job id).
 */
export function clearStreamingJob(queryClient, jobId, chatId) {
    if (!jobId) return;

    if (settledJobs.size >= SETTLED_CAP) {
        const oldest = settledJobs.values().next().value;
        settledJobs.delete(oldest);
    }
    settledJobs.add(jobId);

    if (!queryClient) return;

    const resolvedChatId = chatId || queryClient.getQueryData(JOB_KEY(jobId))?.chatId;

    queryClient.removeQueries({ queryKey: JOB_KEY(jobId) });

    if (resolvedChatId) {
        queryClient.setQueryData(ACTIVE_KEY(resolvedChatId), (old = []) =>
            old.filter((j) => j._jobId !== jobId)
        );
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
