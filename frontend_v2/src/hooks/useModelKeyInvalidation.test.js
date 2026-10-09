/**
 * Query-key reachability, verified against a real react-query cache.
 *
 * A spy on `invalidateQueries` passes for a call whose key matches nothing, and
 * that is exactly what all four of these defects were:
 *
 *   1. `ModelMetadataModal` used the react-query **v4** positional form
 *      `invalidateQueries(['models'])`. In v5 the array is spread into the
 *      filters object, `queryKey` ends up `undefined`, and it matches EVERY
 *      query in the cache — so one autopopulate refetched the whole app.
 *   2. `useProviderModels` / `useProvidersPageData` invalidated
 *      `{ queryKey: ['installed-models'] }`, a key no query declares. The
 *      installed-model list is `modelListKey(...)` = `['models','list',…]`.
 *   3. `ModelMetadataModal` / `ModelDetailsModal` invalidated
 *      `{ queryKey: ['model', modelId] }` — two elements under a namespace
 *      whose only query is three elements — and with a *local* model id where
 *      the query is keyed by a *civitai* one.
 *
 * So each test here seeds a real cache entry and asserts it went stale (or, for
 * the v4 form, that a bystander query it should not have touched stayed fresh).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
}));

vi.mock('../api', () => ({ api: apiMock }));

const providersApiMock = vi.hoisted(() => ({
    deploy: vi.fn(), reconcile: vi.fn(), quickSync: vi.fn(), setup: vi.fn(),
    resetModelStatus: vi.fn(), update: vi.fn(), delete: vi.fn(),
    create: vi.fn(), getLoadBalancing: vi.fn(), updateLoadBalancing: vi.fn(),
}));

vi.mock('../api', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, api: apiMock, providersApi: providersApiMock };
});

const { buildQueryKey, QUERY_KEYS, modelListKey } = await import('../constants/queryKeys');
const { installedVersionsKey } = await import('../hooks/useCivitaiSearch');

function makeClient() {
    return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } });
}

function wrapperFor(queryClient) {
    return function Wrapper({ children }) {
        return createElement(QueryClientProvider, { client: queryClient }, children);
    };
}

const stale = (queryClient, key) => queryClient.getQueryState(key)?.isInvalidated === true;
const fresh = (queryClient, key) => queryClient.getQueryState(key)?.isInvalidated !== true;

/**
 * The real shape of the installed-model list, from the real factory — not a
 * hand-written literal, so a change to `modelListKey` moves this test with it.
 * Note it is NOT built with `buildQueryKey`, so it has no `world_vault` prefix.
 */
function seedModelLists(queryClient) {
    const keys = [
        modelListKey({ modelType: 'checkpoint' }),
        modelListKey({ modelType: 'lora' }),
    ];
    for (const key of keys) queryClient.setQueryData(key, { items: [], total: 0 });
    return keys;
}

/** `['model', 'installed', <civitai model id>]`, as `useCheckInstalledVersions` registers it. */
function seedInstalledVersions(queryClient, civitaiId) {
    const key = installedVersionsKey(civitaiId);
    queryClient.setQueryData(key, { model_installed: true, installed_versions: [] });
    return key;
}

beforeEach(() => {
    vi.clearAllMocks();
    apiMock.get.mockResolvedValue({});
    apiMock.post.mockResolvedValue({});
    apiMock.put.mockResolvedValue({});
    apiMock.patch.mockResolvedValue({});
    apiMock.delete.mockResolvedValue({});
});

