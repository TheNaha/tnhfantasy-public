import React from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
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
    useScenarios,
    useCreateScenario,
    useUpdateScenario,
    useDeleteScenario,
    useApplyScenario,
} from './useScenarios';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            React.createElement(QueryClientProvider, { client: queryClient }, children),
        queryClient,
    };
}

describe('useScenarios', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('fetches the scenario list', async () => {
        apiMock.get.mockResolvedValue([{ id: 'sc1', name: 'Night market' }]);
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useScenarios(), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual([{ id: 'sc1', name: 'Night market' }]));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/scenarios');
    });

    it('create/update/delete invalidate the scenario list', async () => {
        apiMock.post.mockResolvedValue({ id: 'sc2' });
        apiMock.put.mockResolvedValue({ id: 'sc1' });
        apiMock.delete.mockResolvedValue({ ok: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

        const create = renderHook(() => useCreateScenario(), { wrapper });
        await act(async () => create.result.current.mutateAsync({ name: 'B' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/scenarios', { name: 'B' });

        const update = renderHook(() => useUpdateScenario(), { wrapper });
        await act(async () => update.result.current.mutateAsync({ id: 'sc1', name: 'C' }));
        expect(apiMock.put).toHaveBeenCalledWith('/api/v2/scenarios/sc1', { name: 'C' });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'scenarios', 'sc1'] });

        const del = renderHook(() => useDeleteScenario(), { wrapper });
        await act(async () => del.result.current.mutateAsync('sc1'));
        expect(apiMock.delete).toHaveBeenCalledWith('/api/v2/scenarios/sc1');
    });

    it('useApplyScenario posts target type/id and invalidates scenarios, the target chat and stories', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useApplyScenario(), { wrapper });
        await act(async () =>
            result.current.mutateAsync({ scenarioId: 'sc1', targetType: 'chat', targetId: 'c1' })
        );
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/scenarios/sc1/apply', {
            target_type: 'chat',
            target_id: 'c1',
        });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'scenarios'] });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'chats', 'c1'], exact: true });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'stories'] });
    });

    it('useApplyScenario on a story does not invalidate chats at all', async () => {
        apiMock.post.mockResolvedValue({ ok: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
        const { result } = renderHook(() => useApplyScenario(), { wrapper });
        await act(async () =>
            result.current.mutateAsync({ scenarioId: 'sc1', targetType: 'story', targetId: 's1' })
        );
        expect(invalidate).not.toHaveBeenCalledWith(
            expect.objectContaining({ queryKey: ['world_vault', 'chats'] })
        );
    });
});