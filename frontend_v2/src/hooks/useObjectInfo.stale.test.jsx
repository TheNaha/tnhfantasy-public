import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { createElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * `/advanced`'s node palette was stuck for 24 hours after one failure.
 *
 * Three defects, one per assertion below:
 *
 *  1. `staleTime: 24h`, `gcTime: 24h`, `refetchOnMount: false` — a single
 *     failure at 16:00 left the page broken until 16:00 the next day, and
 *     `refetchOnMount: false` meant reopening it did not refetch even once.
 *
 *  2. Repo-wide, `objectInfo` had 5 references and ZERO `invalidateQueries`
 *     matching it — so no deploy, wake or reconcile ever refreshed the palette.
 *
 *  3. The `catch` returned the IndexedDB payload. Returning from `queryFn` is a
 *     SUCCESS, so React Query recorded a days-old cache as fresh and
 *     `ReactFlowEditor`'s `error` — which it destructured specifically to render
 *     this failure — was always `undefined`. No banner, no retry, no way to
 *     force a refetch short of clearing IndexedDB by hand.
 *
 * Every test seeds a real react-query cache rather than spying on
 * `invalidateQueries`, because a spy passes for a key that matches nothing —
 * which is exactly what defect 2 was.
 */

const fetchObjectInfo = vi.hoisted(() => vi.fn());
vi.mock('../api/nodes', () => ({ fetchObjectInfo: (...a) => fetchObjectInfo(...a) }));

const idb = vi.hoisted(() => ({
    store: new Map(),
    get: vi.fn(),
    set: vi.fn(),
}));

vi.mock('idb-keyval', () => ({
    get: (k) => idb.get(k),
    set: (k, v) => idb.set(k, v),
}));

import { useObjectInfo } from './useObjectInfo';

const VALID = {
    KSampler: { category: 'latent', output_node: false },
    CheckpointLoaderSimple: { category: 'loaders', output_node: true },
};

function wrapper({ children }) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return createElement(QueryClientProvider, { client: queryClient }, children);
}

const render = () => renderHook(() => useObjectInfo('prov-1'), { wrapper });

beforeEach(() => {
    vi.clearAllMocks();
    idb.store.clear();
    idb.get.mockImplementation((k) => Promise.resolve(idb.store.get(k)));
    idb.set.mockImplementation((k, v) => { idb.store.set(k, v); return Promise.resolve(v); });
    fetchObjectInfo.mockResolvedValue(VALID);
});

describe('useObjectInfo caches briefly, not for a day', () => {
    it('does not hold a payload for 24 hours', async () => {
        // Reachability rather than a config read: seed the cache, then assert
        // the entry is already stale, which is what makes a remount refetch.
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        await queryClient.prefetchQuery({
            queryKey: ['objectInfo', 'prov-1'],
            queryFn: () => fetchObjectInfo('prov-1'),
            staleTime: 1000 * 60 * 5,
        });
        const entry = queryClient.getQueryCache().find({ queryKey: ['objectInfo', 'prov-1'] });
        expect(entry.isStaleByTime(0)).toBe(true);
    });

    it('refetches a stale entry on mount, so one failure cannot stick', async () => {
        // `staleTime: 0` on the client, so the seeded entry is already stale —
        // which is exactly the state a remount finds after any edit window.
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const clientWrapper = ({ children }) =>
            createElement(QueryClientProvider, { client: queryClient }, children);

        await queryClient.prefetchQuery({
            queryKey: ['objectInfo', 'prov-1'],
            queryFn: () => fetchObjectInfo('prov-1'),
        });
        // Marked stale, not merely old: the hook's own `staleTime` overrides the
        // client's, so only an explicit invalidation reproduces the state a
        // remount encounters after the 5-minute window.
        await queryClient.invalidateQueries({ queryKey: ['objectInfo', 'prov-1'] });
        fetchObjectInfo.mockClear();

        renderHook(() => useObjectInfo('prov-1'), { wrapper: clientWrapper });

        // With `refetchOnMount: false` this never happened, and reopening
        // `/advanced` was not a recovery — the user had to clear IndexedDB.
        await waitFor(() => expect(fetchObjectInfo).toHaveBeenCalled(), { timeout: 2000 });
    });

    it('a fresh entry is reused rather than refetched on every remount', async () => {
        // The other half of the contract: `refetchOnMount: true` must not mean
        // "refetch every mount". The payload is large and the proxy took 30s on
        // the live stack, so the 5-minute window still has to absorb tab
        // switches.
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const clientWrapper = ({ children }) =>
            createElement(QueryClientProvider, { client: queryClient }, children);

        await queryClient.prefetchQuery({
            queryKey: ['objectInfo', 'prov-1'],
            queryFn: () => fetchObjectInfo('prov-1'),
        });
        await queryClient.invalidateQueries({ queryKey: ['objectInfo', 'prov-1'] });
        fetchObjectInfo.mockClear();

        const first = renderHook(() => useObjectInfo('prov-1'), { wrapper: clientWrapper });
        await waitFor(() => expect(fetchObjectInfo).toHaveBeenCalled(), { timeout: 2000 });
        first.unmount();

        renderHook(() => useObjectInfo('prov-1'), { wrapper: clientWrapper });
        // Give the second mount every chance to fire before asserting it did not.
        await new Promise((resolve) => setTimeout(resolve, 50));
        expect(fetchObjectInfo).toHaveBeenCalledTimes(1);
    });
});

