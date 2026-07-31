import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const { mockGet } = vi.hoisted(() => ({
    mockGet: vi.fn(),
}));

vi.mock('../api', () => {
    class MockApiError extends Error {
        constructor(status) {
            super(`status ${status}`);
            this.status = status;
        }
    }

    return {
        api: {
            get: mockGet,
        },
        ApiError: MockApiError,
    };
});

import { useSelectedImageState } from './useSelectedImageState';

describe('useSelectedImageState', () => {
    beforeEach(() => {
        mockGet.mockReset();
        document.body.style.overflow = 'unset';
    });

    afterEach(() => {
        document.body.style.overflow = 'unset';
    });


    const createWrapper = () => {
        const queryClient = new QueryClient({
            defaultOptions: { queries: { retry: false } },
        });
        return ({ children }) => React.createElement(QueryClientProvider, { client: queryClient }, children);
    };

    it('uses embedded metadata immediately and refreshes from sidecar metadata', async () => {
        mockGet.mockResolvedValueOnce({ prompt: 'sidecar', width: 768 });

        const { result } = renderHook(() => useSelectedImageState(), { wrapper: createWrapper() });

        act(() => {
            result.current.selectImage({
                name: 'embedded.png',
                metadata: { prompt: 'embedded', loras: [{ name: 'test-lora', strength: 1.0 }] },
            });
        });

        expect(result.current.selectedImage?.name).toBe('embedded.png');
        expect(result.current.metadata).toEqual({ prompt: 'embedded', loras: [{ name: 'test-lora', strength: 1.0 }] });
        expect(result.current.loadingMeta).toBe(true);

        await waitFor(() => {
            expect(result.current.metadata).toEqual({
                prompt: 'sidecar',
                width: 768,
                loras: [{ name: 'test-lora', strength: 1.0 }],
            });
        });

        expect(result.current.loadingMeta).toBe(false);
        expect(mockGet).toHaveBeenCalledWith('/api/view/output/embedded.png.json');
        expect(document.body.style.overflow).toBe('hidden');
    });

    it('loads fallback metadata for legacy images', async () => {
        mockGet.mockResolvedValueOnce({ prompt: 'loaded from api' });

        const { result } = renderHook(() => useSelectedImageState(), { wrapper: createWrapper() });

        act(() => {
            result.current.selectImage({
                name: 'legacy.png',
                metadata: {},
            });
        });

        expect(result.current.loadingMeta).toBe(true);

        await waitFor(() => {
            expect(result.current.metadata).toEqual({ prompt: 'loaded from api' });
        });

        expect(result.current.loadingMeta).toBe(false);
        expect(mockGet).toHaveBeenCalledWith('/api/view/output/legacy.png.json');

        act(() => {
            result.current.closeSelectedImage();
        });

        expect(result.current.selectedImage).toBe(null);
        expect(result.current.metadata).toBe(null);
        expect(document.body.style.overflow).toBe('unset');
    });

    it('keeps embedded metadata when sidecar is missing', async () => {
        const { ApiError } = await import('../api');
        mockGet.mockRejectedValueOnce(new ApiError(404));

        const { result } = renderHook(() => useSelectedImageState(), { wrapper: createWrapper() });

        act(() => {
            result.current.selectImage({
                name: 'embedded-only.png',
                metadata: { prompt: 'embedded only' },
            });
        });

        await waitFor(() => {
            expect(result.current.loadingMeta).toBe(false);
        });

        expect(result.current.metadata).toEqual({ prompt: 'embedded only' });
        expect(mockGet).toHaveBeenCalledWith('/api/view/output/embedded-only.png.json');
    });
});