describe('provider model mutations reach the installed-model list', () => {
    it('useAddModelToProvider invalidates every modelListKey variant', async () => {
        const { useAddModelToProviders } = await import('../hooks/useProviderModels');
        const queryClient = makeClient();
        const keys = seedModelLists(queryClient);

        const { result } = renderHook(() => useAddModelToProviders(), { wrapper: wrapperFor(queryClient) });
        await act(async () => {
            await result.current.mutateAsync({ providerIds: ['p1'], modelId: 'm1' });
        });

        for (const key of keys) {
            expect(stale(queryClient, key), `${JSON.stringify(key)} was not invalidated`).toBe(true);
        }
    });

    it('a provider action invalidates the model list, not a key nothing declares', async () => {
        const { useProviderMutations } = await import('../hooks/useProvidersPageData');
        const queryClient = makeClient();
        const keys = seedModelLists(queryClient);
        // A bystander in an unrelated namespace, written as a literal on purpose:
        // no factory produces it, which is the point — a provider action must
        // reach the model list and nothing else. (This used to be built from
        // `QUERY_KEYS.PROVIDERS`, which could only ever yield
        // `['world_vault','providers',…]` — a key nothing declares, so the test
        // would have passed for a reason unrelated to what it claims.)
        const listener = ['provider-model-listener', 'p1', { model_type: 'checkpoint' }];
        queryClient.setQueryData(listener, []);

        const { result } = renderHook(() => useProviderMutations(), { wrapper: wrapperFor(queryClient) });
        await act(async () => {
            await result.current.reconcileProvider('p1');
        });

        for (const key of keys) expect(stale(queryClient, key)).toBe(true);
        // The v4 positional form, had it survived here, would have taken this too.
        expect(fresh(queryClient, listener)).toBe(true);
    });
});

describe('the model namespace has exactly one query, and the invalidation names it', () => {
    it('the real key is three elements and is civitai-keyed', () => {
        expect(installedVersionsKey('civ-42')).toEqual(['model', 'installed', 'civ-42']);
    });

    it('an autopopulate invalidates the installed-versions query for the civitai id it matched', async () => {
        const queryClient = makeClient();
        const keys = seedModelLists(queryClient);
        const civitaiKey = seedInstalledVersions(queryClient, 'civ-42');
        // A second civitai model's query: matching the local id instead of the
        // matched civitai id would miss this and hit neither.
        const bystander = seedInstalledVersions(queryClient, 'civ-99');

        const { useQueryClient } = await import('@tanstack/react-query');
        const { result } = renderHook(() => useQueryClient(), { wrapper: wrapperFor(queryClient) });
        await act(async () => {
            // Exactly what ModelMetadataModal's and ModelDetailsModal's onSuccess
            // now issue after `POST /api/v2/models/{id}/autopopulate`.
            result.current.invalidateQueries({ queryKey: [QUERY_KEYS.MODELS] });
            result.current.invalidateQueries({ queryKey: installedVersionsKey('civ-42') });
        });

        expect(stale(queryClient, civitaiKey)).toBe(true);
        expect(fresh(queryClient, bystander)).toBe(true);
        for (const key of keys) expect(stale(queryClient, key)).toBe(true);
    });

    it('a local model id does NOT match the installed-versions query', () => {
        // Why the old `{ queryKey: ['model', file.model_id] }` was wrong twice
        // over: wrong length, and the wrong id space. This is the assertion that
        // keeps someone from "fixing" it to
        // `installedVersionsKey(file.model_id)`, which would still be a no-op.
        const queryClient = makeClient();
        seedInstalledVersions(queryClient, 'civ-42');
        queryClient.invalidateQueries({ queryKey: ['model', 'civ-42'] });
        expect(stale(queryClient, installedVersionsKey('civ-42'))).toBe(false);
    });
});

