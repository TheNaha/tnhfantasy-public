import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, QueryObserver } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const handlers = new Map();

vi.mock('react-hot-toast', () => ({
    default: {
        success: vi.fn(),
        error: vi.fn(),
        dismiss: vi.fn(),
    },
}));

vi.mock('../api/websocket', () => ({
    connect: vi.fn(() => Promise.resolve()),
    subscribe: vi.fn(() => Promise.resolve()),
    unsubscribe: vi.fn(),
    on: vi.fn((event, cb) => {
        handlers.set(event, cb);
        return () => handlers.delete(event);
    }),
    getConnectionStatus: vi.fn(() => true),
    requestReplay: vi.fn(() => Promise.resolve([])),
    dispatchReplayEvents: vi.fn(),
    EventTypes: {
        JOB_CREATED: 'job.created',
        JOB_PROGRESS: 'job.progress',
        JOB_UPDATED: 'job.updated',
        JOB_POST_PROCESSING: 'job.post_processing',
        JOB_COMPLETED: 'job.completed',
        JOB_FAILED: 'job.failed',
        JOB_CANCELLED: 'job.cancelled',
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

describe('useJobsRealtime failure cache invalidation', () => {
    let useJobsRealtime;

    beforeEach(async () => {
        vi.clearAllMocks();
        handlers.clear();
        vi.resetModules();
        const hookMod = await import('./useJobsRealtime');
        useJobsRealtime = hookMod.useJobsRealtime;
    });

    it('invalidates the failed-jobs query when a job fails', async () => {
        const { queryClient: client, wrapper } = makeWrapper();
        const invalidate = vi.spyOn(client, 'invalidateQueries');

        renderHook(() => useJobsRealtime(), { wrapper });
        await waitFor(() => expect(handlers.has('job.failed')).toBe(true));
        invalidate.mockClear();

        handlers.get('job.failed')({
            sequence_number: 7,
            data: {
                job: {
                    id: 'job-1',
                    task_type: 'image',
                    status: 'failed',
                    error: 'boom',
                    diagnostics: { error_type: 'provider_error', is_retryable: true },
                },
            },
        });

        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['jobs', 'failed'] });
    });

    it('invalidates the failed-jobs query when a job is cancelled', async () => {
        const { queryClient: client, wrapper } = makeWrapper();
        const invalidate = vi.spyOn(client, 'invalidateQueries');

        renderHook(() => useJobsRealtime(), { wrapper });
        await waitFor(() => expect(handlers.has('job.cancelled')).toBe(true));
        invalidate.mockClear();

        handlers.get('job.cancelled')({
            data: { job: { id: 'job-2', task_type: 'llm', status: 'cancelled' } },
        });

        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['jobs', 'failed'] });
    });

    it('does not invalidate the failed-jobs query on progress events', async () => {
        const { queryClient: client, wrapper } = makeWrapper();
        const invalidate = vi.spyOn(client, 'invalidateQueries');

        renderHook(() => useJobsRealtime(), { wrapper });
        await waitFor(() => expect(handlers.has('job.progress')).toBe(true));
        invalidate.mockClear();

        handlers.get('job.progress')({
            data: { job: { id: 'job-3', task_type: 'image', status: 'generating', overall_progress: 10 } },
        });

        const keys = invalidate.mock.calls.map((call) => call[0].queryKey);
        expect(keys).not.toContainEqual(['jobs', 'failed']);
    });

    it('refreshes the failed-jobs query on reconnect while it is on screen', async () => {
        const { queryClient: client, wrapper } = makeWrapper();
        const invalidate = vi.spyOn(client, 'invalidateQueries');
        const observer = new QueryObserver(client, { queryKey: ['jobs', 'failed'], queryFn: async () => [] });
        const unsubscribe = observer.subscribe(() => {});

        renderHook(() => useJobsRealtime(), { wrapper });
        await waitFor(() => expect(handlers.has('connection')).toBe(true));
        invalidate.mockClear();

        handlers.get('connection')({ connected: true });

        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['jobs', 'failed'] });
        unsubscribe();
    });

    it('does not refetch caches nothing is watching on reconnect', async () => {
        const { queryClient: client, wrapper } = makeWrapper();
        const invalidate = vi.spyOn(client, 'invalidateQueries');

        renderHook(() => useJobsRealtime(), { wrapper });
        await waitFor(() => expect(handlers.has('connection')).toBe(true));
        invalidate.mockClear();

        // A route with no job UI mounted: the 20s watchdog and this reconnect
        // used to fire requests for caches no component is reading.
        handlers.get('connection')({ connected: true });

        expect(invalidate).not.toHaveBeenCalled();
    });
});
