import React from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    listSessions: vi.fn(),
    listSessionAssets: vi.fn(),
    createSession: vi.fn(),
    updateSession: vi.fn(),
    deleteSession: vi.fn(),
    addSessionAssets: vi.fn(),
    removeSessionAsset: vi.fn(),
    splitSession: vi.fn(),
    mergeSession: vi.fn(),
    detectSessions: vi.fn(),
    getSession: vi.fn(),
}));

vi.mock('../api/sessionsApi', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, ...apiMock };
});

import {
    flattenSessionPages,
    sessionsKeys,
    useDetectSessions,
    useDeleteSession,
    useMergeSession,
    useRenameSession,
    useSessionAssets,
    useSessions,
    useSplitSession,
} from './useSessions';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            React.createElement(QueryClientProvider, { client: queryClient }, children),
        queryClient,
    };
}

function page(sessions, { total = sessions.length, offset = 0 } = {}) {
    return { sessions, total, limit: 100, offset };
}

describe('useSessions', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('requests one page and flattens it into a session list', async () => {
        apiMock.listSessions.mockResolvedValue(page([{ id: 'a' }, { id: 'b' }], { total: 2 }));
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useSessions(), { wrapper });

        await waitFor(() => expect(flattenSessionPages(result.current.data)).toHaveLength(2));
        expect(apiMock.listSessions).toHaveBeenCalledWith({ limit: 100, offset: 0 }, { signal: expect.any(AbortSignal) });
        expect(result.current.hasNextPage).toBe(false);
    });

    it('keeps paging while the server reports more than it has sent', async () => {
        apiMock.listSessions
            .mockResolvedValueOnce(page([{ id: 'a' }], { total: 2, offset: 0 }))
            .mockResolvedValueOnce(page([{ id: 'b' }], { total: 2, offset: 1 }));
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useSessions(), { wrapper });

        await waitFor(() => expect(result.current.hasNextPage).toBe(true));
        await act(async () => { await result.current.fetchNextPage(); });

        expect(apiMock.listSessions).toHaveBeenNthCalledWith(2, { limit: 100, offset: 1 }, { signal: expect.any(AbortSignal) });
        await waitFor(() =>
            expect(flattenSessionPages(result.current.data).map((s) => s.id)).toEqual(['a', 'b']));
        expect(result.current.hasNextPage).toBe(false);
    });

    it('does not fetch while disabled', () => {
        const { wrapper } = createWrapper();
        renderHook(() => useSessions({}, { enabled: false }), { wrapper });
        expect(apiMock.listSessions).not.toHaveBeenCalled();
    });
});

describe('useSessionAssets', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('stays disabled without a session id and reads members otherwise', async () => {
        apiMock.listSessionAssets.mockResolvedValue({ session_id: 'a', assets: [{ id: 'a1' }], total: 1 });
        const { wrapper } = createWrapper();

        const idle = renderHook(() => useSessionAssets(null), { wrapper });
        expect(apiMock.listSessionAssets).not.toHaveBeenCalled();
        expect(idle.result.current.fetchStatus).toBe('idle');

        const active = renderHook(() => useSessionAssets('a'), { wrapper });
        await waitFor(() => expect(active.result.current.data.assets).toHaveLength(1));
        expect(apiMock.listSessionAssets).toHaveBeenCalledWith('a');
    });
});

describe('session mutations', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
        apiMock.updateSession.mockResolvedValue({ id: 'a' });
        apiMock.deleteSession.mockResolvedValue({ success: true });
        apiMock.splitSession.mockResolvedValue({ session: {}, created: {} });
        apiMock.mergeSession.mockResolvedValue({ id: 'b' });
        apiMock.detectSessions.mockResolvedValue({ summary: {} });
    });

    afterEach(() => cleanup());

    it('split posts keep_asset_ids and invalidates the whole sessions tree', async () => {
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

        const { result } = renderHook(() => useSplitSession(), { wrapper });
        await act(async () => {
            await result.current.mutateAsync({ id: 'a', keepAssetIds: ['k1', 'k2'] });
        });

        expect(apiMock.splitSession).toHaveBeenCalledWith('a', ['k1', 'k2']);
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['sessions'] });
    });

    it('merge invalidates the sessions root so the soft-deleted source leaves the list', async () => {
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

        const { result } = renderHook(() => useMergeSession(), { wrapper });
        await act(async () => {
            await result.current.mutateAsync({ id: 'a', targetSessionId: 'b' });
        });

        expect(apiMock.mergeSession).toHaveBeenCalledWith('a', 'b');
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['sessions'] });
    });

    it('does not touch the gallery cache, because membership is not an asset column', async () => {
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

        const split = renderHook(() => useSplitSession(), { wrapper });
        await act(async () => {
            await split.result.current.mutateAsync({ id: 'a', keepAssetIds: ['k1'] });
        });

        const keys = invalidate.mock.calls.map(([arg]) => arg.queryKey);
        expect(keys.every((key) => key[0] === 'sessions')).toBe(true);
    });

    it('rename and delete invalidate the same root', async () => {
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

        const rename = renderHook(() => useRenameSession(), { wrapper });
        await act(async () => {
            await rename.result.current.mutateAsync({ id: 'a', name: 'Renamed' });
        });
        expect(apiMock.updateSession).toHaveBeenCalledWith('a', { name: 'Renamed', description: undefined });

        const remove = renderHook(() => useDeleteSession(), { wrapper });
        await act(async () => {
            await remove.result.current.mutateAsync('a');
        });
        expect(apiMock.deleteSession).toHaveBeenCalledWith('a');

        expect(invalidate).toHaveBeenCalledTimes(2);
        expect(invalidate).toHaveBeenNthCalledWith(1, { queryKey: ['sessions'] });
        expect(invalidate).toHaveBeenNthCalledWith(2, { queryKey: ['sessions'] });
    });

    it('detect invalidates the list and is the only mutation that is a POST with no arguments', async () => {
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

        const { result } = renderHook(() => useDetectSessions(), { wrapper });
        await act(async () => {
            await result.current.mutateAsync({});
        });

        expect(apiMock.detectSessions).toHaveBeenCalledWith({});
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['sessions'] });
    });
});

describe('sessionsKeys', () => {
    it('nests detail and members under the root so one invalidation covers all of them', () => {
        expect(sessionsKeys.all).toEqual(['sessions']);
        expect(sessionsKeys.list({ limit: 100 })).toEqual(['sessions', 'list', { limit: 100 }]);
        expect(sessionsKeys.members('a')).toEqual(['sessions', 'detail', 'a', 'assets']);
    });
});
