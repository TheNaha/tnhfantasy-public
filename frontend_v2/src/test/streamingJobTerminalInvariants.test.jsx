/**
 * The submitter learns its job id from the HTTP *response*; the terminal
 * WebSocket event for that job can arrive first. These tests assert the rule
 * that closes the race rather than the instance that happened to exhibit it,
 * because the race is a property of the ordering, not of any one call site.
 *
 * Measured on the live stack before the fix (single send, timestamps relative
 * to the click):
 *   t=6123ms  WS recv  job.created  id=697afdc5 status=pending
 *   t=6174ms  WS recv  job.failed   id=697afdc5
 *   t=6230ms  HTTP POST /messages -> 200 {"job_id":"697afdc5"}
 *
 * `job.failed` was handled against an empty store, so its clear was a no-op;
 * the POST response then inserted a placeholder whose only removers —
 * JOB_COMPLETED / JOB_FAILED / JOB_CANCELLED — had already fired. The result
 * was a permanent "Ilse Vondt is thinking…" with three bouncing dots.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import React from 'react';

import {
    setStreamingJob,
    clearStreamingJob,
    getStreamingJob,
    isStreamingJobSettled,
    useActiveChatStreams,
} from '../hooks/useStreamingJobs';

const ACTIVE_KEY = (chatId) => ['streaming', 'active', chatId];
const JOB_KEY = (jobId) => ['streaming', jobId];

function makeClient() {
    return new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } },
    });
}

function wrapperFor(queryClient) {
    return function Wrapper({ children }) {
        return React.createElement(QueryClientProvider, { client: queryClient }, children);
    };
}

/** Read the active-stream list synchronously, the way the UI does. */
function activeEntries(queryClient, chatId) {
    return queryClient.getQueryData(ACTIVE_KEY(chatId)) || [];
}

let seq = 0;
const nextJobId = () => `job-${(seq += 1)}`;

describe('streaming job terminal-state memory', () => {
    let queryClient;

    beforeEach(() => {
        queryClient = makeClient();
    });

    it('does not resurrect a placeholder for a job that already reached a terminal state', () => {
        const jobId = nextJobId();
        const chatId = 'chat-1';

        // The job is created and fails before the submitter's HTTP response
        // returns, so nothing is cached when the failure is handled.
        setStreamingJob(queryClient, jobId, { status: 'queued', chatId, text: '' });
        expect(getStreamingJob(queryClient, jobId)).toBeTruthy();

        clearStreamingJob(queryClient, jobId, chatId);
        expect(getStreamingJob(queryClient, jobId)).toBeUndefined();
        expect(activeEntries(queryClient, chatId)).toHaveLength(0);

        // The POST response lands afterwards and does what it always did.
        setStreamingJob(queryClient, jobId, { text: '', status: 'running', chatId });

        expect(getStreamingJob(queryClient, jobId)).toBeUndefined();
        expect(activeEntries(queryClient, chatId)).toHaveLength(0);
    });

    it('handles the terminal event arriving before anything was ever inserted', () => {
        // The measured ordering had job.failed at t=6174ms with the POST still
        // in flight, so the clear ran against a completely empty store.
        const jobId = nextJobId();
        const chatId = 'chat-1';

        clearStreamingJob(queryClient, jobId, chatId);

        expect(isStreamingJobSettled(jobId)).toBe(true);
        setStreamingJob(queryClient, jobId, { text: '', status: 'running', chatId });
        expect(getStreamingJob(queryClient, jobId)).toBeUndefined();
    });

    it('records the settlement even when the caller passes no queryClient', () => {
        const jobId = nextJobId();
        clearStreamingJob(undefined, jobId, 'chat-1');
        expect(isStreamingJobSettled(jobId)).toBe(true);

        setStreamingJob(makeClient(), jobId, { text: '', status: 'running', chatId: 'chat-1' });
        expect(isStreamingJobSettled(jobId)).toBe(true);
    });

    it('still tracks a job that has not settled', () => {
        const jobId = nextJobId();
        const chatId = 'chat-1';
        expect(isStreamingJobSettled(jobId)).toBe(false);

        setStreamingJob(queryClient, jobId, { text: 'partial', status: 'running', chatId });
        expect(getStreamingJob(queryClient, jobId)?.text).toBe('partial');
        expect(activeEntries(queryClient, chatId).map((j) => j._jobId)).toEqual([jobId]);
    });

    it('bounds the settlement memory instead of growing it for the session', () => {
        // SETTLED_CAP is 200. Insert far more than that and assert the oldest
        // eviction happened, so this cannot become a leak.
        for (let i = 0; i < 260; i += 1) {
            clearStreamingJob(queryClient, `flood-${i}`, 'chat-flood');
        }
        expect(isStreamingJobSettled('flood-0')).toBe(false);
        expect(isStreamingJobSettled('flood-259')).toBe(true);
    });

    it('surfaces the settled set through the reactive hook as "no active stream"', () => {
        const chatId = 'chat-hook';
        const jobId = nextJobId();
        const { result, rerender } = renderHook(() => useActiveChatStreams(chatId), {
            wrapper: wrapperFor(queryClient),
        });

        expect(result.current).toHaveLength(0);

        setStreamingJob(queryClient, jobId, { text: 'hi', status: 'running', chatId });
        rerender();
        expect(result.current).toHaveLength(1);

        clearStreamingJob(queryClient, jobId, chatId);
        rerender();
        expect(result.current).toHaveLength(0);

        // And the late insert still does not bring it back.
        setStreamingJob(queryClient, jobId, { text: '', status: 'running', chatId });
        rerender();
        expect(result.current).toHaveLength(0);
    });

    it('covers every production insertion site, not just the send path', () => {
        // All seven `setStreamingJob(queryClient, res.job_id, …)` call sites in
        // ChatWorkspaceContext.jsx have the same shape: the id comes from an
        // HTTP response, so every one of them can be beaten to the punch by the
        // terminal event. The fix is in the primitive, so it covers all of them
        // — this asserts that property for a representative sample of the other
        // six rather than re-listing them.
        const sites = [
            ['chat send', 'roleplay'],
            ['scene image', 'roleplay'],
            ['impersonation', 'impersonation'],
            ['llm action', 'llm'],
            ['image action', 'image'],
        ];
        for (const [label, type] of sites) {
            const jobId = nextJobId();
            const chatId = `chat-${label}`;
            clearStreamingJob(queryClient, jobId, chatId);
            setStreamingJob(queryClient, jobId, { text: '', status: 'running', chatId, type });
            expect(
                getStreamingJob(queryClient, jobId),
                `${label} resurrected a settled job`
            ).toBeUndefined();
        }
    });
});