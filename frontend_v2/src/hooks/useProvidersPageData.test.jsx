/**
 * `useProvidersPageData` must not hand out a new object — or a new empty
 * array — on every render.
 *
 * Eight call sites destructure this hook, and one of them feeds the array
 * straight into a `useMemo` dependency:
 *
 *     const allProviders = useProvidersPageData()?.providers;
 *     const { availableProviders, disabledProviders } = useMemo(… , [allProviders]);
 *
 * The returned object was a bare literal with `providers: providersQuery.data
 * || []` inside it. While the providers request is outstanding that expression
 * allocates a fresh `[]` on every render, so `allProviders` is a new value every
 * render, so that memo re-filters the provider list on every render — for as
 * long as the request takes, which on a cold start is most of the first paint.
 * Nothing about that shows in a screenshot; it is a per-frame allocation plus a
 * list filter on the frame the provider picker is about to render.
 *
 * The fix follows `useFavorites.js`, which already does the same two things: a
 * module-level constant for the empty case, and a `useMemo` so the returned
 * object is stable between real changes.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
    providersApi: { list: vi.fn(), getLoadBalancing: vi.fn() },
}));

// The hook subscribes to realtime provider events unless asked not to; every
// call here passes `realtime: false`, because the subscription reaches for a
// socket that does not exist in the test environment and is not what is under
// test here.

const { providersApi } = await import('../api');
const { useProvidersPageData } = await import('../hooks/useProvidersPageData');

let queryClient;

function wrapper({ children }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

/** A providers request that stays outstanding until `release()` is called. */
function deferredProviders(count = 1) {
    let release;
    providersApi.list.mockImplementation(() => new Promise((resolve) => {
        release = () => resolve({ providers: Array.from({ length: count }, (_, i) => ({ id: `p${i}` })) });
    }));
    providersApi.getLoadBalancing.mockResolvedValue({ config: { strategy: 'round-robin' }, stats: {} });
    // Awaited by the caller: an un-awaited `act(async …)` leaves the testing
    // environment in a state where the *next* test's renders never land.
    return async () => { await act(async () => { release(); }); };
}

beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
});

describe('useProvidersPageData returns a stable value while loading', () => {
    it('returns the same empty array on every render', async () => {
        deferredProviders();
        const { result, rerender } = renderHook(() => useProvidersPageData({ realtime: false }), { wrapper });
        await waitFor(() => expect(result.current?.isLoading).toBe(true));

        const first = result.current.providers;
        expect(first).toEqual([]);
        rerender();
        rerender();
        expect(result.current.providers).toBe(first);
    });

    it('returns the same object on every render', async () => {
        // The eight consumers destructure, so object identity is what a
        // `useMemo` or `useEffect` keyed on the whole result depends on. Both
        // queries are left outstanding so nothing legitimately changes between
        // the renders — the memo is supposed to recompute when something real
        // does.
        deferredProviders();
        providersApi.getLoadBalancing.mockImplementation(() => new Promise(() => {}));
        const { result, rerender } = renderHook(() => useProvidersPageData({ realtime: false }), { wrapper });
        await waitFor(() => expect(result.current?.isLoading).toBe(true));

        const first = result.current;
        rerender();
        expect(result.current).toBe(first);
    });

    it('shares one empty array across separate hook instances', () => {
        // A constant declared inside the hook body would satisfy the two tests
        // above and still hand two mounted consumers different arrays.
        deferredProviders();
        const a = renderHook(() => useProvidersPageData({ realtime: false }), { wrapper });
        const b = renderHook(() => useProvidersPageData({ realtime: false }), { wrapper });
        expect(a.result.current.providers).toBe(b.result.current.providers);
    });

    it('replaces it once the data lands, and is stable again afterwards', async () => {
        const release = deferredProviders(3);
        const { result, rerender } = renderHook(() => useProvidersPageData({ realtime: false }), { wrapper });
        await waitFor(() => expect(result.current?.isLoading).toBe(true));
        const empty = result.current.providers;

        await release();
        await waitFor(() => expect(result.current.providers).toHaveLength(3));

        const loaded = result.current.providers;
        expect(loaded).not.toBe(empty);
        rerender();
        rerender();
        expect(result.current.providers).toBe(loaded);
    });

    it('has a stable refreshAll, so it can be an effect dependency', async () => {
        providersApi.list.mockResolvedValue({ providers: [{ id: 'p0' }] });
        providersApi.getLoadBalancing.mockResolvedValue({ config: {}, stats: {} });
        const { result, rerender } = renderHook(() => useProvidersPageData({ realtime: false }), { wrapper });
        await waitFor(() => expect(result.current?.isLoading).toBe(false));

        const first = result.current.refreshAll;
        rerender();
        expect(result.current.refreshAll).toBe(first);

        const before = providersApi.list.mock.calls.length;
        await act(async () => { await result.current.refreshAll(); });
        expect(providersApi.list.mock.calls.length).toBeGreaterThan(before);
        expect(providersApi.getLoadBalancing.mock.calls.length).toBeGreaterThan(1);
    });
});