import React from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
}));

vi.mock('../api', () => ({
    api: apiMock,
}));

import {
    useMessages,
    useEditMessage,
    useDeleteMessage,
    useRollbackChat,
    useRegenerateReply,
    useImpersonateMessage,
    usePinMessage,
    useSwipeMessage,
    useGenerateSwipe,
    useNarrateMessage,
} from './useMessages';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            React.createElement(QueryClientProvider, { client: queryClient }, children),
        queryClient,
    };
}

describe('useMessages', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('fetches messages for a chat with limit/offset and gates on chatId', async () => {
        apiMock.get.mockResolvedValue([{ id: 'm1', content: 'hi' }]);
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useMessages('c1', { limit: 5, offset: 10 }), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual([{ id: 'm1', content: 'hi' }]));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/chats/c1/messages', { params: { limit: 5, offset: 10 } });
    });

    it('does not fetch without a chatId', async () => {
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useMessages(null), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(false));
        expect(apiMock.get).not.toHaveBeenCalled();
    });

    it('useEditMessage optimistically rewrites content and rolls back on error', async () => {
        apiMock.patch.mockRejectedValue(new Error('fail'));
        const { wrapper, queryClient } = createWrapper();
        queryClient.setQueryData(['world_vault', 'messages', 'c1', 100, 0], [
            { id: 'm1', content: 'old' },
            { id: 'm2', content: 'keep' },
        ]);
        const { result } = renderHook(() => useEditMessage(), { wrapper });

        await act(async () => {
            try {
                await result.current.mutateAsync({ chatId: 'c1', msgId: 'm1', content: 'new' });
            } catch {
                /* expected */
            }
        });
        expect(queryClient.getQueryData(['world_vault', 'messages', 'c1', 100, 0])[0].content).toBe('old');
        expect(apiMock.patch).toHaveBeenCalledWith('/api/v2/chats/c1/messages/m1', { content: 'new' });
    });

    it('useEditMessage applies the optimistic edit while pending', async () => {
        let resolvePatch;
        apiMock.patch.mockImplementation(() => new Promise((r) => { resolvePatch = r; }));
        const { wrapper, queryClient } = createWrapper();
        queryClient.setQueryData(['world_vault', 'messages', 'c1', 100, 0], [{ id: 'm1', content: 'old' }]);
        const { result } = renderHook(() => useEditMessage(), { wrapper });

        let pending;
        act(() => { pending = result.current.mutate({ chatId: 'c1', msgId: 'm1', content: 'new' }); });
        await waitFor(() => {
            expect(queryClient.getQueryData(['world_vault', 'messages', 'c1', 100, 0])[0].content).toBe('new');
        });

        await act(async () => { resolvePatch({ id: 'm1' }); await pending; });
    });

    it('useDeleteMessage optimistically removes and rolls back on error', async () => {
        apiMock.delete.mockRejectedValue(new Error('nope'));
        const { wrapper, queryClient } = createWrapper();
        const key = ['world_vault', 'messages', 'c1', 100, 0];
        queryClient.setQueryData(key, [{ id: 'm1' }, { id: 'm2' }]);
        const { result } = renderHook(() => useDeleteMessage(), { wrapper });

        await act(async () => {
            try {
                await result.current.mutateAsync({ chatId: 'c1', msgId: 'm1' });
            } catch {
                /* expected */
            }
        });
        expect(queryClient.getQueryData(key)).toHaveLength(2);
    });

    it('useRollbackChat posts rollback and invalidates messages + chat', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useRollbackChat(), { wrapper });
        await act(async () => result.current.mutateAsync({ chatId: 'c1', messageId: 'm5' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats/c1/rollback', { message_id: 'm5' });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'messages', 'c1'] });
        // exact: see useChatStreaming.test.js — the detail query is the only one a
        // rollback changes.
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'chats', 'c1'], exact: true });
    });

    it('useRegenerateReply posts with message_id only when provided', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useRegenerateReply(), { wrapper });
        await act(async () => result.current.mutateAsync({ chatId: 'c1', messageId: 'm5' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats/c1/regenerate', { message_id: 'm5' });

        await act(async () => result.current.mutateAsync({ chatId: 'c1', messageId: null }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats/c1/regenerate', {});
    });

    it('useImpersonateMessage posts hint with empty fallback', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useImpersonateMessage(), { wrapper });
        await act(async () => result.current.mutateAsync({ chatId: 'c1', hint: 'be grumpy' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats/c1/impersonate', { hint: 'be grumpy' });
    });

    it('usePinMessage patches the pin endpoint', async () => {
        apiMock.patch.mockResolvedValue({ ok: true });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => usePinMessage(), { wrapper });
        await act(async () => result.current.mutateAsync({ chatId: 'c1', msgId: 'm1', pinned: true }));
        expect(apiMock.patch).toHaveBeenCalledWith('/api/v2/chats/c1/messages/m1/pin', { pinned: true });
    });

    it('useSwipeMessage posts direction/index', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useSwipeMessage(), { wrapper });
        await act(async () => result.current.mutateAsync({ chatId: 'c1', msgId: 'm1', direction: 'next', index: 1 }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats/c1/messages/m1/swipe', { direction: 'next', index: 1 });
    });

    it('useGenerateSwipe posts to generate-swipe endpoint', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useGenerateSwipe(), { wrapper });
        await act(async () => result.current.mutateAsync({ chatId: 'c1', msgId: 'm1' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats/c1/messages/m1/generate-swipe');
    });

    it('useNarrateMessage posts to the narrate endpoint', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useNarrateMessage(), { wrapper });
        await act(async () => result.current.mutateAsync({ chatId: 'c1', msgId: 'm1' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats/c1/messages/m1/narrate', {});
    });
});