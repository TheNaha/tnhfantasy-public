/**
 * Asset tags: one vocabulary query, one cache key, and a listing refetch that
 * costs one request instead of one per loaded page.
 *
 * Two defects are pinned here.
 *
 *   1. There were two `useTagVocabulary` exports with different signatures
 *      (`(prefix, options)` in `useGallery.js` against `({prefix, q, limit},
 *      options)` here) and different cache keys over the same endpoint. Both
 *      import sites read `import { useTagVocabulary }`, so the object-signature
 *      version silently accepted a bare string — destructuring `'chips'` into
 *      `{0:'c',…}` leaves `prefix`/`q`/`limit` undefined, which is the
 *      *unfiltered* vocabulary, with no error anywhere. The assertions run the
 *      signature against both conventions: the object form must reach the server
 *      as a filtered request, and the positional form must not be able to look
 *      like it worked.
 *   2. A tag edit invalidated bare `['gallery']`, which prefix-matches the
 *      paginated `useGallery` `useInfiniteQuery`: every page already loaded was
 *      refetched, one request per page, for one tag typed. The measurement here
 *      is the real `useGallery` hook against a real `QueryClient`, counting real
 *      facet requests, because a seeded cache entry does not reproduce what a
 *      live infinite query does on invalidation.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
    assetsApi: {
        facet: vi.fn(),
        dates: vi.fn(),
        assetTags: vi.fn(),
        addAssetTag: vi.fn(),
        removeAssetTag: vi.fn(),
        tagVocabulary: vi.fn(),
    },
    jobsApi: { list: vi.fn() },
}));

vi.mock('../store/settingsStore', () => ({
    default: (selector) => selector({ settings: { gallery: { itemsPerPage: 3 } } }),
}));

const { assetsApi, jobsApi } = await import('../api');
const { useGallery } = await import('./useGallery');
const { useTagVocabulary, useAssetTags, useAddAssetTag, useRemoveAssetTag } = await import('./useAssetTags');

const FILTERS = { tag: 'blonde hair' };

/**
 * One facet page.
 *
 * `n` keeps react-query's structural sharing from collapsing consecutive pages,
 * and `serial` makes every *fetch* distinguishable, so a test can tell a
 * refetched page from the one that was already in the cache.
 */
let facetSerial = 0;
function facetPage(n) {
    facetSerial += 1;
    return {
        items: [{ id: `a${n}`, filename: `${n}.png` }],
        has_more: true,
        next_cursor: `cursor-${n + 1}`,
        facets: { tag: [{ value: 'blonde hair', count: n }] },
        // Carried into the hook's page object, so a refetched page 0 is
        // distinguishable from the one that was already cached.
        total_matched: facetSerial,
    };
}

let queryClient;

function wrapper({ children }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
    });
    jobsApi.list.mockResolvedValue({ jobs: [] });
    assetsApi.facet.mockImplementation(({ cursor }) => {
        const n = cursor ? Number(cursor.replace('cursor-', '')) : 1;
        return Promise.resolve(facetPage(n));
    });
    assetsApi.dates.mockResolvedValue({ days: [], total: 0 });
    assetsApi.tagVocabulary.mockResolvedValue({ tags: [{ tag: 'blonde hair', count: 4 }] });
    assetsApi.assetTags.mockResolvedValue({ tags: [] });
    assetsApi.addAssetTag.mockResolvedValue({ created: true });
    assetsApi.removeAssetTag.mockResolvedValue({ removed: true });
});

