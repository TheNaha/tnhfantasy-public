import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const toastMock = vi.hoisted(() => ({
    error: vi.fn(),
}));

vi.mock('react-hot-toast', () => ({
    default: toastMock,
}));

vi.mock('../api', () => ({
    filesApi: {
        list: vi.fn(),
    },
}));

function createWrapper(queryClient) {
    return function Wrapper({ children }) {
        return React.createElement(QueryClientProvider, { client: queryClient }, children);
    };
}

describe('useModelDirectories', () => {
    let filesApi;
    let useModelDirectories;

    beforeEach(async () => {
        vi.resetModules();
        toastMock.error.mockReset();

        const apiMod = await import('../api');
        filesApi = apiMod.filesApi;

        const hookMod = await import('./useModelDirectories');
        useModelDirectories = hookMod.useModelDirectories;
    });

    it('loads directories and maps results by request key', async () => {
        filesApi.list
            .mockResolvedValueOnce({ files: [{ name: 'checkpoint-a' }] })
            .mockResolvedValueOnce({ files: [{ name: 'vae-a' }] });

        const queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
            },
        });

        const requests = [
            { key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' },
            { key: 'vaeModels', directory: 'models/vae', label: 'VAE models' },
        ];

        const { result } = renderHook(() => useModelDirectories(requests), {
            wrapper: createWrapper(queryClient),
        });

        await waitFor(() => {
            expect(result.current.loading).toBe(false);
        });

        expect(result.current.modelsByKey.checkpoints).toEqual([{ name: 'checkpoint-a' }]);
        expect(result.current.modelsByKey.vaeModels).toEqual([{ name: 'vae-a' }]);
        expect(result.current.error).toBeNull();
        expect(filesApi.list).toHaveBeenCalledTimes(2);
    });

    it('reuses cached per-directory queries across consumers', async () => {
        filesApi.list.mockResolvedValue({ files: [{ name: 'checkpoint-a' }] });

        const queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
            },
        });

        const requests = [
            { key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' },
        ];

        const first = renderHook(() => useModelDirectories(requests), {
            wrapper: createWrapper(queryClient),
        });

        await waitFor(() => {
            expect(first.result.current.loading).toBe(false);
        });

        filesApi.list.mockClear();

        const second = renderHook(() => useModelDirectories(requests), {
            wrapper: createWrapper(queryClient),
        });

        await waitFor(() => {
            expect(second.result.current.loading).toBe(false);
        });

        expect(filesApi.list).not.toHaveBeenCalled();
    });

    it('hands every consumer the same modelsByKey object across re-renders', async () => {
        filesApi.list.mockResolvedValue({ files: [{ name: 'checkpoint-a' }] });

        const queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
            },
        });

        const requests = [
            { key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' },
        ];

        // A parent re-render with nothing about the data changing: the shape
        // that used to hand out a new object every time, because `useQueries`
        // without `combine` returns a fresh result array per render and both
        // memos depended on it.
        const { result, rerender } = renderHook((props) => {
            void props;
            return useModelDirectories(requests);
        }, {
            wrapper: createWrapper(queryClient),
            initialProps: 0,
        });

        await waitFor(() => {
            expect(result.current.loading).toBe(false);
        });

        const first = result.current.modelsByKey;
        for (let i = 1; i <= 3; i += 1) rerender(i);
        expect(result.current.modelsByKey).toBe(first);
        expect(result.current.error).toBeNull();

        // And once more after the query has settled, for the render that a
        // websocket event or a keystroke elsewhere in the page would cause.
        await new Promise((resolve) => setTimeout(resolve, 10));
        rerender(4);
        expect(result.current.modelsByKey).toBe(first);
    });

    it('returns a new modelsByKey when a directory actually changes', async () => {
        filesApi.list.mockResolvedValue({ files: [{ name: 'checkpoint-a' }] });

        const queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
            },
        });

        const requests = [
            { key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' },
        ];

        const { result } = renderHook(() => useModelDirectories(requests), {
            wrapper: createWrapper(queryClient),
        });

        await waitFor(() => {
            expect(result.current.loading).toBe(false);
        });
        const first = result.current.modelsByKey;

        queryClient.setQueryData(['model-directory', 'models/checkpoints'], [{ name: 'checkpoint-b' }]);

        await waitFor(() => {
            expect(result.current.modelsByKey.checkpoints).toEqual([{ name: 'checkpoint-b' }]);
        });
        expect(result.current.modelsByKey).not.toBe(first);
    });

    it('returns empty arrays for failed directories and reports a single aggregated error toast', async () => {
        filesApi.list.mockRejectedValue(new Error('backend unavailable'));

        const queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
            },
        });

        const requests = [
            { key: 'checkpoints', directory: 'models/checkpoints', label: 'checkpoints' },
        ];

        const { result } = renderHook(() => useModelDirectories(requests), {
            wrapper: createWrapper(queryClient),
        });

        await waitFor(() => {
            expect(result.current.loading).toBe(false);
            expect(result.current.error).not.toBeNull();
        });

        expect(result.current.modelsByKey.checkpoints).toEqual([]);
        expect(result.current.error).toContain('checkpoints');
        expect(toastMock.error).toHaveBeenCalledWith(
            expect.stringContaining('checkpoints'),
            expect.objectContaining({ id: 'model-directories-load-failed' }),
        );
    });
});
