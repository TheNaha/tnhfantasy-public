import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

    it('uses embedded metadata without fetching', () => {
        const { result } = renderHook(() => useSelectedImageState());

        act(() => {
            result.current.selectImage({
                name: 'embedded.png',
                metadata: { prompt: 'embedded' },
            });
        });

        expect(result.current.selectedImage?.name).toBe('embedded.png');
        expect(result.current.metadata).toEqual({ prompt: 'embedded' });
        expect(result.current.loadingMeta).toBe(false);
        expect(mockGet).not.toHaveBeenCalled();
        expect(document.body.style.overflow).toBe('hidden');
    });

    it('loads fallback metadata for legacy images', async () => {
        mockGet.mockResolvedValueOnce({ prompt: 'loaded from api' });

        const { result } = renderHook(() => useSelectedImageState());

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
});
