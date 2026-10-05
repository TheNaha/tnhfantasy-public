import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';

/**
 * One finished job must cost one request, not one per loaded page.
 *
 * `useGalleryAutoRefresh` exists so that a completed job refreshes the NEWEST
 * page of the gallery instead of walking every page the user has scrolled. It
 * chose its branch with `galleryQueryKey?.length === 1`, on the reasoning that
 * only the bare `['gallery']` root means "the whole library".
 *
 * That made the scoped branch unreachable in production. The only caller builds
 * a two-element key:
 *
 *     // pages/Dashboard.jsx
 *     const galleryQueryKey = useMemo(() => ['gallery', filters], [filters]);
 *
 * and a reader sweep over `src/` found zero bare-root call sites. So every
 * finished job fell through to `invalidateQueries({ queryKey: ['gallery',
 * filters] })` — the full-library page walk the hook was written to prevent.
 * Three loaded pages, three requests, for one job.
 *
 * `refetchNewestGalleryPage` was never the problem: it takes the `['gallery']`
 * prefix and destructures `const [, filters, limit] = query.queryKey`, so the
 * filtered key is exactly the shape it was written for.
 *
 * The pre-existing test passed throughout because it mocked `./useGallery`
 * wholesale and exercised the branch with a narrowed one-element key — the shape
 * production does not use. This one mocks the API instead, so the real
 * `refetchNewestGalleryPage` runs.
 */

vi.mock('../../api', () => ({
    assetsApi: { facet: vi.fn() },
    jobsApi: { list: vi.fn() },
}));

vi.mock('../../store/settingsStore', () => ({
    default: () => ({ galleryImagesFirst: false, galleryGroupBy: null }),
}));

import { assetsApi, jobsApi } from '../../api';
import { useGalleryAutoRefresh } from '../../hooks/useGalleryAutoRefresh';

const FILTERS = { sort: 'date_desc' };
// The exact shape pages/Dashboard.jsx:259 builds.
const KEY = ['gallery', FILTERS, 25];

const PAGE = (id) => ({ files: [{ id, name: id }], jobs: [], nextPage: null });

const COMPLETED_JOB = { id: 'job-1', outputs: [{ filename: 'img.png' }] };

function threeLoadedPages() {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(KEY, {
        pages: [PAGE('a'), PAGE('b'), PAGE('c')],
        pageParams: [null, 'a', 'b'],
    });
    return queryClient;
}

describe('a completed job refreshes the newest page only', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        assetsApi.facet.mockResolvedValue({ items: [{ id: 'new', name: 'new' }], facets: {} });
        jobsApi.list.mockResolvedValue({ jobs: [] });
    });

    it('issues one request, for page 0, not one per loaded page', async () => {
        const queryClient = threeLoadedPages();

        renderHook(() =>
            useGalleryAutoRefresh({
                lastCompletedJob: COMPLETED_JOB,
                autoRefreshOnJobComplete: true,
                galleryQueryKey: KEY,
                queryClient,
            })
        );

        await waitFor(() => expect(assetsApi.facet).toHaveBeenCalled());

        // Before the fix: the length === 1 guard was false for this key, so the
        // hook fell through to invalidateQueries and every loaded page refetched.
        expect(assetsApi.facet).toHaveBeenCalledTimes(1);
        // Page 0 omits `cursor` entirely; later pages send it.
        expect(assetsApi.facet.mock.calls[0][0].cursor).toBeUndefined();
    });

    it('replaces page 0 and leaves the tail of the listing alone', async () => {
        const queryClient = threeLoadedPages();

        renderHook(() =>
            useGalleryAutoRefresh({
                lastCompletedJob: COMPLETED_JOB,
                autoRefreshOnJobComplete: true,
                galleryQueryKey: KEY,
                queryClient,
            })
        );

        await waitFor(() => {
            expect(queryClient.getQueryData(KEY).pages[0].files[0].id).toBe('new');
        });

        const data = queryClient.getQueryData(KEY);
        expect(data.pages).toHaveLength(3);
        expect(data.pages[1].files[0].id).toBe('b');
        expect(data.pages[2].files[0].id).toBe('c');
    });

    it('does nothing when auto-refresh is off', async () => {
        const queryClient = threeLoadedPages();

        renderHook(() =>
            useGalleryAutoRefresh({
                lastCompletedJob: COMPLETED_JOB,
                autoRefreshOnJobComplete: false,
                galleryQueryKey: KEY,
                queryClient,
            })
        );

        await new Promise((resolve) => setTimeout(resolve, 50));
        expect(assetsApi.facet).not.toHaveBeenCalled();
    });

    it('does not re-refresh for the same job id', async () => {
        const queryClient = threeLoadedPages();

        const { rerender } = renderHook(() =>
            useGalleryAutoRefresh({
                lastCompletedJob: COMPLETED_JOB,
                autoRefreshOnJobComplete: true,
                galleryQueryKey: KEY,
                queryClient,
            })
        );
        await waitFor(() => expect(assetsApi.facet).toHaveBeenCalledTimes(1));

        rerender();
        rerender();
        await new Promise((resolve) => setTimeout(resolve, 50));

        expect(assetsApi.facet).toHaveBeenCalledTimes(1);
    });
});