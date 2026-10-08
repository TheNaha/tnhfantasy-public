import React from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const websocketMock = vi.hoisted(() => {
    const handlers = new Map();

    const addHandler = (event, callback) => {
        if (!handlers.has(event)) {
            handlers.set(event, new Set());
        }
        handlers.get(event).add(callback);
        return () => handlers.get(event)?.delete(callback);
    };

    return {
        handlers,
        connect: vi.fn().mockResolvedValue(undefined),
        subscribe: vi.fn().mockResolvedValue(undefined),
        unsubscribe: vi.fn(),
        on: vi.fn((event, callback) => addHandler(event, callback)),
        emit(event, payload) {
            for (const callback of handlers.get(event) || []) {
                callback(payload);
            }
        },
    };
});

vi.mock('../api', () => ({
    providersApi: {
        list: vi.fn(),
        getLoadBalancing: vi.fn(),
    },
}));

vi.mock('../api/websocket', () => ({
    ...websocketMock,
    EventTypes: {
        PROVIDER_STATUS: 'provider.status',
        PROVIDER_STATS_UPDATE: 'provider.stats_update',
        RECONCILIATION_STARTED: 'reconciliation.started',
        RECONCILIATION_PROGRESS: 'reconciliation.progress',
        RECONCILIATION_COMPLETED: 'reconciliation.completed',
        MODEL_STATUS_UPDATE: 'model.status_update',
    },
}));

function createWrapper(queryClient) {
    return function Wrapper({ children }) {
        return React.createElement(
            QueryClientProvider,
            { client: queryClient },
            children,
        );
    };
}

describe('useProvidersPageData', () => {
    let providersApi;
    let useProvidersPageData;
    let useProviderReconciliationState;

    beforeEach(async () => {
        vi.resetModules();
        cleanup();
        websocketMock.handlers.clear();
        websocketMock.connect.mockClear();
        websocketMock.subscribe.mockClear();
        websocketMock.unsubscribe.mockClear();
        websocketMock.on.mockClear();

        const apiMod = await import('../api');
        providersApi = apiMod.providersApi;
        const hookMod = await import('./useProvidersPageData');
        useProvidersPageData = hookMod.default;
        useProviderReconciliationState = hookMod.useProviderReconciliationState;

        providersApi.list.mockResolvedValue({
            providers: [{
                id: 'provider-1',
                type: 'modal',
                enabled: true,
                priority: 1,
                runtime_state: { status: 'stopped', connected: true },
                reconciliation_state: { status: 'idle' },
                model_sync: {
                    total_models: 1,
                    stats: { installed: 0, pending: 1, downloading: 0, failed: 0 },
                    models: [
                        {
                            file_id: 42,
                            provider_status: { status: 'pending', storage_path: null, size_bytes: null, error_message: null },
                        },
                    ],
                },
                storage: { total: 0, by_directory: {} },
                capabilities: {},
                capability_reasons: {},
                diagnostics: { warnings: [], errors: [] },
                credential_summary: {},
            }],
        });
        providersApi.getLoadBalancing.mockResolvedValue({
            config: { strategy: 'round-robin', fallback_enabled: true },
            stats: { total_providers: 1, provider_stats: [] },
        });
    });

    afterEach(() => {
        cleanup();
    });

    it('shares a single realtime subscription across multiple consumers and patches the shared cache', async () => {
        const queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
            },
        });
        const wrapper = createWrapper(queryClient);

        const first = renderHook(() => useProvidersPageData(), { wrapper });
        const second = renderHook(() => useProvidersPageData(), { wrapper });

        await waitFor(() => {
            expect(first.result.current.providers).toHaveLength(1);
            expect(second.result.current.providers).toHaveLength(1);
        });

        expect(websocketMock.connect).toHaveBeenCalledTimes(1);
        expect(websocketMock.subscribe).toHaveBeenCalledTimes(1);


        second.unmount();
        expect(websocketMock.unsubscribe).not.toHaveBeenCalled();

        first.unmount();
        expect(websocketMock.unsubscribe).toHaveBeenCalledTimes(1);
    });

    it('returns normalized provider reconciliation state from the shared providers query cache', async () => {
        const queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
            },
        });
        const wrapper = createWrapper(queryClient);

        const result = renderHook(() => useProviderReconciliationState('provider-1'), { wrapper });

        await waitFor(() => {
            expect(result.result.current.reconciliationState?.status).toBe('idle');
        });

        await act(async () => {
            websocketMock.emit('reconciliation.progress', {
                data: {
                    provider_id: 'provider-1',
                    status: 'started',
                    phase: 'downloading',
                    message: 'Starting sync',
                },
            });
        });

        await waitFor(() => {
            expect(result.result.current.reconciliationState?.status).toBe('queued');
            expect(result.result.current.reconciliationState?.phase).toBe('downloading');
        });
    });

    it('patches model status updates in the providers cache without broad refetches', async () => {
        const queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
            },
        });
        const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
        const wrapper = createWrapper(queryClient);

        const result = renderHook(() => useProvidersPageData(), { wrapper });

        await waitFor(() => {
            expect(result.result.current.providers).toHaveLength(1);
        });

        await act(async () => {
            websocketMock.emit('model.status_update', {
                data: {
                    provider_id: 'provider-1',
                    file_id: 42,
                    status: 'ready',
                    storage_path: 'models/checkpoints/test.safetensors',
                },
            });
        });

        await waitFor(() => {
            const stats = result.result.current.providers[0].model_sync?.stats || {};
            expect(stats.installed).toBe(1);
            expect(stats.pending).toBe(0);
        });

        const broadInvalidationCalls = invalidateSpy.mock.calls.filter(
            ([filters]) => filters?.queryKey?.[0] === 'providers-page' && filters?.queryKey?.[1] === 'providers',
        );
        expect(broadInvalidationCalls).toHaveLength(0);
    });

    it('falls back to providers invalidation when model status payload schema is incomplete', async () => {
        const queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
            },
        });
        const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
        const wrapper = createWrapper(queryClient);

        renderHook(() => useProvidersPageData(), { wrapper });

        await waitFor(() => {
            expect(queryClient.getQueryData(['providers-page', 'providers'])).toBeDefined();
        });

        await act(async () => {
            websocketMock.emit('model.status_update', {
                data: {
                    status: 'ready',
                },
            });
        });

        expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['providers-page', 'providers'] });
    });
});
