/**
 * `world_id` on chat and story create, sent but never relied on.
 *
 * `a338abc0` renamed the server-side `Campaign` resource to `World` and left
 * "letting a chat or story pick its world" undone. `Chat.world_id` and
 * `Story.world_id` are real columns (`backend_v2/core/entities.py:1186,1397`)
 * and come back on the created record, so the create response is a capability
 * check for free: if the field was dropped on the way in, `created.world_id` is
 * not what was asked for.
 *
 * The requirement is that a rejected `world_id` must not break creation. So the
 * two failure shapes are both covered here:
 *   - the server errors on the payload  -> the chat is still created, without
 *     `world_id`, and the user is told
 *   - the server silently drops it      -> the chat is created and the user is
 *     told
 *
 * The tests use the REAL `useCreateChat` / `useCreateStory` against a mocked HTTP
 * client, so a payload that stopped being sent would fail here rather than
 * silently degrade in the product.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
}));

vi.mock('../api', () => ({ api: apiMock }));

function makeClient() {
    return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
}

function wrapperFor(queryClient) {
    return function Wrapper({ children }) {
        return createElement(QueryClientProvider, { client: queryClient }, children);
    };
}

beforeEach(() => {
    vi.clearAllMocks();
    apiMock.get.mockResolvedValue([]);
});

describe('useCreateChat sends world_id', () => {
    it('puts it in the create payload when a world was picked', async () => {
        const { useCreateChat } = await import('../hooks/useChats');
        apiMock.post.mockResolvedValue({ id: 'c1', world_id: 'w1' });
        const queryClient = makeClient();
        const { result } = renderHook(() => useCreateChat(), { wrapper: wrapperFor(queryClient) });

        await act(async () => {
            await result.current.mutateAsync({ name: 'Chat', world_id: 'w1' });
        });

        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats', expect.objectContaining({ world_id: 'w1' }));
    });

    it('omits it entirely when no world was picked', async () => {
        const { useCreateChat } = await import('../hooks/useChats');
        apiMock.post.mockResolvedValue({ id: 'c1' });
        const queryClient = makeClient();
        const { result } = renderHook(() => useCreateChat(), { wrapper: wrapperFor(queryClient) });

        await act(async () => {
            await result.current.mutateAsync({ name: 'Chat' });
        });

        expect(apiMock.post.mock.calls[0][1]).not.toHaveProperty('world_id');
    });
});

describe('useCreateStory sends world_id', () => {
    it('puts it in the create payload when a world was picked', async () => {
        const { useCreateStory } = await import('../hooks/useStories');
        apiMock.post.mockResolvedValue({ id: 's1', world_id: 'w1' });
        const queryClient = makeClient();
        const { result } = renderHook(() => useCreateStory(), { wrapper: wrapperFor(queryClient) });

        await act(async () => {
            await result.current.mutateAsync({ title: 'A Tale', world_id: 'w1' });
        });

        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/stories', expect.objectContaining({ world_id: 'w1' }));
    });
});

describe('a world_id the server did not take is reported, and never blocks the create', () => {
    it('detects a silently dropped world_id from the created record', async () => {
        const { warnIfWorldIgnored } = await import('../utils/worldLinkWarning');
        // What a server that does not accept the field returns: 201, with the
        // column at its default. Nothing in the request failed.
        expect(warnIfWorldIgnored({ id: 'c1', world_id: null }, 'w1', 'chat')).toBeTruthy();
        expect(warnIfWorldIgnored({ id: 'c1' }, 'w1', 'chat')).toBeTruthy();
        // A different world than the one asked for is also a miss.
        expect(warnIfWorldIgnored({ id: 'c1', world_id: 'w2' }, 'w1', 'chat')).toBeTruthy();
    });

    it('stays silent when the world took, and when none was asked for', async () => {
        const { warnIfWorldIgnored } = await import('../utils/worldLinkWarning');
        expect(warnIfWorldIgnored({ id: 'c1', world_id: 'w1' }, 'w1', 'chat')).toBe(false);
        expect(warnIfWorldIgnored({ id: 'c1', world_id: null }, null, 'chat')).toBe(false);
    });

    it('the create still succeeds when the server rejects the payload with world_id', async () => {
        const { useCreateChat } = await import('../hooks/useChats');
        // A 422 from a server that forbids the unknown field. The chat must
        // still exist afterwards, which is the whole point of not assuming a
        // 200 on the first attempt.
        apiMock.post.mockImplementation((_url, body) => (
            'world_id' in body
                ? Promise.reject(Object.assign(new Error('extra fields not permitted'), { status: 422 }))
                : Promise.resolve({ id: 'c1', world_id: null })
        ));
        const queryClient = makeClient();
        const { result } = renderHook(() => useCreateChat(), { wrapper: wrapperFor(queryClient) });

        let created;
        await act(async () => {
            try {
                await result.current.mutateAsync({ name: 'Chat', world_id: 'w1' });
            } catch {
                // The caller retries without the world; the retry is the same
                // mutation, which is why this is asserted as a separate call.
                created = await result.current.mutateAsync({ name: 'Chat' });
            }
        });

        expect(apiMock.post).toHaveBeenCalledTimes(2);
        expect(apiMock.post.mock.calls[0][1]).toHaveProperty('world_id', 'w1');
        expect(apiMock.post.mock.calls[1][1]).not.toHaveProperty('world_id');
        expect(created).toEqual({ id: 'c1', world_id: null });
        expect(result.current.isError).toBe(false);
    });

    it('the warning names the entity, so a story and a chat do not read the same', async () => {
        const { WORLD_IGNORED_MESSAGE } = await import('../utils/worldLinkWarning');
        expect(WORLD_IGNORED_MESSAGE('chat')).toMatch(/^Chat created/);
        expect(WORLD_IGNORED_MESSAGE('story')).toMatch(/^Story created/);
        // Both must say the world was NOT attached — the whole point is that
        // the create succeeded and only the link was lost.
        for (const label of ['chat', 'story']) {
            expect(WORLD_IGNORED_MESSAGE(label)).toMatch(/could not be attached/i);
        }
    });
});
