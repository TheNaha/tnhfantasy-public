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
        getLoadBalancerConfig: vi.fn(),
    },
}));

vi.mock('../api/websocket', () => ({
    ...websocketMock,
    EventTypes: {
        PROVIDER_STATUS: 'provider.status',
        PROVIDER_CONTAINER_STATUS: 'provider.container_status',
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

        providersApi.list.mockResolvedValue({
            providers: [{
                id: 'provider-1',
                type: 'modal',
                enabled: true,
                priority: 1,
                runtime_state: { status: 'stopped', connected: true },
                deploy_state: { status: 'idle' },
                reconciliation_state: { status: 'idle' },
                model_sync: { total_models: 0, stats: {} },
                storage: { total: 0, by_directory: {} },
                capabilities: {},
                capability_reasons: {},
                diagnostics: { warnings: [], errors: [] },
                credential_summary: {},
            }],
        });
        providersApi.getLoadBalancerConfig.mockResolvedValue({
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

        await act(async () => {
            websocketMock.emit('provider.container_status', {
                provider_id: 'provider-1',
                status: 'running',
                running: true,
                healthy: true,
            });
        });

        await waitFor(() => {
            expect(first.result.current.providers[0].runtime_state.status).toBe('running');
            expect(second.result.current.providers[0].runtime_state.status).toBe('running');
        });

        second.unmount();
        expect(websocketMock.unsubscribe).not.toHaveBeenCalled();

        first.unmount();
        expect(websocketMock.unsubscribe).toHaveBeenCalledTimes(1);
    });
});
