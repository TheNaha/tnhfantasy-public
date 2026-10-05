import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
    jobsApi: {
        getActive: vi.fn(),
        get: vi.fn(),
    },
}));

vi.mock('../api/websocket', () => ({
    on: vi.fn(() => () => {}),
    getConnectionStatus: vi.fn(() => false),
}));

function makeWrapper() {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
    const wrapper = ({ children }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { queryClient, wrapper };
}

describe('useActiveJobs', () => {
    let jobsApi;
    let ws;
    let useActiveJobs;
    const connectionHandlers = [];

    beforeEach(async () => {
        vi.resetModules();
        vi.clearAllMocks();

        const apiMod = await import('../api');
        jobsApi = apiMod.jobsApi;

        const wsMod = await import('../api/websocket');
        ws = wsMod;
        connectionHandlers.length = 0;
        ws.on.mockImplementation((event, cb) => {
            if (event === 'connection') connectionHandlers.push(cb);
            return () => {};
        });

        const hookMod = await import('./useActiveJobs');
        useActiveJobs = hookMod.useActiveJobs;
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('fetches the active jobs list', async () => {
        jobsApi.getActive.mockResolvedValue({ jobs: [{ id: 'j1' }] });
        const { wrapper } = makeWrapper();

        const { result } = renderHook(() => useActiveJobs(), { wrapper });

        await waitFor(() => expect(result.current.data).toEqual([{ id: 'j1' }]));
        expect(jobsApi.getActive).toHaveBeenCalled();
    });

    it('starts polling when the socket disconnects and stops when it reconnects', async () => {
        vi.useFakeTimers();
        jobsApi.getActive.mockResolvedValue({ jobs: [{ id: 'j1' }] });
        // Force non-mobile so the poll gate is entirely connection-driven.
        Object.defineProperty(navigator, 'maxTouchPoints', { value: 0, configurable: true });
        Object.defineProperty(window, 'ontouchstart', { value: undefined, configurable: true });

        const { wrapper } = makeWrapper();
        const { result } = renderHook(() => useActiveJobs(), { wrapper });
        await act(async () => {});
        expect(jobsApi.getActive).toHaveBeenCalledTimes(1);

        // Disconnect -> mobile-style fallback poll kicks in.
        await act(async () => {
            connectionHandlers.forEach((cb) => cb({ connected: false }));
        });
        await act(async () => {
            vi.advanceTimersByTime(2000);
        });
        expect(jobsApi.getActive.mock.calls.length).toBeGreaterThanOrEqual(2);

        // Reconnect -> polling stops. Flush the state update first so React
        // Query re-evaluates the interval and clears the pending timer.
        await act(async () => {
            connectionHandlers.forEach((cb) => cb({ connected: true }));
        });
        const callsBefore = jobsApi.getActive.mock.calls.length;
        await act(async () => {
            vi.advanceTimersByTime(6000);
        });
        expect(jobsApi.getActive.mock.calls.length).toBe(callsBefore);
        expect(result.current.data).toEqual([{ id: 'j1' }]);
    });
});

describe('useJobStatus', () => {
    let jobsApi;
    let ws;
    let useJobStatus;
    const connectionHandlers = [];

    beforeEach(async () => {
        vi.resetModules();
        vi.clearAllMocks();

        const apiMod = await import('../api');
        jobsApi = apiMod.jobsApi;

        const wsMod = await import('../api/websocket');
        ws = wsMod;
        connectionHandlers.length = 0;
        ws.on.mockImplementation((event, cb) => {
            if (event === 'connection') connectionHandlers.push(cb);
            return () => {};
        });

        const hookMod = await import('./useJobStatus');
        useJobStatus = hookMod.useJobStatus;
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('fetches a job by id and exposes its data', async () => {
        jobsApi.get.mockResolvedValue({ job: { id: 'j1', status: 'generating' } });
        const { wrapper } = makeWrapper();

        const { result } = renderHook(() => useJobStatus('j1'), { wrapper });

        await waitFor(() => expect(result.current.data).toEqual({ id: 'j1', status: 'generating' }));
        expect(jobsApi.get).toHaveBeenCalledWith('j1', { signal: expect.any(AbortSignal) });
    });

    it('does not poll while the socket is connected', async () => {
        vi.useFakeTimers();
        ws.getConnectionStatus.mockReturnValue(true);
        jobsApi.get.mockResolvedValue({ job: { id: 'j1', status: 'generating' } });
        const { wrapper } = makeWrapper();

        renderHook(() => useJobStatus('j1'), { wrapper });
        await act(async () => {});

        const callsBefore = jobsApi.get.mock.calls.length;
        await act(async () => {
            vi.advanceTimersByTime(6000);
        });
        expect(jobsApi.get.mock.calls.length).toBe(callsBefore);
    });

    it('polls while disconnected until the job reaches a terminal status', async () => {
        vi.useFakeTimers();
        ws.getConnectionStatus.mockReturnValue(false);
        jobsApi.get
            .mockResolvedValueOnce({ job: { id: 'j1', status: 'generating' } })
            .mockResolvedValue({ job: { id: 'j1', status: 'generating' } });
        const { wrapper } = makeWrapper();

        const { result } = renderHook(() => useJobStatus('j1', { pollInterval: 2000 }), { wrapper });
        await act(async () => {});

        const callsBefore = jobsApi.get.mock.calls.length;
        await act(async () => {
            vi.advanceTimersByTime(4000);
        });
        expect(jobsApi.get.mock.calls.length).toBeGreaterThan(callsBefore);

        // Terminal status -> polling stops.
        jobsApi.get.mockResolvedValue({ job: { id: 'j1', status: 'completed' } });
        await act(async () => {
            vi.advanceTimersByTime(4000);
        });
        const terminalCalls = jobsApi.get.mock.calls.length;
        await act(async () => {
            vi.advanceTimersByTime(6000);
        });
        expect(jobsApi.get.mock.calls.length).toBe(terminalCalls);
        expect(result.current.data.status).toBe('completed');
    });
});
