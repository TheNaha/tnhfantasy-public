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
