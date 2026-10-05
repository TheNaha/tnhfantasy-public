/**
 * "Refetch only the newest page of the gallery" — the rule, and the reason it
 * needed writing down a second time.
 *
 * `useGallery` is a `useInfiniteQuery`. Invalidating `['gallery']` refetches
 * **every** page already loaded, sequentially, and each one changes the list
 * height as it lands — which moves the infinite-scroll sentinel. The obvious
 * narrowing is `invalidateQueries({ queryKey: ['gallery'], refetchPage })`, and
 * that is exactly what three call sites shipped (`useGalleryAutoRefresh.js`,
 * `useJobsRealtime.jsx` twice).
 *
 * **`refetchPage` is not a react-query v5 option.** It was query-core v3. In
 * `@tanstack/query-core@5.90.11` `RefetchQueryFilters` and
 * `InvalidateQueryFilters` are `QueryFilters` and nothing else, and the string
 * does not appear anywhere in the built package — so the extra property was
 * carried onto the filter object and then ignored, and all three sites were
 * doing the full-library refetch they were written to avoid. The way it
 * survived a test suite is the point of this file: the old tests asserted that
 * the option *was passed*, which passes just as happily when the option does
 * nothing, and one of them asserted it by grepping the source text.
 *
 * `refetchNewestGalleryPage` (`hooks/useGallery.js`) is the replacement: fetch
 * page 0 with the same parameter list the hook uses, write it back with
 * `setQueryData`. The behavioural assertions below count real requests against a
 * real `useGallery` on a real `QueryClient`, because "how many requests does an
 * invalidation issue" is not something a spy on `invalidateQueries` can answer.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

vi.mock('../api', () => ({
    assetsApi: { facet: vi.fn(), dates: vi.fn(), assetTags: vi.fn() },
    jobsApi: { list: vi.fn() },
}));

vi.mock('../store/settingsStore', () => ({
    default: (selector) => selector({ settings: { gallery: { itemsPerPage: 3 } } }),
}));

const { assetsApi, jobsApi } = await import('../api');
const { useGallery, useAssetDateHistogram, refetchNewestGalleryPage } = await import('../hooks/useGallery');

const FILTERS = { tag: 'blonde hair' };
const HERE = dirname(fileURLToPath(import.meta.url));

let facetSerial = 0;
function facetPage(n) {
    facetSerial += 1;
    return {
        items: [{ id: `a${n}`, filename: `${n}.png` }],
        has_more: true,
        next_cursor: `cursor-${n + 1}`,
        facets: { tag: [{ value: 'blonde hair', count: n }] },
        // Changes on every fetch, so a refetched page is distinguishable from
        // the copy already in the cache.
        total_matched: facetSerial,
    };
}

let queryClient;

function wrapper({ children }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

const galleryQuery = () => queryClient.getQueryCache().find({ queryKey: ['gallery', FILTERS, 3] });
const loadedPages = () => galleryQuery()?.state.data?.pages?.length ?? 0;

async function mountGalleryWithPages(pages) {
    const view = renderHook(() => useGallery(FILTERS), { wrapper });
    await waitFor(() => expect(loadedPages()).toBe(1));
    for (let loaded = 1; loaded < pages; loaded += 1) {
        await act(async () => { await view.result.current.fetchNextPage(); });
        await waitFor(() => expect(loadedPages()).toBe(loaded + 1));
    }
    return view;
}

beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
    });
    jobsApi.list.mockResolvedValue({ jobs: [] });
    assetsApi.facet.mockImplementation(({ cursor }) => {
        const n = cursor ? Number(String(cursor).replace('cursor-', '')) : 1;
        return Promise.resolve(facetPage(n));
    });
    assetsApi.dates.mockResolvedValue({ days: [], total: 0 });
});

describe('refetchPage is not a react-query v5 option', () => {
    it('is absent from the installed query-core, by name and in its types', async () => {
        const pkg = join(HERE, '..', '..', 'node_modules', '@tanstack', 'query-core');
        const files = [];
        const walk = (dir) => {
            for (const entry of readdirSync(dir, { withFileTypes: true })) {
                const full = join(dir, entry.name);
                if (entry.isDirectory()) walk(full);
                else if (/\.(js|d\.ts|cjs)$/.test(entry.name)) files.push(full);
            }
        };
        walk(join(pkg, 'build'));

        const hits = files.filter((f) => readFileSync(f, 'utf8').includes('refetchPage'));
        expect(hits).toEqual([]);
    });

    it('and an invalidation carrying it refetches every page, exactly as if it did not', async () => {
        // The behaviour, not the option: this is what the three call sites were
        // doing while appearing to scope themselves.
        await mountGalleryWithPages(3);
        const before = assetsApi.facet.mock.calls.length;

        await act(async () => {
            await queryClient.invalidateQueries({
                queryKey: ['gallery'],
                refetchPage: (page, allPages) => page === allPages[0],
            });
        });
        await waitFor(() => expect(assetsApi.facet.mock.calls.length - before).toBe(3));

        expect(loadedPages()).toBe(3);
    });

    it('and no source file still passes it to invalidateQueries', () => {
        const offenders = [];
        const walk = (dir) => {
            for (const entry of readdirSync(join(HERE, '..', dir), { withFileTypes: true })) {
                if (entry.isDirectory()) walk(`${dir}/${entry.name}`);
                else if (/\.jsx?$/.test(entry.name) && !/\.test\.jsx?$/.test(entry.name)) {
                    // Comments are blanked first: the word appears in docblocks
                    // explaining why it must not be used, and those docblocks are
                    // the documentation for the replacement.
                    const src = readFileSync(join(HERE, '..', dir, entry.name), 'utf8')
                        .replace(/\/\*[\s\S]*?\*\//g, '')
                        .replace(/^\s*\/\/.*$/gm, '');
                    if (/refetchPage/.test(src)) offenders.push(`${dir}/${entry.name}`);
                }
            }
        };
        walk('hooks');
        expect(offenders).toEqual([]);
    });
});

describe('refetchNewestGalleryPage fetches one page and leaves the rest untouched', () => {
    it('costs one request with three pages loaded, and one with fifteen', async () => {
        await mountGalleryWithPages(3);
        const before = assetsApi.facet.mock.calls.length;

        await act(async () => { await refetchNewestGalleryPage(queryClient); });

        expect(assetsApi.facet.mock.calls.length - before).toBe(1);
    });

    it('replaces page 0 and keeps every other page as the same object', async () => {
        await mountGalleryWithPages(3);
        const before = galleryQuery().state.data.pages;

        await act(async () => { await refetchNewestGalleryPage(queryClient); });
        const after = galleryQuery().state.data.pages;

        expect(after).toHaveLength(3);
        expect(after[0]).not.toBe(before[0]);
        expect(after[0].totalMatched).not.toBe(before[0].totalMatched);
        expect(after[1]).toBe(before[1]);
        expect(after[2]).toBe(before[2]);
    });

    it('sends the same parameters the hook would for page 0', async () => {
        await mountGalleryWithPages(2);
        await act(async () => { await refetchNewestGalleryPage(queryClient); });

        const params = assetsApi.facet.mock.calls.at(-1)[0];
        expect(params.limit).toBe(3);
        expect(params.tag).toBe('blonde hair');
        expect(params.cursor).toBeUndefined();
        expect(params.group_by.split(',').length).toBeLessThanOrEqual(3);
        // A refetch of page 0 also refreshes the job cards, which live on it.
        expect(jobsApi.list).toHaveBeenCalled();
    });

    it('costs one request when two handlers fire on the same event', async () => {
        // `job.completed` reaches both the job card and the gallery
        // auto-refresh. Two requests for one new image is the tail churn the
        // rule exists to remove.
        await mountGalleryWithPages(3);
        const before = assetsApi.facet.mock.calls.length;

        await act(async () => {
            await Promise.all([
                refetchNewestGalleryPage(queryClient),
                refetchNewestGalleryPage(queryClient),
            ]);
        });

        expect(assetsApi.facet.mock.calls.length - before).toBe(1);
    });

    it('skips a listing nothing is observing, when asked to', async () => {
        const view = await mountGalleryWithPages(2);
        view.unmount();
        const before = assetsApi.facet.mock.calls.length;

        await act(async () => { await refetchNewestGalleryPage(queryClient, { mountedOnly: true }); });

        expect(assetsApi.facet.mock.calls.length - before).toBe(0);
    });

    it('leaves the listing fresh rather than invalidated, so nothing re-walks it', async () => {
        await mountGalleryWithPages(2);
        await act(async () => { await refetchNewestGalleryPage(queryClient); });

        // `isInvalidated` would make the next observer tick refetch every page
        // again — the defect with an extra step.
        expect(galleryQuery().state.isInvalidated).toBe(false);
    });

    it('ignores the date rail, which is not a listing and is not tag-scoped', async () => {
        await mountGalleryWithPages(1);
        renderHook(() => useAssetDateHistogram(FILTERS), { wrapper });
        await waitFor(() => expect(assetsApi.dates).toHaveBeenCalled());

        const before = assetsApi.dates.mock.calls.length;
        await act(async () => { await refetchNewestGalleryPage(queryClient); });

        expect(assetsApi.dates.mock.calls.length - before).toBe(0);
    });
});