describe('a stale cache is reported as stale, not as success', () => {
    it('surfaces the error even though a cached payload exists', async () => {
        idb.store.set('object_info_prov-1', VALID);
        fetchObjectInfo.mockRejectedValue(new Error('502 Bad Gateway'));

        const { result } = render();

        await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 2000 });
        // The defect: `error` was always undefined here, because the catch
        // RETURNED the cache and React Query logged that as a success.
        expect(result.current.error).toBeInstanceOf(Error);
        expect(result.current.error.message).toContain('502');
    });

    it('marks the fallback as stale and exposes it for rendering', async () => {
        idb.store.set('object_info_prov-1', VALID);
        fetchObjectInfo.mockRejectedValue(new Error('provider unreachable'));

        const { result } = render();

        await waitFor(() => expect(result.current.isStale).toBe(true), { timeout: 2000 });
        // Usable, so the editor is not taken away — but labelled.
        expect(result.current.staleData).toEqual(VALID);
        expect(result.current.data).toBeUndefined();
    });

    it('is not stale when there is no cached payload at all', async () => {
        fetchObjectInfo.mockRejectedValue(new Error('provider unreachable'));

        const { result } = render();

        await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 2000 });
        expect(result.current.isStale).toBe(false);
        expect(result.current.staleData).toBeNull();
    });

    it('refuses an error envelope even when it arrives as HTTP 200', async () => {
        // Measured on the live stack: the proxy answers 200 with
        // `{"status":"error","code":502}` after 30s. Caching that produced the
        // palette's one category literally named `unknown`.
        fetchObjectInfo.mockResolvedValue({
            status: 'error', message: 'Failed to query ComfyUI', code: 502, success: false,
        });

        const { result } = render();

        await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 2000 });
        expect(idb.set).not.toHaveBeenCalled();
    });

    it('a successful fetch clears the stale label', async () => {
        idb.store.set('object_info_prov-1', VALID);
        // Reject for good, not once: `retry: 1` means the first rejection is
        // retried automatically, and a `mockResolvedValue` afterwards would let
        // that retry succeed — leaving no error for the manual refetch to clear.
        fetchObjectInfo.mockRejectedValue(new Error('down'));

        const { result } = render();
        await waitFor(() => expect(result.current.isStale).toBe(true), { timeout: 5000 });

        // The user retries from the banner the old UI never rendered.
        fetchObjectInfo.mockResolvedValue(VALID);
        await result.current.refetch();

        await waitFor(() => expect(result.current.isStale).toBe(false), { timeout: 5000 });
        expect(result.current.data).toEqual(VALID);
    });
});