import React from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
}));

vi.mock('../api', () => ({
    api: apiMock,
}));

import { useBranches, useCreateBranch } from './useBranches';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            React.createElement(QueryClientProvider, { client: queryClient }, children),
        queryClient,
    };
}

describe('useBranches', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('fetches branches with the branches subkey and gates on chatId', async () => {
        apiMock.get.mockResolvedValue([{ id: 'b1', message_id: 'm1' }]);
        const { wrapper, queryClient } = createWrapper();
        const { result } = renderHook(() => useBranches('c1'), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual([{ id: 'b1', message_id: 'm1' }]));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/chats/c1/branches');
        expect(queryClient.getQueryState(['world_vault', 'chats', 'c1', 'branches'])).toBeDefined();
    });

    it('does not fetch without a chatId', async () => {
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useBranches(null), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(false));
        expect(apiMock.get).not.toHaveBeenCalled();
    });

    it('useCreateBranch posts and invalidates branches + chat detail', async () => {
        apiMock.post.mockResolvedValue({ id: 'b2' });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useCreateBranch(), { wrapper });
        await act(async () => result.current.mutateAsync({ chatId: 'c1', messageId: 'm9' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/chats/c1/branches', { message_id: 'm9' });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'chats', 'c1', 'branches'] });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'chats', 'c1'] });
    });
});