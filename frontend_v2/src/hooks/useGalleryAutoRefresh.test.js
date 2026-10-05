/**
 * The auto-refresh decision table for a finished image job.
 *
 * The one thing that changed here is *how* the gallery is refreshed. The old
 * test asserted `invalidateQueries({ queryKey: ['gallery'], refetchPage })` —
 * i.e. that the option was passed. `refetchPage` is not a react-query v5 option
 * (`InvalidateQueryFilters` carries no such member in
 * `@tanstack/query-core@5.90.11`), so that assertion passed while the full-library
 * refetch it was written to prevent was what actually happened. The behaviour is
 * now covered by request counts in `src/test/galleryNewestPageRefresh.test.jsx`;
 * what is left to pin here is the decision table — when a completed job triggers
 * a refresh at all, and when it does not.
 */
import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useGalleryAutoRefresh } from './useGalleryAutoRefresh';

const refreshMock = vi.hoisted(() => vi.fn());
vi.mock('./useGallery', () => ({ refetchNewestGalleryPage: refreshMock }));

describe('useGalleryAutoRefresh', () => {
    let queryClient;

    beforeEach(() => {
        vi.clearAllMocks();
        refreshMock.mockResolvedValue(1);
        queryClient = { invalidateQueries: vi.fn() };
    });

    it('refreshes the gallery for completed jobs with outputs', () => {
        const lastCompletedJob = { id: 'job-1', outputs: [{ filename: 'img.png' }] };

        renderHook(() => useGalleryAutoRefresh({
            lastCompletedJob,
            autoRefreshOnJobComplete: true,
            queryClient,
        }));

        // Not an invalidation: `useGallery` is a `useInfiniteQuery`, so
        // invalidating `['gallery']` refetches every loaded page, sequentially,
        // and each one changes the list height — which moves the sentinel, which
        // is most of what people mean by "a job update sets off the infinite
        // scroll".
        expect(refreshMock).toHaveBeenCalledWith(queryClient);
        expect(queryClient.invalidateQueries).not.toHaveBeenCalled();
    });

    it('does not refresh for completed jobs without persisted outputs', () => {
        renderHook(() => useGalleryAutoRefresh({
            lastCompletedJob: { id: 'job-2', outputs: [] },
            autoRefreshOnJobComplete: true,
            queryClient,
        }));

        expect(refreshMock).not.toHaveBeenCalled();
        expect(queryClient.invalidateQueries).not.toHaveBeenCalled();
    });

    it('suppresses duplicate refresh for the same completed job id', () => {
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

        expect(refreshMock).toHaveBeenCalledTimes(1);
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

        expect(refreshMock).toHaveBeenCalledTimes(2);
    });

    it('tracks completed jobs but does not refresh when auto refresh is disabled', () => {
        renderHook(() => useGalleryAutoRefresh({
            lastCompletedJob: { id: 'job-6', outputs: [{ filename: 'x.png' }] },
            autoRefreshOnJobComplete: false,
            queryClient,
        }));

        expect(refreshMock).not.toHaveBeenCalled();
    });

    it('refreshes for a job that completed while the setting was off', () => {
        const { rerender } = renderHook((props) => useGalleryAutoRefresh(props), {
            initialProps: {
                lastCompletedJob: { id: 'job-7', outputs: [{ filename: 'x.png' }] },
                autoRefreshOnJobComplete: false,
                queryClient,
            },
        });

        expect(refreshMock).not.toHaveBeenCalled();

        // The id used to be spent before the enablement check, so switching the
        // setting on afterwards left this job permanently un-refreshed.
        rerender({
            lastCompletedJob: { id: 'job-7', outputs: [{ filename: 'x.png' }] },
            autoRefreshOnJobComplete: true,
            queryClient,
        });

        expect(refreshMock).toHaveBeenCalledTimes(1);
    });

    it('falls back to an ordinary invalidation for a narrowed, non-listing key', () => {
        renderHook(() => useGalleryAutoRefresh({
            lastCompletedJob: { id: 'job-8', outputs: [{ filename: 'x.png' }] },
            autoRefreshOnJobComplete: true,
            queryClient,
            galleryQueryKey: ['gallery', { tag: 'x' }, 20],
        }));

        expect(refreshMock).not.toHaveBeenCalled();
        expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['gallery', { tag: 'x' }, 20] });
    });
});