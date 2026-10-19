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
    useAgents,
    useAgent,
    useCreateAgent,
    useUpdateAgent,
    useDeleteAgent,
    useSimulateWorkflow,
    useAgentVariants,
    useCreateAgentVariant,
    useUpdateAgentVariant,
    useDeleteAgentVariant,
    useActivateAgentVariant,
} from './useAgents';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            React.createElement(QueryClientProvider, { client: queryClient }, children),
        queryClient,
    };
}

describe('useAgents', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    afterEach(() => cleanup());

    it('fetches agents list with query params', async () => {
        apiMock.get.mockResolvedValue([{ id: 'ag-1', name: 'Character', slug: 'character' }]);
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useAgents(), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual([{ id: 'ag-1', name: 'Character', slug: 'character' }]));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/agents', {
            params: { include_disabled: true },
            signal: expect.any(AbortSignal),
        });
    });

    it('fetches single agent by id', async () => {
        apiMock.get.mockResolvedValue({ id: 'ag-1', name: 'Character' });
        const { wrapper } = createWrapper();
        const { result } = renderHook(() => useAgent('ag-1'), { wrapper });
        await waitFor(() => expect(result.current.data).toEqual({ id: 'ag-1', name: 'Character' }));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/agents/ag-1', {
            signal: expect.any(AbortSignal),
        });
    });

    it('create, update, delete, and simulate call expected endpoints', async () => {
        apiMock.post.mockResolvedValue({ id: 'ag-2', name: 'Narrator' });
        apiMock.put.mockResolvedValue({ id: 'ag-1', name: 'Updated' });
        apiMock.delete.mockResolvedValue({ ok: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

        const create = renderHook(() => useCreateAgent(), { wrapper });
        await act(async () => create.result.current.mutateAsync({ name: 'Narrator', slug: 'narrator' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/agents', { name: 'Narrator', slug: 'narrator' });

        const update = renderHook(() => useUpdateAgent(), { wrapper });
        await act(async () => update.result.current.mutateAsync({ id: 'ag-1', name: 'Updated' }));
        expect(apiMock.put).toHaveBeenCalledWith('/api/v2/agents/ag-1', { name: 'Updated' });

        const remove = renderHook(() => useDeleteAgent(), { wrapper });
        await act(async () => remove.result.current.mutateAsync('ag-1'));
        expect(apiMock.delete).toHaveBeenCalledWith('/api/v2/agents/ag-1');

        expect(invalidate).toHaveBeenCalled();

        // Simulate workflow
        apiMock.post.mockResolvedValue({ triage: { next_speaker: 'narrator' } });
        const simulate = renderHook(() => useSimulateWorkflow(), { wrapper });
        await act(async () => simulate.result.current.mutateAsync({ scenario_text: 'Hello world' }));
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/agents/simulate', { scenario_text: 'Hello world' });
    });

    it('manages prompt variants for an agent', async () => {
        apiMock.get.mockResolvedValue([{ id: 'var-1', slug: 'noir' }]);
        apiMock.post.mockResolvedValue({ id: 'var-1', slug: 'noir' });
        apiMock.put.mockResolvedValue({ id: 'var-1', name: 'Noir 2' });
        apiMock.delete.mockResolvedValue({ deleted: true });
        const { wrapper, queryClient } = createWrapper();
        const invalidate = vi.spyOn(queryClient, 'invalidateQueries');

        const list = renderHook(() => useAgentVariants('ag-1'), { wrapper });
        await waitFor(() => expect(list.result.current.data).toEqual([{ id: 'var-1', slug: 'noir' }]));
        expect(apiMock.get).toHaveBeenCalledWith('/api/v2/agents/ag-1/variants', {
            signal: expect.any(AbortSignal),
        });

        const create = renderHook(() => useCreateAgentVariant(), { wrapper });
        await act(async () =>
            create.result.current.mutateAsync({
                agentId: 'ag-1',
                slug: 'noir',
                name: 'Noir',
                system_prompt_template: 'You are noir.',
            })
        );
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/agents/ag-1/variants', {
            slug: 'noir',
            name: 'Noir',
            system_prompt_template: 'You are noir.',
        });

        const update = renderHook(() => useUpdateAgentVariant(), { wrapper });
        await act(async () =>
            update.result.current.mutateAsync({ agentId: 'ag-1', variantId: 'var-1', name: 'Noir 2' })
        );
        expect(apiMock.put).toHaveBeenCalledWith('/api/v2/agents/ag-1/variants/var-1', { name: 'Noir 2' });

        const activate = renderHook(() => useActivateAgentVariant(), { wrapper });
        await act(async () =>
            activate.result.current.mutateAsync({ agentId: 'ag-1', variantId: 'var-1' })
        );
        expect(apiMock.post).toHaveBeenCalledWith('/api/v2/agents/ag-1/variants/var-1/activate');

        const remove = renderHook(() => useDeleteAgentVariant(), { wrapper });
        await act(async () =>
            remove.result.current.mutateAsync({ agentId: 'ag-1', variantId: 'var-1' })
        );
        expect(apiMock.delete).toHaveBeenCalledWith('/api/v2/agents/ag-1/variants/var-1');

        expect(invalidate).toHaveBeenCalled();
    });
});