describe('there is exactly one tag-vocabulary query', () => {
    it('is declared in exactly one file in the hooks directory', async () => {
        // The consolidation is a *name* claim, so it is checked as one: reading
        // the sources is the only way to catch a re-introduced duplicate that
        // no consumer happens to import yet.
        const { readFileSync, readdirSync } = await import('node:fs');
        const { fileURLToPath } = await import('node:url');
        const { dirname, join } = await import('node:path');
        const hooksDir = join(dirname(fileURLToPath(import.meta.url)));

        const declaring = [];
        for (const entry of readdirSync(hooksDir, { withFileTypes: true })) {
            if (!entry.isFile() || !/\.jsx?$/.test(entry.name) || /\.test\.jsx?$/.test(entry.name)) continue;
            const src = readFileSync(join(hooksDir, entry.name), 'utf8');
            if (/export function useTagVocabulary\b/.test(src)) declaring.push(entry.name);
        }
        expect(declaring).toEqual(['useAssetTags.js']);
    });

    it('has exactly one api wrapper for the vocabulary endpoint', async () => {
        const { readFileSync, readdirSync } = await import('node:fs');
        const { fileURLToPath } = await import('node:url');
        const { dirname, join } = await import('node:path');
        const apiDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'api');

        const wrapping = [];
        for (const entry of readdirSync(apiDir, { withFileTypes: true })) {
            if (!entry.isFile() || !/\.jsx?$/.test(entry.name) || /\.test\.jsx?$/.test(entry.name)) continue;
            const src = readFileSync(join(apiDir, entry.name), 'utf8');
            const hits = src.match(/\$\{API_V2_BASE\}\/tags`/g) || [];
            if (hits.length) wrapping.push(`${entry.name} x${hits.length}`);
        }
        expect(wrapping).toEqual(['files.js x1']);
    });

    it('sends an anchored prefix and returns the response the editor reads', async () => {
        const { result } = renderHook(() => useTagVocabulary({ prefix: 'blo', limit: 24 }), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        expect(assetsApi.tagVocabulary.mock.calls[0][0]).toEqual({ prefix: 'blo', q: '', limit: 24 });
        expect(result.current.data).toEqual({ tags: [{ tag: 'blonde hair', count: 4 }] });
    });

    it('is keyed per prefix AND per q, so two typeaheads cannot share a cache entry', async () => {
        renderHook(() => useTagVocabulary({ prefix: 'blo' }), { wrapper });
        await waitFor(() => expect(assetsApi.tagVocabulary).toHaveBeenCalledTimes(1));
        renderHook(() => useTagVocabulary({ q: 'hair' }), { wrapper });
        await waitFor(() => expect(assetsApi.tagVocabulary).toHaveBeenCalledTimes(2));

        const keys = queryClient.getQueryCache().findAll({ queryKey: ['gallery', 'tags'] }).map((q) => q.queryKey);
        expect(keys.sort()).toEqual([
            ['gallery', 'tags', '', 'hair'],
            ['gallery', 'tags', 'blo', ''],
        ]);
    });

    it('cannot be handed a bare string and silently answer with everything', async () => {
        // The footgun, exercised. Destructuring `'chips'` as an options object
        // finds no `prefix`, `q` or `limit` on it, so every default applies and
        // the request is the *unfiltered* vocabulary — the one result set a
        // typeahead must never show for a prefix that matches three tags out of
        // four thousand — and it lands under the unfiltered cache key.
        const { result } = renderHook(() => useTagVocabulary('chips'), { wrapper });
        await waitFor(() => expect(assetsApi.tagVocabulary).toHaveBeenCalled());

        expect(assetsApi.tagVocabulary.mock.calls[0][0]).toEqual({ prefix: '', q: '', limit: 12 });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));

        const keys = queryClient.getQueryCache().findAll({ queryKey: ['gallery', 'tags'] }).map((q) => q.queryKey);
        expect(keys).toEqual([['gallery', 'tags', '', '']]);
        // ...which is the same entry an unprefixed query occupies, so the
        // unfiltered answer is what the next unprefixed query reads back too.
        expect(keys).toContainEqual(['gallery', 'tags', '', '']);
        expect(result.current.data).toEqual({ tags: [{ tag: 'blonde hair', count: 4 }] });
    });

    it('reaches the api with one argument, which is the contract AssetTagEditor.test.jsx pins', async () => {
        // The hook does not forward React Query's signal, because that spec
        // asserts a one-argument call and lives in the components workstream.
        // Recorded here so the trade is visible rather than forgotten.
        renderHook(() => useTagVocabulary({ prefix: 'a' }), { wrapper });
        await waitFor(() => expect(assetsApi.tagVocabulary).toHaveBeenCalled());
        expect(assetsApi.tagVocabulary.mock.calls[0]).toHaveLength(1);
    });
});

describe('one tag edit refetches the newest gallery page, not every loaded page', () => {
    /**
     * The live gallery query, read from the cache rather than from
     * `result.current`. `renderHook`'s handle is only refreshed on a render, and
     * react-query resolves a page inside a promise continuation, so polling the
     * handle races the fetch it is waiting for; the cache is where the pages
     * actually are.
     */
    const galleryQuery = () => queryClient.getQueryCache().find({ queryKey: ['gallery', FILTERS, 3] });
    const loadedPages = () => galleryQuery()?.state.data?.pages?.length ?? 0;

    /** Mount the real gallery and load `pages` pages of it. */
    async function mountGalleryWithPages(pages) {
        const { result } = renderHook(() => useGallery(FILTERS), { wrapper });
        await waitFor(() => expect(loadedPages()).toBe(1));
        for (let loaded = 1; loaded < pages; loaded += 1) {
            await act(async () => { await result.current.fetchNextPage(); });
            await waitFor(() => expect(loadedPages()).toBe(loaded + 1));
        }
        expect(loadedPages()).toBe(pages);
        return { before: assetsApi.facet.mock.calls.length };
    }

    it('costs one request when fifteen pages are loaded, not fifteen', async () => {
        // Three pages stands in for fifteen: the property under test is
        // "requests per loaded page", and the old code's answer was that ratio.
        const { before } = await mountGalleryWithPages(3);

        const { result: mutation } = renderHook(() => useAddAssetTag('a1'), { wrapper });
        await act(async () => { await mutation.current.mutateAsync('new tag'); });
        await waitFor(() => expect(assetsApi.facet.mock.calls.length).toBeGreaterThan(before));

        expect(assetsApi.facet.mock.calls.length - before).toBe(1);
    });

    it('leaves the older pages byte-identical', async () => {
        await mountGalleryWithPages(3);
        const before = galleryQuery().state.data.pages;

        const { result: mutation } = renderHook(() => useAddAssetTag('a1'), { wrapper });
        await act(async () => { await mutation.current.mutateAsync('new tag'); });
        await waitFor(() => expect(assetsApi.facet.mock.calls.length).toBeGreaterThan(3));

        const after = galleryQuery().state.data.pages;
        expect(after).toHaveLength(3);
        expect(after[0]).not.toEqual(before[0]);   // newest page refetched
        expect(after[1]).toBe(before[1]);          // same object: never refetched
        expect(after[2]).toBe(before[2]);
    });

    it('never issues a bare [\'gallery\'] invalidation, which is the whole-library refetch', async () => {
        await mountGalleryWithPages(3);
        const spy = vi.spyOn(queryClient, 'invalidateQueries');

        const { result } = renderHook(() => useAddAssetTag('a1'), { wrapper });
        await act(async () => { await result.current.mutateAsync('new tag'); });

        const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
        expect(keys.filter((k) => k === JSON.stringify(['gallery']))).toEqual([]);
        // The asset's own tags and the vocabulary are invalidated as before.
        expect(keys).toContain(JSON.stringify(['gallery', 'asset', 'a1', 'tags']));
        expect(keys).toContain(JSON.stringify(['gallery', 'tags']));
    });

    it('still refreshes the asset\'s own tags and the vocabulary', async () => {
        renderHook(() => useAssetTags('a1'), { wrapper });
        renderHook(() => useTagVocabulary({ prefix: 'a' }), { wrapper });
        await waitFor(() => {
            expect(assetsApi.assetTags).toHaveBeenCalledTimes(1);
            expect(assetsApi.tagVocabulary).toHaveBeenCalledTimes(1);
        });

        const { result } = renderHook(() => useRemoveAssetTag('a1'), { wrapper });
        await act(async () => { await result.current.mutateAsync('gone tag'); });

        // Both are live queries, so the invalidation shows up as a second fetch
        // rather than as a lingering `isInvalidated` flag.
        await waitFor(() => {
            expect(assetsApi.assetTags).toHaveBeenCalledTimes(2);
            expect(assetsApi.tagVocabulary).toHaveBeenCalledTimes(2);
        });
    });

    it('reproduces the old cost when the scoping is dropped', async () => {
        // The regression as its own case: a bare `['gallery']` invalidation is
        // one request per loaded page. If this ever stops being 3, the defect it
        // documents is gone and the page-0 rule is no longer the cheapest.
        await mountGalleryWithPages(3);
        const before = assetsApi.facet.mock.calls.length;
        await act(async () => { await queryClient.invalidateQueries({ queryKey: ['gallery'] }); });
        await waitFor(() => expect(assetsApi.facet.mock.calls.length - before).toBeGreaterThan(0));
        expect(assetsApi.facet.mock.calls.length - before).toBe(3);
    });
});

describe('useAssetTags', () => {
    it('is keyed per asset and does not fire for an absent id', async () => {
        const { result } = renderHook(() => useAssetTags('a1'), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(true));
        expect(queryClient.getQueryCache().findAll({ queryKey: ['gallery', 'asset', 'a1', 'tags'] })).toHaveLength(1);

        renderHook(() => useAssetTags(null), { wrapper });
        expect(assetsApi.assetTags).toHaveBeenCalledTimes(1);
    });

    it('reaches the api with the options bag and no signal, per the same exemption', async () => {
        renderHook(() => useAssetTags('a1'), { wrapper });
        await waitFor(() => expect(assetsApi.assetTags).toHaveBeenCalled());
        expect(assetsApi.assetTags.mock.calls[0]).toEqual(['a1', {}]);
    });
});