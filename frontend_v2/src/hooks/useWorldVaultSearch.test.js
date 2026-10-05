import React from 'react';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(),
}));

vi.mock('../api', () => ({
    api: apiMock,
}));

import {
    useWorldVaultSearch,
    useWorldVaultDashboard,
    useWorldVaultRelationships,
} from './useWorldVaultSearch';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            React.createElement(QueryClientProvider, { client: queryClient }, children),
        queryClient,
    };
}

describe('useWorldVaultSearch', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('searches all entities with q and optional type param', async () => {
        apiMock.get.mockResolvedValue({ characters: [], chats: [] });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useWorldVaultSearch('aria', 'character'), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual({ characters: [], chats: [] }));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/world-vault/search?q=aria&type=character', { signal: expect.any(AbortSignal) });
    });

    it('is disabled without a query', async () => {
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useWorldVaultSearch(''), { wrapper });
        await waitFor(() => expect(result.current.isSuccess).toBe(false));
        expect(apiMock.get).not.toHaveBeenCalled();
    });

    it('stays disabled below the backend minimum query length', async () => {
        const { wrapper } = createWrapper();
        // The backend declares `q: str = Query(..., min_length=2)`, so a
        // single-character query is a guaranteed 422, not an empty search.
        const { result } = renderHook(() => useWorldVaultSearch('a'), { wrapper });
        await waitFor(() => expect(result.current.fetchStatus).toBe('idle'));
        expect(apiMock.get).not.toHaveBeenCalled();

        cleanup();
        apiMock.get.mockResolvedValue({});
        const { result: ok } = renderHook(() => useWorldVaultSearch(' aria '), { wrapper: createWrapper().wrapper });
        await waitFor(() => expect(ok.current.isSuccess).toBe(true));
        // Surrounding whitespace is trimmed, so " aria " is a valid search.
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/world-vault/search?q=aria', { signal: expect.any(AbortSignal) });
    });

    it('omits the type param when falsy', async () => {
        apiMock.get.mockResolvedValue({});
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useWorldVaultSearch('bard'), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual({}));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/world-vault/search?q=bard', { signal: expect.any(AbortSignal) });
    });

    it('useWorldVaultDashboard fetches entity counts', async () => {
        apiMock.get.mockResolvedValue({ counts: { characters: 3 } });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useWorldVaultDashboard(), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual({ counts: { characters: 3 } }));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/world-vault/entities');
    });

    it('useWorldVaultRelationships fetches the relationship graph', async () => {
        apiMock.get.mockResolvedValue({ nodes: [], edges: [] });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useWorldVaultRelationships(), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual({ nodes: [], edges: [] }));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/world-vault/relationships');
    });
});