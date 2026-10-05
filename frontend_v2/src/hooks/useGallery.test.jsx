/**
 * The gallery's data layer.
 *
 * `useGallery` was switched from `GET /api/v2/assets` to
 * `GET /api/v2/assets/facet`. That is the highest-traffic data path in the
 * app, so the thing worth pinning is that the switch is *transparent*: the same
 * filters reach the server, the same page shape comes back, and the facet
 * counts are picked off page 1 rather than refetched on every scroll.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useGallery, useAssetDateHistogram } from './useGallery';
import { assetsApi } from '../api';

vi.mock('../api', () => ({
    assetsApi: {
        list: vi.fn(),
        facet: vi.fn(),
        dates: vi.fn(),
    },
    jobsApi: {
        list: vi.fn().mockResolvedValue({ jobs: [] }),
    },
}));

vi.mock('../store/settingsStore', () => ({
    default: (selector) => selector({ settings: { gallery: { itemsPerPage: 24 } } }),
}));

// A FRESH client per test, assigned to a module-level binding that `wrapper`
// reads. Two ways this goes wrong, both of which look exactly like a hook bug:
// building the client inside `wrapper` makes a new one on every render and
// discards the cache each time; sharing one module-level client lets a
// previous test's cache satisfy the next one's first render.
let queryClient;

function wrapper({ children }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
    queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
});

const FACETS = {
    lora: [{ value: '1189691', count: 4, label: 'Some LoRA' }, { value: '999', count: 1, label: null }],
    tag: [{ value: 'blonde hair', count: 4 }],
    checkpoint: [{ value: 'Illustrious', count: 9 }],
};

/**
 * Page one and page two are deliberately DIFFERENT, and page two terminates.
 *
 * Returning the same object for every call made this file lie: react-query's
 * structural sharing (on by default) collapses a page that deep-equals its
 * predecessor, so `data.pages` stayed at length 1 and `pageParams` at `[null]`
 * while the request was plainly issued with the right cursor. A real second
 * page has different items and eventually `has_more: false`, so that is what the
 * mock returns.
 */
function pageFor(cursor) {
    if (!cursor) {
        return {
            items: [{ id: 'a1', filename: 'a.png' }, { id: 'a2', filename: 'b.png' }],
            has_more: true,
            next_cursor: 'cursor-2',
            total_matched: 17,
            facets: FACETS,
        };
    }
    return {
        items: [{ id: 'a3', filename: 'c.png' }],
        has_more: false,
        next_cursor: null,
        total_matched: 17,
        facets: FACETS,
    };
}

beforeEach(() => {
    vi.clearAllMocks();
    assetsApi.facet.mockImplementation(({ cursor } = {}) => Promise.resolve(pageFor(cursor)));
    assetsApi.dates.mockResolvedValue({
        days: [{ day: '2026-09-01', count: 3 }, { day: '2026-09-02', count: 8 }],
        total: 11,
        first_day: '2026-09-01',
        last_day: '2026-09-02',
        day_rule: 'utc',
    });
});

