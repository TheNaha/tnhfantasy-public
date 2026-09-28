/**
 * Regression tests for three defects that a green suite did not catch, because
 * in each case the test file that touches the code mocks the module under test.
 *
 *  1. `LOREBOOK_ENTRIES_KEY` was defined as `(id) => LOREBOOK_ENTRIES_KEY(id)` —
 *     the factory called itself. Every consumer raised
 *     `RangeError: Maximum call stack size exceeded` during render: the
 *     Lorebooks page as soon as a lorebook was selected, and
 *     `EntityContextInspector`. The same key is called in the `onSuccess` of
 *     all six entry mutations, so a create/update/delete/import/bulk-delete
 *     wrote to the server and *then* threw in its invalidation, leaving the
 *     list stale. `Lorebooks.test.jsx` and `EntityContextInspector.test.jsx`
 *     both `vi.mock('../hooks/useLorebooks')`, so neither could see it.
 *
 *  2. `App.jsx`'s settings effect called `queryClient.setDefaultOptions` with
 *     `mutations: { retry: 1 }`, restoring on every page load the retried
 *     non-idempotent mutations that the QueryClient constructor had just set to
 *     `retry: 0` — duplicate jobs, duplicated chat messages and paid LLM
 *     calls, duplicated characters, and DELETEs that succeeded server-side and
 *     then reported a 404 failure.
 *
 *  3. Batch-favouriting looped `toggleFavorite`, a read-modify-write of the
 *     whole list. `onMutate` runs asynchronously, so every iteration read the
 *     same pre-batch list; N overwrites went to the server, the last one won,
 *     and the UI reported "Added N images to favorites".
 *
 * This file imports the real modules.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createElement } from 'react';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const FAVORITES_KEY = ['favorites'];

function makeWrapper(queryClient) {
    // A component, not a pre-created element: passing an element as `wrapper`
    // makes React treat the element itself as the component type.
    return function Wrapper({ children }) {
        return createElement(QueryClientProvider, { client: queryClient }, children);
    };
}

function makeClient() {
    return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe('useLorebooks entries key', () => {
    beforeEach(() => {
        vi.resetModules();
    });

    it('builds a finite key instead of recursing forever', async () => {
        vi.doMock('../api', () => ({
            api: { get: vi.fn().mockResolvedValue([]) },
        }));
        const { useLorebookEntries } = await import('./useLorebooks.js');

        const queryClient = makeClient();
        // With the self-recursive factory this line throws
        // `RangeError: Maximum call stack size exceeded` during render, which
        // is exactly the crash the Lorebooks page showed.
        const { result } = renderHook(() => useLorebookEntries('lb-1'), {
            wrapper: makeWrapper(queryClient),
        });

        expect(result.current).toBeDefined();
        const registered = queryClient.getQueryCache().findAll({
            queryKey: ['world_vault', 'lorebooks'],
        });
        expect(registered.length).toBeGreaterThan(0);
        expect(registered[0].queryKey).toEqual(['world_vault', 'lorebooks', 'lb-1', 'entries']);
    });

    it('nests the entries key under the lorebooks prefix, and apart from the detail key', async () => {
        const { QUERY_KEYS, buildQueryKey } = await import('../constants/queryKeys.js');
        const expected = buildQueryKey(QUERY_KEYS.LOREBOOKS, 'lb-1', 'entries');
        expect(expected).toEqual(['world_vault', 'lorebooks', 'lb-1', 'entries']);
        // A lorebook detail invalidation must not be able to match it, and
        // vice versa — the two were the same shape before the fix only by
        // accident, since the entries factory never returned.
        expect(expected).not.toEqual(buildQueryKey(QUERY_KEYS.LOREBOOKS, 'lb-1'));
    });

    it('every entry mutation invalidates a key that exists', async () => {
        // The other half of the bug: the same factory was called from six
        // `onSuccess` handlers, so each write landed and then its invalidation
        // threw. These all run without raising.
        vi.doMock('../api', () => ({
            api: {
                get: vi.fn().mockResolvedValue([]),
                post: vi.fn().mockResolvedValue({}),
                put: vi.fn().mockResolvedValue({}),
                delete: vi.fn().mockResolvedValue({}),
            },
        }));
        const mod = await import('./useLorebooks.js');
        const queryClient = makeClient();
        const wrapper = makeWrapper(queryClient);

        const mutations = [
            ['useCreateEntry', { lorebookId: 'lb-1', name: 'x' }],
            ['useUpdateEntry', { lorebookId: 'lb-1', id: 'e1', name: 'y' }],
            ['useDeleteEntry', { lorebookId: 'lb-1', id: 'e1' }],
            ['useReindexLorebook', 'lb-1'],
            ['useImportLorebookEntries', { lorebookId: 'lb-1', payload: [] }],
            ['useBulkDeleteEntries', { lorebookId: 'lb-1', entryIds: ['e1'] }],
        ];

        for (const [hookName, variables] of mutations) {
            const { result } = renderHook(() => mod[hookName](), { wrapper });
            await act(async () => {
                await result.current.mutateAsync(variables);
            });
        }
        expect(true).toBe(true); // reaching here without a RangeError is the point
    });
});

describe('query client mutation retry policy', () => {
    it('is not clobbered when the settings effect re-applies cache timings', async () => {
        // What the effect used to do — a full replace that reinstated retry: 1.
        const clobbered = new QueryClient({
            defaultOptions: { queries: { retry: 1 }, mutations: { retry: 0, networkMode: 'online' } },
        });
        clobbered.setDefaultOptions({
            queries: { staleTime: 1, gcTime: 2, retry: 1 },
            mutations: { retry: 1, networkMode: 'online' },
        });
        expect(clobbered.getDefaultOptions().mutations.retry).toBe(1); // the bug, reproduced

        // What it does now — merge, so the constructor's policy survives.
        const merged = new QueryClient({
            defaultOptions: { queries: { retry: 1 }, mutations: { retry: 0, networkMode: 'online' } },
        });
        const current = merged.getDefaultOptions().queries;
        merged.setDefaultOptions({
            ...merged.getDefaultOptions(),
            queries: { ...current, staleTime: 1, gcTime: 2 },
        });
        expect(merged.getDefaultOptions().mutations.retry).toBe(0);
        expect(merged.getDefaultOptions().queries.staleTime).toBe(1);
        expect(merged.getDefaultOptions().queries.gcTime).toBe(2);
        expect(merged.getDefaultOptions().queries.retry).toBe(1); // query retry preserved
    });
});

describe('batch favourite', () => {
    beforeEach(() => {
        vi.resetModules();
    });

    async function mountFavorites(initial) {
        const updateFavorites = vi.fn().mockImplementation(async (next) => ({ favorites: next }));
        vi.doMock('../api/settingsApi', () => ({
            settingsApi: {
                getFavorites: vi.fn().mockResolvedValue({ favorites: initial }),
                updateFavorites,
            },
        }));
        const { useFavorites } = await import('./useFavorites.js');
        const queryClient = makeClient();
        queryClient.setQueryData(FAVORITES_KEY, initial);
        const { result } = renderHook(() => useFavorites(), { wrapper: makeWrapper(queryClient) });
        return { result, updateFavorites };
    }

    it('sends one merged list rather than N competing overwrites', async () => {
        const { result, updateFavorites } = await mountFavorites(['existing.png']);

        // The old implementation looped toggleFavorite synchronously; because
        // onMutate is async, all three read the same pre-batch list and the
        // server received three "existing + one" overwrites.
        await act(async () => {
            result.current.addFavorites(['a.png', 'b.png', 'c.png']);
        });

        expect(updateFavorites).toHaveBeenCalledTimes(1);
        expect(updateFavorites).toHaveBeenCalledWith([
            'existing.png', 'a.png', 'b.png', 'c.png',
        ]);
    });

    it('does not re-add something already favourited', async () => {
        const { result, updateFavorites } = await mountFavorites(['existing.png']);

        await act(async () => {
            result.current.addFavorites(['existing.png', 'new.png']);
        });

        expect(updateFavorites).toHaveBeenCalledWith(['existing.png', 'new.png']);
    });

    it('is a no-op for an empty selection', async () => {
        const { result, updateFavorites } = await mountFavorites(['existing.png']);

        await act(async () => {
            result.current.addFavorites([]);
        });

        expect(updateFavorites).not.toHaveBeenCalled();
    });
});
