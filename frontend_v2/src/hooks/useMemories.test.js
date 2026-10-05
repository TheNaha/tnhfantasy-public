import React from 'react';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
}));

vi.mock('../api', () => ({
    api: apiMock,
}));

import {
    useCharacterMemories,
    useCreateMemory,
    useUpdateMemory,
    useDeleteMemory,
    useSearchMemories,
} from './useMemories';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            React.createElement(QueryClientProvider, { client: queryClient }, children),
        queryClient,
    };
}

const MOCK_MEMORIES = [
    { id: 'mem-1', character_id: 'char-1', content: 'The hero was born under a full moon.', importance: 8, tags: ['birth', 'omen'], created_at: '2024-01-15T10:00:00Z', last_accessed_at: null },
    { id: 'mem-2', character_id: 'char-1', content: 'Trust no one in the Shadowfell.', importance: 5, tags: ['warning', 'shadowfell'], created_at: '2024-02-20T12:00:00Z', last_accessed_at: '2024-03-01T08:00:00Z' },
];

describe('useMemories hooks', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    describe('useCharacterMemories', () => {
        it('fetches memories for the given character id', async () => {
            apiMock.get.mockResolvedValue(MOCK_MEMORIES);
            const { wrapper } = createWrapper();
            const { result } = renderHook(() => useCharacterMemories('char-1'), { wrapper });

            await waitFor(() => expect(result.current.data).toEqual(MOCK_MEMORIES));
            expect(apiMock.get).toHaveBeenCalledWith('/api/v2/memories/character/char-1', { signal: expect.any(AbortSignal) });
        });

        it('does not fetch when characterId is falsy', () => {
            const { wrapper } = createWrapper();
            const { result } = renderHook(() => useCharacterMemories(null), { wrapper });

            expect(result.current.isLoading).toBe(false);
            expect(result.current.data).toBeUndefined();
            expect(apiMock.get).not.toHaveBeenCalled();
        });

        it('returns empty data when the API returns an empty array', async () => {
            apiMock.get.mockResolvedValue([]);
            const { wrapper } = createWrapper();
            const { result } = renderHook(() => useCharacterMemories('char-2'), { wrapper });

            await waitFor(() => expect(result.current.data).toEqual([]));
        });
    });

    describe('useCreateMemory', () => {
        it('posts a new memory and invalidates the character memories query', async () => {
            apiMock.post.mockResolvedValue({ id: 'mem-new', ...MOCK_MEMORIES[0] });
            const { wrapper, queryClient } = createWrapper();
            const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

            const { result } = renderHook(() => useCreateMemory(), { wrapper });

            const payload = {
                character_id: 'char-1',
                content: 'A hidden temple was discovered.',
                importance: 7,
                tags: ['temple', 'discovery'],
            };

            await result.current.mutateAsync(payload);

            expect(apiMock.post).toHaveBeenCalledWith('/api/v2/memories', payload);
            expect(invalidate).toHaveBeenCalledWith({
                queryKey: ['world_vault', 'memories', 'char-1'],
            });
        });

        it('handles creation errors gracefully', async () => {
            apiMock.post.mockRejectedValue(new Error('Network error'));
            const { wrapper } = createWrapper();

            const { result } = renderHook(() => useCreateMemory(), { wrapper });

            await expect(
                result.current.mutateAsync({ character_id: 'char-1', content: 'test', importance: 5, tags: [] })
            ).rejects.toThrow('Network error');
        });
    });

    describe('useUpdateMemory', () => {
        it('puts updated memory data and invalidates queries', async () => {
            apiMock.put.mockResolvedValue({ id: 'mem-1', content: 'Updated content' });
            const { wrapper, queryClient } = createWrapper();
            const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

            const { result } = renderHook(() => useUpdateMemory(), { wrapper });

            await result.current.mutateAsync({
                id: 'mem-1',
                characterId: 'char-1',
                content: 'Updated content',
                importance: 9,
            });

            // The hook destructures id and character_id out, so the PUT body
            // should NOT contain them.
            expect(apiMock.put).toHaveBeenCalledWith('/api/v2/memories/mem-1', {
                content: 'Updated content',
                importance: 9,
            });
            expect(invalidate).toHaveBeenCalledWith({
                queryKey: ['world_vault', 'memories', 'char-1'],
            });
        });
    });

    describe('useDeleteMemory', () => {
        it('deletes a memory and invalidates the character memories query', async () => {
            apiMock.delete.mockResolvedValue({ ok: true });
            const { wrapper, queryClient } = createWrapper();
            const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

            const { result } = renderHook(() => useDeleteMemory(), { wrapper });

            await result.current.mutateAsync({ id: 'mem-1', characterId: 'char-1' });

            expect(apiMock.delete).toHaveBeenCalledWith('/api/v2/memories/mem-1');
            expect(invalidate).toHaveBeenCalledWith({
                queryKey: ['world_vault', 'memories', 'char-1'],
            });
        });
    });

    describe('useSearchMemories', () => {
        it('fetches semantic search results when characterId and query are provided', async () => {
            const searchResults = [MOCK_MEMORIES[0]];
            apiMock.get.mockResolvedValue(searchResults);

            const { wrapper } = createWrapper();
            const { result } = renderHook(
                () => useSearchMemories('char-1', 'moon'),
                { wrapper }
            );

            await waitFor(() => expect(result.current.data).toEqual(searchResults));
            expect(apiMock.get).toHaveBeenCalledWith(
                '/api/v2/memories/search/semantic',
                { params: { character_id: 'char-1', query: 'moon', limit: 20 }, signal: expect.any(AbortSignal) }
            );
        });

        it('does not fetch when query is shorter than 2 characters', () => {
            const { wrapper } = createWrapper();
            const { result } = renderHook(
                () => useSearchMemories('char-1', 'm'),
                { wrapper }
            );

            expect(result.current.isLoading).toBe(false);
            expect(apiMock.get).not.toHaveBeenCalled();
        });

        it('does not fetch when characterId is falsy', () => {
            const { wrapper } = createWrapper();
            const { result } = renderHook(
                () => useSearchMemories(null, 'moon'),
                { wrapper }
            );

            expect(result.current.isLoading).toBe(false);
            expect(apiMock.get).not.toHaveBeenCalled();
        });
    });
});
