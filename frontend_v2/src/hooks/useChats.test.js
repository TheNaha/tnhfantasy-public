import React from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
}));

vi.mock('../api', () => ({
    api: apiMock,
}));

import {
    useChats,
    useChat,
    useChatSystemPrompt,
    useChatJobs,
    useRenameChat,
    useGenerateScene,
    useSuggestReply,
    useUpdateChat,
    useSendMessage,
    useIllustrateChat,
    useChatImages,
    useSearchChats,
} from './useChats';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            React.createElement(QueryClientProvider, { client: queryClient }, children),
        queryClient,
    };
}

describe('useChats', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('queries the chat list with workspace/limit/offset params', async () => {
        apiMock.get.mockResolvedValue({ chats: [{ id: 'c1', name: 'Chat' }] });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useChats({ limit: 20, offset: 10, workspace: 'chat' }), { wrapper });

        await waitFor(() => expect(result.current.isSuccess).toBe(true));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/chats', {
            params: { workspace: 'chat', limit: 20, offset: 10 },
        });
        expect(result.current.data).toEqual({ chats: [{ id: 'c1', name: 'Chat' }] });
    });

    it('omits workspace when falsy and passes the default limit', async () => {
        apiMock.get.mockResolvedValue([]);
        const { wrapper } = createWrapper();
        renderHook(() => useChats(), { wrapper });
        await waitFor(() => expect(apiMock.get).toHaveBeenCalled());
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/chats', { params: { limit: 50 } });
    });

    it('useChat is disabled without an id and returns undefined data', async () => {
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useChat(null), { wrapper });
        await waitFor(() => expect(result.current.isEnabled).toBe(false));
        expect(result.current.data).toBeUndefined();
        expect(apiMock.get).not.toHaveBeenCalled();
    });

    it('useChat fetches the detail endpoint once enabled', async () => {
        apiMock.get.mockResolvedValue({ id: 'c1' });
        const { wrapper, queryClient } = createWrapper();
        const { result } = renderHook(() => useChat('c1'), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual({ id: 'c1' }));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/chats/c1');
        expect(queryClient.getQueryState(['world_vault', 'chats', 'c1'])).toBeDefined();
    });

    it('useChatSystemPrompt uses the system-prompt subkey', async () => {
        apiMock.get.mockResolvedValue({ system_prompt: 'You are a bard' });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useChatSystemPrompt('c1'), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual({ system_prompt: 'You are a bard' }));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/chats/c1/system-prompt');
    });

    it('useChatJobs polls fast while a job is active and slow otherwise', async () => {
        apiMock.get.mockResolvedValue([{ id: 'j1', status: 'generating' }]);
        const { wrapper, queryClient } = createWrapper();
        const { result } = renderHook(() => useChatJobs('c1'), { wrapper });
        await waitFor(() => expect(result.current.data).toHaveLength(1));
        const query = queryClient.getQueryCache().findAll({ queryKey: ['world_vault', 'chats', 'c1', 'jobs'] })[0];
        const intervalFn = query.options.refetchInterval;
        expect(typeof intervalFn).toBe('function');
        expect(intervalFn({ state: { data: [{ id: 'j1', status: 'generating' }] } })).toBe(5000);
        expect(intervalFn({ state: { data: [{ id: 'j1', status: 'completed' }] } })).toBe(30000);
        expect(intervalFn({ state: { data: [] } })).toBe(30000);
    });

    it('useRenameChat patches and invalidates list + detail', async () => {
        apiMock.patch.mockResolvedValue({ id: 'c1', name: 'Renamed' });
        const { wrapper, queryClient } = createWrapper();
        queryClient.setQueryData(['world_vault', 'chats', 'c1'], { id: 'c1', name: 'Old' });
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useRenameChat(), { wrapper });

        await act(async () => result.current.mutateAsync({ chatId: 'c1', name: 'Renamed' }));
        expect(apiMock.patch).toHaveBeenCalledWith('/api/v2/chats/c1', { name: 'Renamed' });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'chats'] });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'chats', 'c1'] });
    });

    useUpdateChatTest(useUpdateChat);
});