describe('useGallery', () => {
    it('calls the facet endpoint, not the plain listing', async () => {
        const { result } = renderHook(() => useGallery({}), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(assetsApi.facet).toHaveBeenCalledTimes(1);
        expect(assetsApi.list).not.toHaveBeenCalled();
    });

    it('sends the pre-existing filter vocabulary through unchanged', async () => {
        const filters = {
            search: 'lighthouse', workspace: 'main', character_id: 'c1',
            story_id: 'st1', sort: 'date_asc',
        };
        const { result } = renderHook(() => useGallery(filters), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(assetsApi.facet).toHaveBeenCalledWith(
            expect.objectContaining({ ...filters, limit: 24 }),
            { signal: expect.any(AbortSignal) },
        );
    });

    it('sends the facet dimensions, comma-separated', async () => {
        const { result } = renderHook(
            () => useGallery({ lora: '1,2', tag: 'pose: kneeling', checkpoint: 'Flux' }),
            { wrapper },
        );
        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(assetsApi.facet).toHaveBeenCalledWith(
            expect.objectContaining({ lora: '1,2', tag: 'pose: kneeling', checkpoint: 'Flux' }),
            { signal: expect.any(AbortSignal) },
        );
    });

    it('requests at most three facet dimensions', async () => {
        const { result } = renderHook(() => useGallery({}), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        const params = assetsApi.facet.mock.calls[0][0];
        expect(params.group_by.split(',').length).toBeLessThanOrEqual(3);
    });

    it('omits unset filters rather than sending empty strings', async () => {
        // An empty string sent to the server filters on the literal text `""`,
        // which is how "clear the search box" used to return nothing.
        const { result } = renderHook(
            () => useGallery({ search: '', workspace: null, lora: undefined }),
            { wrapper },
        );
        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        const params = assetsApi.facet.mock.calls[0][0];
        expect('search' in params).toBe(false);
        expect('workspace' in params).toBe(false);
        expect('lora' in params).toBe(false);
    });

    it('exposes the counts and the total from page one', async () => {
        const { result } = renderHook(() => useGallery({}), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        const page = result.current.data.pages[0];
        expect(page.facets.lora).toHaveLength(2);
        expect(page.totalMatched).toBe(17);
        // The grid reads `files`; it must be untouched by the switch.
        expect(page.files).toHaveLength(2);
        expect(page.nextPage).toBe('cursor-2');
    });

    it('paginates with the same cursor and stops at has_more=false', async () => {
        const { result } = renderHook(() => useGallery({}), { wrapper });
        await waitFor(() => expect(result.current.hasNextPage).toBe(true));

        // `fetchNextPage` updates state, so it has to run inside `act` or the
        // result is written before the assertion reads it.
        await act(async () => { await result.current.fetchNextPage(); });
        expect(assetsApi.facet.mock.calls[1][0].cursor).toBe('cursor-2');
    });

    it('does not refetch the counts or the jobs on a later page', async () => {
        // The counts cannot have changed between two pages of one scroll, and
        // the jobs are a page-one thing. Asking again costs a round trip per
        // scroll to get numbers that are identical.
        const { result } = renderHook(() => useGallery({}), { wrapper });
        await waitFor(() => expect(result.current.hasNextPage).toBe(true));
        await act(async () => { await result.current.fetchNextPage(); });
        // `act` flushes the update it is told about; the page is stored by the
        // query's own observer, so wait for the observable state rather than
        // reading the hook's snapshot one microtask later.
        await waitFor(() => expect(result.current.data.pages).toHaveLength(2));
        const second = result.current.data.pages[1];
        expect(second.facets).toEqual({});
        expect(second.jobs).toEqual([]);
    });

    it('keeps the jobs alongside the images on page one', async () => {
        const { result } = renderHook(() => useGallery({}), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));
        // `jobsApi.list` is mocked to `[]`; the point is the shape survives.
        expect(result.current.data.pages[0]).toHaveProperty('jobs');
    });

    it('survives a facet response with no facets at all', async () => {
        assetsApi.facet.mockResolvedValue({ items: [], has_more: false });
        const { result } = renderHook(() => useGallery({}), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data.pages[0].facets).toEqual({});
        expect(result.current.hasNextPage).toBe(false);
    });
});

describe('useAssetDateHistogram', () => {
    it('scopes by the listing filters and flattens the response', async () => {
        const { result } = renderHook(
            () => useAssetDateHistogram({ workspace: 'main', search: 'a', lora: '1' }),
            { wrapper },
        );
        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        // `lora` is a facet filter, not a scope filter: a rail scoped to the
        // current selection tells you how much you selected, which is not a
        // navigation aid.
        expect(assetsApi.dates.mock.calls[0][0]).toEqual(
            expect.objectContaining({ workspace: 'main', search: 'a' }),
        );
        expect(assetsApi.dates.mock.calls[0][0].lora).toBeUndefined();
        expect(result.current.data.total).toBe(11);
        expect(result.current.data.days).toHaveLength(2);
    });

    it('copes with an empty library', async () => {
        assetsApi.dates.mockResolvedValue({ days: [], total: 0, first_day: null, last_day: null });
        const { result } = renderHook(() => useAssetDateHistogram({}), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(result.current.data).toMatchObject({ days: [], total: 0, firstDay: null, lastDay: null });
    });
});
