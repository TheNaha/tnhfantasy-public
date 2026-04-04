import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const toastMock = vi.hoisted(() => ({
    success: vi.fn(),
}));

vi.mock('react-hot-toast', () => ({
    default: toastMock,
}));

import { useGalleryAutoRefresh } from './useGalleryAutoRefresh';

describe('useGalleryAutoRefresh', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('invalidates gallery queries for completed jobs with outputs', () => {
        const queryClient = { invalidateQueries: vi.fn() };
        const lastCompletedJob = { id: 'job-1', outputs: [{ filename: 'img.png' }] };

        renderHook(() => useGalleryAutoRefresh({
            lastCompletedJob,
            autoRefreshOnJobComplete: true,
            queryClient,
            toastSuccessDuration: 3000,
        }));

        expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
            queryKey: ['gallery'],
        });
        expect(toastMock.success).toHaveBeenCalledWith(
            '🎉 Generation complete! Gallery updated.',
            { duration: 3000 },
        );
    });

    it('does not invalidate for completed jobs without persisted outputs', () => {
        const queryClient = { invalidateQueries: vi.fn() };

        renderHook(() => useGalleryAutoRefresh({
            lastCompletedJob: { id: 'job-2', outputs: [] },
            autoRefreshOnJobComplete: true,
            queryClient,
            toastSuccessDuration: 3000,
        }));

        expect(queryClient.invalidateQueries).not.toHaveBeenCalled();
        expect(toastMock.success).not.toHaveBeenCalled();
    });

    it('suppresses duplicate invalidation for the same completed job id', () => {
        const queryClient = { invalidateQueries: vi.fn() };
        const completed = { id: 'job-3', outputs: [{ filename: 'x.png' }] };

        const { rerender } = renderHook((props) => useGalleryAutoRefresh(props), {
            initialProps: {
                lastCompletedJob: completed,
                autoRefreshOnJobComplete: true,
                queryClient,
                toastSuccessDuration: 3000,
            },
        });

        rerender({
            lastCompletedJob: { ...completed },
            autoRefreshOnJobComplete: true,
            queryClient,
            toastSuccessDuration: 3000,
        });

        expect(queryClient.invalidateQueries).toHaveBeenCalledTimes(1);
        expect(toastMock.success).toHaveBeenCalledTimes(1);
    });

    it('triggers again when a new completed job id appears', () => {
        const queryClient = { invalidateQueries: vi.fn() };

        const { rerender } = renderHook((props) => useGalleryAutoRefresh(props), {
            initialProps: {
                lastCompletedJob: { id: 'job-4', outputs: [{ filename: 'a.png' }] },
                autoRefreshOnJobComplete: true,
                queryClient,
                toastSuccessDuration: 3000,
            },
        });

        rerender({
            lastCompletedJob: { id: 'job-5', outputs: [{ filename: 'b.png' }] },
            autoRefreshOnJobComplete: true,
            queryClient,
            toastSuccessDuration: 3000,
        });

        expect(queryClient.invalidateQueries).toHaveBeenCalledTimes(2);
        expect(toastMock.success).toHaveBeenCalledTimes(2);
    });

    it('tracks completed jobs but does not invalidate when auto refresh is disabled', () => {
        const queryClient = { invalidateQueries: vi.fn() };

        renderHook(() => useGalleryAutoRefresh({
            lastCompletedJob: { id: 'job-6', outputs: [{ filename: 'x.png' }] },
            autoRefreshOnJobComplete: false,
            queryClient,
            toastSuccessDuration: 3000,
        }));

        expect(queryClient.invalidateQueries).not.toHaveBeenCalled();
        expect(toastMock.success).not.toHaveBeenCalled();
    });
});
