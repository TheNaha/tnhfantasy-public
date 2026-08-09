/**
 * useLLMJobResult — submit an LLM job and await its final text output.
 *
 * Replaces the duplicated "submit /api/jobs + poll /api/jobs/{id} every 1s" loops
 * (Characters field generation, StorySandbox titles, ChatWorkspace titles).
 * Resolves via WebSocket JOB_COMPLETED events when connected, with a polling
 * fallback so it also works without a WS connection.
 *
 * Resolves with { jobId, text } where text is outputs[0].content (may be null).
 * Resolves with { jobId, text: null, cancelled: true } if isCancelled() returns true.
 * Rejects on job failure, timeout (maxPolls exhausted), or submission error.
 */
import { useCallback, useRef } from 'react';
import { api } from '../api';
import { on, EventTypes, getConnectionStatus } from '../api/websocket';

const getJob = (event) => event?.job ?? event;

export function useLLMJobResult({ pollInterval = 1000, defaultMaxPolls = 300 } = {}) {
    const pollIntervalRef = useRef(pollInterval);
    const defaultMaxPollsRef = useRef(defaultMaxPolls);

    return useCallback(async ({ workflow, taskType = 'llm', maxPolls, isCancelled = () => false }) => {
        const res = await api.post('/api/jobs', { task_type: taskType, workflow });
        const jobId = res?.id;
        if (!jobId) throw new Error('LLM job submission returned no job id');

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
                resolve({ jobId, text: job?.outputs?.[0]?.content ?? null });
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

            (async () => {
                // WebSocket-first: when connected we rely on JOB_COMPLETED/FAILED
                // events and only poll as a genuine last-resort fallback. When
                // disconnected, poll immediately so the hook still resolves.
                const wsConnected = getConnectionStatus();
                // Long overall ceiling (300s) so slow jobs (e.g. Modal cold
                // starts) never get a false "LLM job failed" rejection.
                const max = maxPolls ?? defaultMaxPollsRef.current;
                const initialDelay = wsConnected ? 5000 : 0;
                for (let i = 0; i < max && !settled; i++) {
                    if (isCancelled()) {
                        onCancelled();
                        return;
                    }
                    const delay = i === 0 ? initialDelay : pollIntervalRef.current;
                    if (delay > 0) await new Promise((r) => setTimeout(r, delay));
                    try {
                        const job = await api.get(`/api/jobs/${jobId}`);
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
    }, []);
}
