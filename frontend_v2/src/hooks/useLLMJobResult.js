/**
 * useLLMJobResult — submit an LLM job and await its final text output.
 *
 * Replaces the duplicated "submit /api/jobs + poll /api/jobs/{id} every 1s" loops
 * (Characters field generation, StorySandbox titles, ChatWorkspace titles).
 * Resolves via WebSocket JOB_COMPLETED events when connected, with a polling
 * fallback so it also works without a WS connection.
 *
 * Polling reads/writes through the React Query ['jobs', jobId] cache so the
 * result is shared with useJobStatus consumers instead of living in a private
 * poll loop.
 *
 * Resolves with { jobId, text } where text is outputs[0].content (may be null).
 * Resolves with { jobId, text: null, cancelled: true } if isCancelled() returns true.
 * Rejects on job failure, timeout (maxPolls exhausted), or submission error.
 */
import { useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { on, EventTypes, getConnectionStatus } from '../api/websocket';

const getJob = (event) => event?.data?.job ?? event?.job ?? event?.data ?? event;

const getOutputText = (job) => {
    const output = job?.outputs?.[0];
    if (!output) return null;
    if (typeof output === 'string') return output;
    return output.text ?? output.content ?? output.result?.text ?? null;
};

/**
 * Await the text output of an already-submitted LLM job id.
 * Resolves { jobId, text } | { jobId, text: null, cancelled: true };
 * rejects on failure or when maxPolls is exhausted. Shares the
 * ['jobs', jobId] React Query cache with useJobStatus consumers.
 */
export function awaitJobText({ jobId, queryClient = null, pollInterval = 1000, maxPolls = 300, isCancelled = () => false }) {
    return new Promise((resolve, reject) => {
        let settled = false;
        const unsubs = [];

        const cleanup = () => {
            while (unsubs.length) unsubs.pop()?.();
        };
        const finish = (fn) => (payload) => {
            if (settled) return;
            settled = true;
            cleanup();
            fn(payload);
        };

        const onCompleted = finish((event) => {
            const job = getJob(event);
            resolve({ jobId, text: getOutputText(job) });
        });
        const onFailed = finish(() => reject(new Error('LLM job failed')));
        const onCancelled = finish(() => resolve({ jobId, text: null, cancelled: true }));

        const isForJob = (event) => getJob(event)?.id === jobId;

        unsubs.push(on(EventTypes.JOB_COMPLETED, (event) => {
            if (isForJob(event)) onCompleted(event);
        }));
        unsubs.push(on(EventTypes.JOB_FAILED, (event) => {
            if (isForJob(event)) onFailed(event);
        }));
        unsubs.push(on(EventTypes.JOB_CANCELLED, (event) => {
            if (isForJob(event)) onCancelled(event);
        }));

        const fetchJob = () => {
            if (!queryClient) return api.get(`/api/jobs/${jobId}`);
            return queryClient.fetchQuery({
                queryKey: ['jobs', jobId],
                queryFn: ({ signal }) => api.get(`/api/jobs/${jobId}`, { signal }),
                staleTime: 2000,
            });
        };

        (async () => {
            const wsConnected = getConnectionStatus();

            const cached = queryClient?.getQueryData(['jobs', jobId]);
            if (cached?.status === 'completed' && cached.outputs?.length > 0) {
                onCompleted({ job: cached });
                return;
            }
            if (cached?.status === 'failed') {
                onFailed();
                return;
            }

            for (let i = 0; i < maxPolls && !settled; i++) {
                if (isCancelled()) {
                    onCancelled();
                    return;
                }
                if (i === 0 && wsConnected) {
                    continue;
                }
                const delay = pollInterval;
                if (delay > 0) await new Promise((r) => setTimeout(r, delay));
                try {
                    const job = await fetchJob();
                    if (job?.status === 'completed' && job.outputs?.length > 0) {
                        onCompleted({ job });
                        return;
                    }
                    if (job?.status === 'failed') {
                        onFailed();
                        return;
                    }
                } catch {
                    // transient fetch error — keep polling
                }
            }
            if (!settled) onFailed();
        })();
    });
}

export function useLLMJobResult({ pollInterval = 1000, defaultMaxPolls = 300 } = {}) {
    const pollIntervalRef = useRef(pollInterval);
    const defaultMaxPollsRef = useRef(defaultMaxPolls);
    // Optional cache integration: when rendered under a QueryClientProvider
    // (always true in the app) polls read/write ['jobs', jobId] so useJobStatus
    // consumers share the result. Outside a provider (tests) we fall back to a
    // plain fetch.
    let queryClient = null;
    try {
        // eslint-disable-next-line react-hooks/rules-of-hooks
        queryClient = useQueryClient();
    } catch {
        queryClient = null;
    }

    return useCallback(async ({ workflow, taskType = 'llm', maxPolls, isCancelled = () => false }) => {
        const res = await api.post('/api/jobs', { task_type: taskType, workflow });
        const jobId = res?.id;
        if (!jobId) throw new Error('LLM job submission returned no job id');

        return awaitJobText({
            jobId,
            queryClient,
            pollInterval: pollIntervalRef.current,
            maxPolls: maxPolls ?? defaultMaxPollsRef.current,
            isCancelled,
        });
    }, [queryClient]);
}
