import { renderHook, waitFor, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const toast = {
    error: vi.fn(),
    success: vi.fn(),
};

vi.mock('react-hot-toast', () => ({
    default: toast,
}));

vi.mock('../api', () => ({
    filesApi: {
        list: vi.fn(),
    },
}));

describe('useModels', () => {
    let useModels;
    let filesApi;

    beforeEach(async () => {
        vi.resetModules();
        vi.clearAllMocks();

        vi.mock('react-hot-toast', () => ({
            default: toast,
        }));

        vi.mock('../api', () => ({
            filesApi: {
                list: vi.fn(),
            },
        }));

        ({ useModels } = await import('./useModels'));
        ({ filesApi } = await import('../api'));
    });

    it('keeps successful directories when one model request fails', async () => {
        filesApi.list.mockImplementation(({ directory }) => {
            if (directory === 'models/controlnet') {
                return Promise.reject(new Error('controlnet unavailable'));
            }

            return Promise.resolve({ files: [`${directory}/item.safetensors`] });
        });

        const { result } = renderHook(() => useModels());

        await waitFor(() => expect(result.current.loading).toBe(false));

        expect(result.current.checkpoints).toEqual(['models/checkpoints/item.safetensors']);
        expect(result.current.controlNetModels).toEqual([]);
        expect(result.current.loraModels).toEqual(['models/loras/item.safetensors']);
        expect(result.current.error).toContain('controlnet models');
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('controlnet models'));
    });

    it('reports a full failure when every model directory request fails', async () => {
        filesApi.list.mockRejectedValue(new Error('network unavailable'));

        const { result } = renderHook(() => useModels());

        await waitFor(() => expect(result.current.loading).toBe(false));

        expect(result.current.error).toBe('Failed to load any model directories');
        expect(result.current.checkpoints).toEqual([]);
        expect(toast.error).toHaveBeenCalledWith('Failed to load any model directories');
    });

    it('refreshes successfully without raising an error toast', async () => {
        filesApi.list.mockResolvedValue({ files: ['models/checkpoints/item.safetensors'] });

        const { result } = renderHook(() => useModels());

        await waitFor(() => expect(result.current.loading).toBe(false));

        await act(async () => {
            await result.current.refresh();
        });

        expect(result.current.error).toBeNull();
        expect(toast.success).toHaveBeenCalledWith('Models refreshed');
    });
});