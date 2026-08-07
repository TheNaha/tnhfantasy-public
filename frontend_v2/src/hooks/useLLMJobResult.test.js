import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
    api: {
        post: vi.fn(),
        get: vi.fn(),
    },
}));

vi.mock('../api/websocket', () => ({
    EventTypes: {
        JOB_COMPLETED: 'job.completed',
        JOB_FAILED: 'job.failed',
        JOB_CANCELLED: 'job.cancelled',
    },
    on: vi.fn(() => () => {}),
}));

describe('useLLMJobResult', () => {
    let api;
    let ws;
    let useLLMJobResult;
    const handlers = {};

    beforeEach(async () => {
        vi.resetModules();

        const apiMod = await import('../api');
        api = apiMod.api;

        const wsMod = await import('../api/websocket');
        ws = wsMod;
        handlers.JOB_COMPLETED = null;
        handlers.JOB_FAILED = null;
        handlers.JOB_CANCELLED = null;
        ws.on.mockImplementation((event, cb) => {
            handlers[event] = cb;
            return () => {};
        });

        const hookMod = await import('./useLLMJobResult');
        useLLMJobResult = hookMod.useLLMJobResult;
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('submits the job and resolves via WebSocket completion', async () => {
        api.post.mockResolvedValue({ id: 'job-1' });

        const { result } = renderHook(() => useLLMJobResult());

        let outcome;
        await act(async () => {
            outcome = result.current({ workflow: { messages: [] } });
            await new Promise((r) => setTimeout(r, 0));
        });
        act(() => {
            handlers[ws.EventTypes.JOB_COMPLETED]({ job: { id: 'job-1', outputs: [{ content: 'Hello' }] } });
        });

        const resolved = await outcome;
        expect(api.post).toHaveBeenCalledWith('/api/jobs', { task_type: 'llm', workflow: { messages: [] } });
        expect(resolved).toEqual({ jobId: 'job-1', text: 'Hello' });
    });

    it('ignores WebSocket events for other jobs', async () => {
        api.post.mockResolvedValue({ id: 'job-1' });
        api.get.mockResolvedValue({ status: 'completed', outputs: [{ content: 'From poll' }] });

        const { result } = renderHook(() => useLLMJobResult());

        let outcome;
        await act(async () => {
            outcome = result.current({ workflow: {} });
            await new Promise((r) => setTimeout(r, 0));
        });
        act(() => {
            handlers[ws.EventTypes.JOB_COMPLETED]({ job: { id: 'other-job', outputs: [{ content: 'nope' }] } });
            handlers[ws.EventTypes.JOB_FAILED]({ job: { id: 'other-job' } });
        });

        const resolved = await outcome;
        expect(resolved).toEqual({ jobId: 'job-1', text: 'From poll' });
    });

    it('resolves via polling fallback when no WS event arrives', async () => {
        api.post.mockResolvedValue({ id: 'job-1' });
        api.get.mockResolvedValue({ status: 'completed', outputs: [{ content: 'From poll' }] });

        const { result } = renderHook(() => useLLMJobResult({ pollInterval: 1000 }));

        let outcome;
        await act(async () => {
            outcome = result.current({ workflow: {} });
        });

        const resolved = await outcome;
        expect(api.get).toHaveBeenCalledWith('/api/jobs/job-1');
        expect(resolved).toEqual({ jobId: 'job-1', text: 'From poll' });
    });

    it('resolves as cancelled when isCancelled() returns true', async () => {
        api.post.mockResolvedValue({ id: 'job-1' });

        const { result } = renderHook(() => useLLMJobResult());

        let outcome;
        await act(async () => {
            outcome = result.current({ workflow: {}, isCancelled: () => true });
        });

        const resolved = await outcome;
        expect(resolved).toEqual({ jobId: 'job-1', text: null, cancelled: true });
    });

    it('rejects when the job fails', async () => {
        api.post.mockResolvedValue({ id: 'job-1' });
        api.get.mockResolvedValue({ status: 'failed' });

        const { result } = renderHook(() => useLLMJobResult());

        await expect(async () => {
            await act(async () => {
                await result.current({ workflow: {} });
            });
        }).rejects.toThrow('LLM job failed');
    });

    it('rejects after maxPolls exhausted', async () => {
        vi.useFakeTimers();
        api.post.mockResolvedValue({ id: 'job-1' });
        api.get.mockResolvedValue({ status: 'pending' });

        const { result } = renderHook(() => useLLMJobResult({ pollInterval: 1000 }));

        let outcome;
        await act(async () => {
            outcome = result.current({ workflow: {}, maxPolls: 2 });
            outcome.catch(() => {});
        });
        await act(async () => {
            await vi.advanceTimersByTimeAsync(2000);
        });

        await expect(outcome).rejects.toThrow('LLM job failed');
    });

    it('rejects when job submission fails', async () => {
        api.post.mockRejectedValue(new Error('boom'));

        const { result } = renderHook(() => useLLMJobResult());

        await expect(async () => {
            await act(async () => {
                await result.current({ workflow: {} });
            });
        }).rejects.toThrow('boom');
    });
});
