import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useGalleryAutoRefresh } from './useGalleryAutoRefresh';

describe('useGalleryAutoRefresh', () => {
    let queryClient;

    beforeEach(() => {
        vi.clearAllMocks();
        queryClient = { invalidateQueries: vi.fn() };
    });

    it('invalidates gallery queries for completed jobs with outputs', () => {
        const lastCompletedJob = { id: 'job-1', outputs: [{ filename: 'img.png' }] };

        renderHook(() => useGalleryAutoRefresh({
            lastCompletedJob,
            autoRefreshOnJobComplete: true,
            queryClient,
        }));

        expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
            queryKey: ['gallery'],
        });
    });

    it('does not invalidate for completed jobs without persisted outputs', () => {
        renderHook(() => useGalleryAutoRefresh({
            lastCompletedJob: { id: 'job-2', outputs: [] },
            autoRefreshOnJobComplete: true,
            queryClient,
        }));

        expect(queryClient.invalidateQueries).not.toHaveBeenCalled();
    });

    it('suppresses duplicate invalidation for the same completed job id', () => {
        const completed = { id: 'job-3', outputs: [{ filename: 'x.png' }] };

        const { rerender } = renderHook((props) => useGalleryAutoRefresh(props), {
            initialProps: {
                lastCompletedJob: completed,
                autoRefreshOnJobComplete: true,
                queryClient,
            },
        });

        rerender({
            lastCompletedJob: { ...completed },
            autoRefreshOnJobComplete: true,
            queryClient,
        });

        expect(queryClient.invalidateQueries).toHaveBeenCalledTimes(1);
    });

    it('triggers again when a new completed job id appears', () => {
        const { rerender } = renderHook((props) => useGalleryAutoRefresh(props), {
            initialProps: {
                lastCompletedJob: { id: 'job-4', outputs: [{ filename: 'a.png' }] },
                autoRefreshOnJobComplete: true,
                queryClient,
            },
        });

        rerender({
            lastCompletedJob: { id: 'job-5', outputs: [{ filename: 'b.png' }] },
            autoRefreshOnJobComplete: true,
            queryClient,
        });

        expect(queryClient.invalidateQueries).toHaveBeenCalledTimes(2);
    });

    it('tracks completed jobs but does not invalidate when auto refresh is disabled', () => {
        renderHook(() => useGalleryAutoRefresh({
            lastCompletedJob: { id: 'job-6', outputs: [{ filename: 'x.png' }] },
            autoRefreshOnJobComplete: false,
            queryClient,
        }));

        expect(queryClient.invalidateQueries).not.toHaveBeenCalled();
    });

    it('refreshes for a job that completed while the setting was off', () => {
        const { rerender } = renderHook((props) => useGalleryAutoRefresh(props), {
            initialProps: {
                lastCompletedJob: { id: 'job-7', outputs: [{ filename: 'x.png' }] },
                autoRefreshOnJobComplete: false,
                queryClient,
            },
        });

        expect(queryClient.invalidateQueries).not.toHaveBeenCalled();

        // The id used to be spent before the enablement check, so switching the
        // setting on afterwards left this job permanently un-refreshed.
        rerender({
            lastCompletedJob: { id: 'job-7', outputs: [{ filename: 'x.png' }] },
            autoRefreshOnJobComplete: true,
            queryClient,
        });

        expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['gallery'] });
    });
});
