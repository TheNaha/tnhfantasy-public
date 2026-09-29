/**
 * The two vault-wide read models that nothing invalidated.
 *
 * `useTimeline` (Activity) unions `Message`, `StoryChapter`, `CharacterMemory`
 * and `Asset`; `useWorldVaultDashboard` counts every entity type. Both are
 * derived aggregates, so an entity mutation cannot reach them by its own id —
 * and nothing did. Sending a message left the Activity feed missing it for the
 * full 5-minute global `staleTime` (`refetchOnWindowFocus` is off app-wide, so
 * nothing bounded it), and the roleplay front door's count cards read stale
 * numbers. Audit P1-32.
 *
 * There is no websocket for either: `api/websocket.js`'s `EventTypes` has no
 * timeline or dashboard topic and no provider pushes one, so a test asserting
 * "a websocket already covers this" would be asserting an absence. What is
 * asserted here instead is that each mutation reaches both keys.
 *
 * These tests import the REAL hook modules and the real react-query cache: the
 * only mock is the HTTP client, so a mutation whose `onSuccess` silently drops
 * the invalidation fails here.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
}));

vi.mock('../api', () => ({ api: apiMock }));

const TIMELINE_PREFIX = ['world_vault', 'timeline'];
const DASHBOARD_KEY = ['world_vault', 'dashboard'];

function makeClient() {
    // `gcTime: 0` (used elsewhere in this suite to isolate renders) would collect
    // the seeded queries the moment the `act()` yields, and the assertions would
    // read `undefined` rather than "not invalidated".
    return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } });
}

function wrapperFor(queryClient) {
    return function Wrapper({ children }) {
        return createElement(QueryClientProvider, { client: queryClient }, children);
    };
}

/**
 * Invalidation, observed rather than spied on.
 *
 * A spy on `invalidateQueries` would pass for a call with a key that matches
 * nothing — which is exactly what the `['installed-models']` and
 * `['model', modelId]` defects were. Seeding real queries under both aggregate
 * keys and asserting they go stale proves the key actually reaches them.
 */
function seedAggregates(queryClient) {
    // Two different filter objects, because the Activity page changes its key
    // on every chip click; a prefix invalidation has to reach all of them.
    queryClient.setQueryData([...TIMELINE_PREFIX, {}], { events: [] });
    queryClient.setQueryData([...TIMELINE_PREFIX, { character_id: 'c1' }], { events: [] });
    queryClient.setQueryData(DASHBOARD_KEY, { counts: {} });
}

function expectAggregatesStale(queryClient) {
    for (const key of [
        [...TIMELINE_PREFIX, {}],
        [...TIMELINE_PREFIX, { character_id: 'c1' }],
        DASHBOARD_KEY,
    ]) {
        expect(
            queryClient.getQueryState(key)?.isInvalidated,
            `query ${JSON.stringify(key)} was not invalidated`,
        ).toBe(true);
    }
}

const MUTATIONS = [
    ['useSendMessage', '../hooks/useChats', { chatId: 'c1', message: { role: 'user', content: 'hi' } }],
    ['useCreateMemory', '../hooks/useMemories', { character_id: 'char-1', content: 'likes rain' }],
    ['useCreateChapter', '../hooks/useStories', { storyId: 's1', data: { title: 'One' } }],
    ['useCreateCharacter', '../hooks/useCharacters', { name: 'Aria' }],
    ['useCreateLorebook', '../hooks/useLorebooks', { name: 'Book' }],
    ['useCreateEntry', '../hooks/useLorebooks', { lorebookId: 'lb-1', name: 'Fact' }],
    ['useCreateWorld', '../hooks/useWorlds', { name: 'Emberfall' }],
    ['useCreateBranch', '../hooks/useBranches', { chatId: 'c1', messageId: 'm1' }],
];

describe('vault aggregate invalidation', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        apiMock.get.mockResolvedValue({});
        apiMock.post.mockResolvedValue({ id: 'new' });
        apiMock.put.mockResolvedValue({});
        apiMock.patch.mockResolvedValue({});
        apiMock.delete.mockResolvedValue({});
    });

    for (const [hookName, modulePath, variables] of MUTATIONS) {
        it(`${hookName} invalidates the timeline and the dashboard counts`, async () => {
            const queryClient = makeClient();
            seedAggregates(queryClient);
            const mod = await import(/* @vite-ignore */ modulePath);

            const { result } = renderHook(() => mod[hookName](), { wrapper: wrapperFor(queryClient) });
            await act(async () => {
                await result.current.mutateAsync(variables);
            });

            expectAggregatesStale(queryClient);
        });
    }

    it('a delete invalidates them too', async () => {
        const queryClient = makeClient();
        seedAggregates(queryClient);
        const { useDeleteWorld } = await import('../hooks/useWorlds');

        const { result } = renderHook(() => useDeleteWorld(), { wrapper: wrapperFor(queryClient) });
        await act(async () => { await result.current.mutateAsync('world-1'); });

        expectAggregatesStale(queryClient);
    });

    it('the aggregate keys are the ones the two queries actually register', async () => {
        // If `useTimeline`'s key or `useWorldVaultDashboard`'s key drifts from
        // what the invalidation targets, every test above would still pass while
        // the real queries were untouched. This closes that gap.
        const { useTimeline, TIMELINE_KEY } = await import('../hooks/useTimeline');
        const { useWorldVaultDashboard } = await import('../hooks/useWorldVaultSearch');
        const { buildQueryKey, QUERY_KEYS } = await import('../constants/queryKeys');
        expect(TIMELINE_KEY).toEqual(TIMELINE_PREFIX);
        expect(buildQueryKey(QUERY_KEYS.DASHBOARD)).toEqual(DASHBOARD_KEY);

        const queryClient = makeClient();
        const wrapper = wrapperFor(queryClient);
        renderHook(() => useTimeline({ character_id: 'c1' }), { wrapper });
        renderHook(() => useWorldVaultDashboard(), { wrapper });

        const registered = queryClient.getQueryCache().findAll().map((q) => q.queryKey);
        expect(registered.some((k) => TIMELINE_PREFIX.every((part, i) => k[i] === part))).toBe(true);
        expect(registered.some((k) => DASHBOARD_KEY.every((part, i) => k[i] === part))).toBe(true);
    });
});
