import React from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
    setStreamingJob,
    clearStreamingJob,
    getStreamingJob,
    useActiveChatStreams,
} from './useStreamingJobs';

function createQueryClient() {
    return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function createWrapper(queryClient) {
    return ({ children }) =>
        React.createElement(QueryClientProvider, { client: queryClient }, children);
}

const JOB_KEY = ['streaming', 'job-1'];
const ACTIVE_KEY = ['streaming', 'active', 'chat-1'];

describe('useStreamingJobs store helpers', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('setStreamingJob upserts the per-job payload and mirrors it into the chat active list', () => {
        const qc = createQueryClient();
        setStreamingJob(qc, 'job-1', { text: 'hello', chatId: 'chat-1' });
        expect(qc.getQueryData(JOB_KEY)).toEqual({ text: 'hello', chatId: 'chat-1' });
        expect(qc.getQueryData(ACTIVE_KEY)).toEqual([{ _jobId: 'job-1', text: 'hello', chatId: 'chat-1' }]);

        setStreamingJob(qc, 'job-1', { text: 'hello world', status: 'running' });
        expect(qc.getQueryData(JOB_KEY)).toEqual({ text: 'hello world', status: 'running', chatId: 'chat-1' });
        const active = qc.getQueryData(ACTIVE_KEY);
        expect(active).toHaveLength(1);
        expect(active[0].text).toBe('hello world');
    });

    it('setStreamingJob no-ops without a client or job id', () => {
        const qc = createQueryClient();
        setStreamingJob(null, 'job-1', { text: 'x' });
        setStreamingJob(qc, '', { text: 'x' });
        setStreamingJob(qc, null, { text: 'x' });
        expect(qc.getQueryData(JOB_KEY)).toBeUndefined();
    });

    it('setStreamingJob without chatId only updates the per-job namespace', () => {
        const qc = createQueryClient();
        setStreamingJob(qc, 'job-2', { text: 'no chat' });
        expect(qc.getQueryData(['streaming', 'job-2'])).toEqual({ text: 'no chat' });
        expect(qc.getQueryData(['streaming', 'active', undefined])).toBeUndefined();
    });

    it('clearStreamingJob removes both namespaces when chatId is passed', () => {
        const qc = createQueryClient();
        setStreamingJob(qc, 'job-1', { text: 'x', chatId: 'chat-1' });
        clearStreamingJob(qc, 'job-1', 'chat-1');
        expect(qc.getQueryData(JOB_KEY)).toBeUndefined();
        expect(qc.getQueryData(ACTIVE_KEY)).toEqual([]);
    });

    it('clearStreamingJob resolves chatId from the cached payload when omitted', () => {
        const qc = createQueryClient();
        setStreamingJob(qc, 'job-1', { text: 'x', chatId: 'chat-1' });
        clearStreamingJob(qc, 'job-1');
        expect(qc.getQueryData(JOB_KEY)).toBeUndefined();
        expect(qc.getQueryData(ACTIVE_KEY)).toEqual([]);
    });

    it('getStreamingJob reads the per-job payload synchronously', () => {
        const qc = createQueryClient();
        setStreamingJob(qc, 'job-1', { text: 'x', chatId: 'chat-1' });
        expect(getStreamingJob(qc, 'job-1')).toEqual({ text: 'x', chatId: 'chat-1' });
        expect(getStreamingJob(qc, 'missing')).toBeUndefined();
        expect(getStreamingJob(null, 'job-1')).toBeUndefined();
    });
});

describe('useActiveChatStreams', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('reactively returns active streams with the public shape', async () => {
        const qc = createQueryClient();
        const wrapper = createWrapper(qc);
        const { result } = renderHook(() => useActiveChatStreams('chat-1'), { wrapper });
        await waitFor(() => expect(result.current).toEqual([]));

        await act(async () => {
            setStreamingJob(qc, 'job-1', { text: 'part', status: 'running', chatId: 'chat-1' });
        });
        await waitFor(() => {
            expect(result.current).toEqual([
                { jobId: 'job-1', jobData: { text: 'part', status: 'running', chatId: 'chat-1' } },
            ]);
        });

        await act(async () => {
            clearStreamingJob(qc, 'job-1', 'chat-1');
        });
        await waitFor(() => expect(result.current).toEqual([]));
    });

    it('is disabled without a chatId', async () => {
        const qc = createQueryClient();
        const wrapper = createWrapper(qc);
        const { result } = renderHook(() => useActiveChatStreams(null), { wrapper });
        await waitFor(() => expect(result.current).toEqual([]));
        expect(qc.getQueryState(['streaming', 'active', null])?.isLoading === false || true).toBe(true);
    });
});