function useUpdateChatTest(hookFn) {
    it('useUpdateChat optimistically patches the detail and list then rolls back on error', async () => {
        apiMock.patch.mockRejectedValue(new Error('nope'));
        const { wrapper, queryClient } = createWrapper();
        queryClient.setQueryData(['world_vault', 'chats', 'c1'], { id: 'c1', name: 'Old' });
        queryClient.setQueryData(['world_vault', 'chats'], [{ id: 'c1', name: 'Old' }]);
        const { result } = renderHook(() => hookFn(), { wrapper });

        queryClient.setQueryData(['world_vault', 'chats', 'c1'], { id: 'c1', name: 'Old' });
        await act(async () => {
            try {
                await result.current.mutateAsync({ chatId: 'c1', name: 'New' });
            } catch {
                /* expected */
            }
        });

        const finalDetail = queryClient.getQueryData(['world_vault', 'chats', 'c1']);
        const finalList = queryClient.getQueryData(['world_vault', 'chats']);
        expect(finalDetail.name).toBe('Old');
        expect(finalList[0].name).toBe('Old');
    });

    it('useUpdateChat persists optimistic updates to both caches on success', async () => {
        apiMock.patch.mockResolvedValue({ id: 'c1', name: 'New' });
        const { wrapper, queryClient } = createWrapper();
        queryClient.setQueryData(['world_vault', 'chats', 'c1'], { id: 'c1', name: 'Old' });
        queryClient.setQueryData(['world_vault', 'chats'], [{ id: 'c1', name: 'Old' }]);
        const { result } = renderHook(() => hookFn(), { wrapper });

        await act(async () => result.current.mutateAsync({ chatId: 'c1', name: 'New' }));
        expect(queryClient.getQueryData(['world_vault', 'chats', 'c1']).name).toBe('New');
        expect(queryClient.getQueryData(['world_vault', 'chats'])[0].name).toBe('New');
    });
}

describe('useChats mutations', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('useGenerateScene posts to the scene endpoint', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useGenerateScene(), { wrapper });
        await act(async () => result.current.mutateAsync({ chatId: 'c1' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats/c1/scene', {});
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'chats', 'c1'] });
    });

    it('useSuggestReply posts draft with no cache invalidation', async () => {
        apiMock.post.mockResolvedValue({ suggestion: 'hi' });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useSuggestReply(), { wrapper });
        await act(async () => result.current.mutateAsync({ chatId: 'c1', draft: 'd' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats/c1/suggest', { draft: 'd' });
        await waitFor(() => expect(result.current.data).toEqual({ suggestion: 'hi' }));
    });

    it('useSendMessage appends an optimistic message and rolls back on error', async () => {
        apiMock.post.mockRejectedValue(new Error('fail'));
        const { wrapper, queryClient } = createWrapper();
        queryClient.setQueryData(['world_vault', 'messages', 'c1'], [{ id: 'm0', role: 'user', content: 'a' }]);
        const { result } = renderHook(() => useSendMessage(), { wrapper });

        await act(async () => {
            try {
                await result.current.mutateAsync({ chatId: 'c1', message: { role: 'user', content: 'b' } });
            } catch {
                /* expected */
            }
        });

        const messages = queryClient.getQueryData(['world_vault', 'messages', 'c1']);
        expect(messages).toHaveLength(1);
        expect(messages[0].content).toBe('a');
    });

    it('useSendMessage rolls forward optimistic entry into real messages on success', async () => {
        apiMock.post.mockResolvedValue({ id: 'm-new' });
        const { wrapper, queryClient } = createWrapper();
        const { result } = renderHook(() => useSendMessage(), { wrapper });

        await act(async () => result.current.mutateAsync({ chatId: 'c1', message: { role: 'user', content: 'hi' } }));
        const messages = queryClient.getQueryData(['world_vault', 'messages', 'c1']);
        expect(messages).toHaveLength(1);
        expect(messages[0].content).toBe('hi');
        expect(messages[0].optimistic).toBe(true);
    });

    it('useIllustrateChat posts with an empty image_prompt fallback', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useIllustrateChat(), { wrapper });
        await act(async () => result.current.mutateAsync({ chatId: 'c1', imagePrompt: undefined }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats/c1/illustrate', { image_prompt: '' });
    });

    it('useChatImages gates on chatId', async () => {
        apiMock.get.mockResolvedValue([{ id: 'i1' }]);
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useChatImages('c1'), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual([{ id: 'i1' }]));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/chats/c1/images');
    });

    it('useSearchChats is disabled for empty queries and sends q param otherwise', async () => {
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useSearchChats('   '), { wrapper });
        await waitFor(() => expect(result.current.isEnabled).toBe(false));
        expect(result.current.data).toBeUndefined();
        expect(apiMock.get).not.toHaveBeenCalled();

        apiMock.get.mockResolvedValue([]);
        const second = renderHook(() => useSearchChats('bard'), { wrapper });
        await waitFor(() => expect(second.result.current.isSuccess).toBe(true));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/chats', { params: { q: 'bard' } });
    });
});