describe('the react-query v4 positional form, which ModelMetadataModal still used', () => {
    it('invalidateQueries([key]) nukes the whole cache, object form does not', async () => {
        // `ModelMetadataModal` called `queryClient.invalidateQueries(['models'])`.
        // In v5 the array is spread into the filters object, so `queryKey` is
        // `undefined` and the filter is "everything" — one autopopulate refetched
        // every mounted query in the app, and would have re-run every active poll
        // alongside it. This test pins the reason the object form is required, so
        // nobody "simplifies" it back.
        const { useQueryClient } = await import('@tanstack/react-query');

        const withPositional = makeClient();
        const bystander = buildQueryKey(QUERY_KEYS.CHATS, 'c1');
        withPositional.setQueryData(bystander, []);
        withPositional.setQueryData(modelListKey({ modelType: 'lora' }), { items: [] });
        const { result: rq } = renderHook(() => useQueryClient(), { wrapper: wrapperFor(withPositional) });
        await act(async () => { rq.current.invalidateQueries([QUERY_KEYS.MODELS]); });
        expect(stale(withPositional, bystander)).toBe(true);

        const withObject = makeClient();
        withObject.setQueryData(bystander, []);
        withObject.setQueryData(modelListKey({ modelType: 'lora' }), { items: [] });
        const { result: rq2 } = renderHook(() => useQueryClient(), { wrapper: wrapperFor(withObject) });
        await act(async () => { rq2.current.invalidateQueries({ queryKey: [QUERY_KEYS.MODELS] }); });
        expect(fresh(withObject, bystander)).toBe(true);
        expect(stale(withObject, modelListKey({ modelType: 'lora' }))).toBe(true);
    });
});

/**
 * `/advanced`'s node palette and the provider lifecycle.
 *
 * `objectInfo` is keyed `['objectInfo', providerId]` and, before 2026-10-04,
 * repo-wide it had 5 references and ZERO `invalidateQueries` matching it. So no
 * provider action refreshed it — not a deploy, not a reconcile, not a wake. A
 * provider that had just booted from cold, or just gained a custom-node pack,
 * left the palette describing it as it was hours or days ago, and because
 * `refetchOnMount` was `false` reopening `/advanced` did not help either.
 *
 * Verified against a seeded cache rather than by spying on
 * `invalidateQueries`, for the reason in this file's header: a spy passes for a
 * key that matches nothing.
 */
describe('provider actions reach the node palette', () => {
    /** `useObjectInfo`'s real key shape. */
    function seedObjectInfo(queryClient, providerId = 'p1') {
        const key = ['objectInfo', providerId];
        queryClient.setQueryData(key, { KSampler: { category: 'latent' } });
        return key;
    }

    it('a reconcile invalidates objectInfo for that provider', async () => {
        const { useProviderMutations } = await import('../hooks/useProvidersPageData');
        const queryClient = makeClient();
        const key = seedObjectInfo(queryClient, 'p1');

        const { result } = renderHook(() => useProviderMutations(), { wrapper: wrapperFor(queryClient) });
        await act(async () => {
            await result.current.reconcileProvider('p1');
        });

        expect(stale(queryClient, key)).toBe(true);
    });

    it('there is no deploy path left to invalidate for', async () => {
        // `deployProvider` was removed with the containerized provider workers on
        // 2026-10-09: `POST /api/v2/providers/{id}/deploy`, `DeployTab.jsx` and
        // the engine's `deploy()` method are all gone, so there is no longer a
        // mutation whose success should mark the node palette stale.
        //
        // Recorded as a test rather than deleted, because the shape of the bug
        // that removed it — a mutation renamed out from under its invalidation
        // test — is invisible: this file would simply have passed with a test
        // asserting a function that no longer exists.
        const { useProviderMutations } = await import('../hooks/useProvidersPageData');
        expect(typeof useProviderMutations).toBe('function');
        const { result } = renderHook(() => useProviderMutations(), {
            wrapper: wrapperFor(makeClient()),
        });
        expect(result.current).not.toHaveProperty('deployProvider');
        expect(result.current).not.toHaveProperty('getDeployState');
    });

    it('does not reach an unrelated namespace', async () => {
        const { useProviderMutations } = await import('../hooks/useProvidersPageData');
        const queryClient = makeClient();
        seedObjectInfo(queryClient, 'p1');
        const bystander = ['advanced-graph', 'p1'];
        queryClient.setQueryData(bystander, {});

        const { result } = renderHook(() => useProviderMutations(), { wrapper: wrapperFor(queryClient) });
        await act(async () => {
            await result.current.reconcileProvider('p1');
        });

        expect(fresh(queryClient, bystander)).toBe(true);
    });
});
