import { act, waitFor } from '@testing-library/react';
import { renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useJobRecovery } from './useJobRecovery';

vi.mock('../api', () => ({
    jobsApi: {
        getFailed: vi.fn(),
        retry: vi.fn(),
        cancel: vi.fn(),
        recover: vi.fn(),
    },
}));

vi.mock('react-hot-toast', () => ({
    default: {
        success: vi.fn(),
        error: vi.fn(),
    },
}));

function makeWrapper() {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const wrapper = ({ children }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { queryClient, wrapper };
}

const FAILED_JOB = {
    id: 'job-1',
    task_type: 'image',
    status: 'failed',
    error: 'All providers failed: p1',
    provider_id: 'p1',
    metadata: { prompt: 'a cat', checkpoint: 'dreamshaper.safetensors' },
    diagnostics: {
        provider_id: 'p1',
        last_provider_id: 'p1',
        model: 'dreamshaper.safetensors',
        attempt_count: 2,
        attempts: [
            { provider_id: 'p1', attempt: 1, outcome: 'timeout', error: 'provider hung', duration_seconds: 30 },
            { provider_id: 'p1', attempt: 2, outcome: 'error', error: 'OutOfMemory', duration_seconds: 12 },
        ],
        error_type: 'providers_exhausted',
        error_message: 'All providers failed: p1',
        duration_seconds: 42.5,
        is_stale: false,
        is_retryable: true,
        retry_of: null,
    },
};

describe('useJobRecovery', () => {
    let jobsApi;

    beforeEach(async () => {
        vi.clearAllMocks();
        const apiMod = await import('../api');
        jobsApi = apiMod.jobsApi;
    });

    it('exposes failed jobs and the page summary', async () => {
        jobsApi.getFailed.mockResolvedValue({
            jobs: [FAILED_JOB],
            total: 1,
            summary: { by_error_type: { providers_exhausted: 1 }, retryable: 1 },
        });
        const { wrapper } = makeWrapper();

        const { result } = renderHook(() => useJobRecovery(), { wrapper });

        await waitFor(() => expect(result.current.jobs).toHaveLength(1));
        expect(result.current.total).toBe(1);
        expect(result.current.summary.by_error_type).toEqual({ providers_exhausted: 1 });
        expect(jobsApi.getFailed).toHaveBeenCalledWith({ limit: 10, taskType: null });
    });

    it('defaults to an empty list when the payload is malformed', async () => {
        jobsApi.getFailed.mockResolvedValue({});
        const { wrapper } = makeWrapper();

        const { result } = renderHook(() => useJobRecovery(), { wrapper });

        await waitFor(() => expect(result.current.jobs).toEqual([]));
        expect(result.current.total).toBe(0);
        expect(result.current.summary).toBeNull();
    });

    it('passes limit and task type through to the API', async () => {
        jobsApi.getFailed.mockResolvedValue({ jobs: [], total: 0 });
        const { wrapper } = makeWrapper();

        renderHook(() => useJobRecovery({ limit: 25, taskType: 'llm' }), { wrapper });

        await waitFor(() =>
            expect(jobsApi.getFailed).toHaveBeenCalledWith({ limit: 25, taskType: 'llm' })
        );
    });

    it('does not fetch when disabled', async () => {
        const { wrapper } = makeWrapper();

        renderHook(() => useJobRecovery({ enabled: false }), { wrapper });

        await new Promise((resolve) => setTimeout(resolve, 10));
        expect(jobsApi.getFailed).not.toHaveBeenCalled();
    });

    it('retry invalidates the job and gallery caches', async () => {
        jobsApi.getFailed.mockResolvedValue({ jobs: [], total: 0 });
        jobsApi.retry.mockResolvedValue({ status: 'success', new_job_id: 'job-2' });
        const { queryClient, wrapper } = makeWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

        const { result } = renderHook(() => useJobRecovery(), { wrapper });
        await waitFor(() => expect(result.current.jobs).toEqual([]));
        invalidate.mockClear();

        await act(async () => {
            await result.current.retryJob('job-1');
        });

        expect(jobsApi.retry).toHaveBeenCalledWith('job-1');
        const invalidatedKeys = invalidate.mock.calls.map((call) => call[0].queryKey);
        expect(invalidatedKeys).toContainEqual(['jobs']);
        expect(invalidatedKeys).toContainEqual(['gallery']);
    });

    it('surfaces retry errors to the caller', async () => {
        jobsApi.getFailed.mockResolvedValue({ jobs: [], total: 0 });
        jobsApi.retry.mockRejectedValue(new Error('Only failed jobs can be retried'));
        const { wrapper } = makeWrapper();

        const { result } = renderHook(() => useJobRecovery(), { wrapper });
        await waitFor(() => expect(result.current.jobs).toEqual([]));

        await expect(result.current.retryJob('job-1')).rejects.toThrow(
            'Only failed jobs can be retried'
        );
    });

    it('cancel passes the reason through', async () => {
        jobsApi.getFailed.mockResolvedValue({ jobs: [], total: 0 });
        jobsApi.cancel.mockResolvedValue({ status: 'success', job_status: 'cancelled' });
        const { wrapper } = makeWrapper();

        const { result } = renderHook(() => useJobRecovery(), { wrapper });
        await waitFor(() => expect(result.current.jobs).toEqual([]));

        await act(async () => {
            await result.current.cancelJob('job-1', 'user stopped it');
        });

        expect(jobsApi.cancel).toHaveBeenCalledWith('job-1', 'user stopped it');
    });

    it('recover returns the server summary', async () => {
        jobsApi.getFailed.mockResolvedValue({ jobs: [], total: 0 });
        jobsApi.recover.mockResolvedValue({
            status: 'success',
            recovered: 2,
            failed: 1,
            failed_job_ids: ['job-9'],
        });
        const { wrapper } = makeWrapper();

        const { result } = renderHook(() => useJobRecovery(), { wrapper });
        await waitFor(() => expect(result.current.jobs).toEqual([]));

        let summary;
        await act(async () => {
            summary = await result.current.recoverJobs();
        });

        expect(summary.recovered).toBe(2);
        expect(jobsApi.recover).toHaveBeenCalledWith({});
        await waitFor(() => expect(result.current.recoverySummary.failed_job_ids).toEqual(['job-9']));
    });
});
