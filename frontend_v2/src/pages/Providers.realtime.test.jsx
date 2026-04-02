import { act, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import Providers from './Providers';

const wsListeners = vi.hoisted(() => new Map());

function emitWsEvent(eventType, payload) {
    const callbacks = wsListeners.get(eventType) || [];
    callbacks.forEach((callback) => callback(payload));
}

const providersApiMock = vi.hoisted(() => ({
    list: vi.fn(),
    getAllContainerStatuses: vi.fn(),
    getLoadBalancerConfig: vi.fn(),
    getStatusCards: vi.fn(),
    getContainerLogs: vi.fn(),
}));

const providerStoreState = vi.hoisted(() => ({
    containerLoading: {},
    startContainer: vi.fn(),
    stopContainer: vi.fn(),
    restartContainer: vi.fn(),
    deployProvider: vi.fn(),
    reconcileProvider: vi.fn(),
    setupProvider: vi.fn(),
    resetProviderModelStatus: vi.fn(),
    toggleProviderEnabled: vi.fn(),
    deleteProvider: vi.fn(),
    updateLoadBalancerStrategy: vi.fn(),
    saveProvider: vi.fn(),
}));

const reconciliationStoreState = vi.hoisted(() => ({
    startReconciliation: vi.fn(),
}));

vi.mock('../api', () => ({
    providersApi: providersApiMock,
}));

vi.mock('../api/websocket', () => ({
    connect: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn().mockResolvedValue(undefined),
    unsubscribe: vi.fn(),
    on: vi.fn((event, callback) => {
        const callbacks = wsListeners.get(event) || [];
        callbacks.push(callback);
        wsListeners.set(event, callbacks);

        return () => {
            const current = wsListeners.get(event) || [];
            wsListeners.set(
                event,
                current.filter((fn) => fn !== callback)
            );
        };
    }),
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

vi.mock('../store/providerStore', () => ({
    useProviderStore: (selector) => selector(providerStoreState),
}));

vi.mock('../store/reconciliationStore', () => ({
    default: (selector) => (
        typeof selector === 'function'
            ? selector(reconciliationStoreState)
            : reconciliationStoreState
    ),
}));

vi.mock('../components/providers/ProviderModal', () => ({
    default: () => null,
}));

vi.mock('../components/providers/AddModelToProviderModal', () => ({
    default: () => null,
}));

vi.mock('../components/providers/ReconciliationStatus', () => ({
    default: () => null,
}));

vi.mock('../components/ConfirmationModal', () => ({
    default: () => null,
}));

function createWrapper() {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
            },
        },
    });

    return ({ children }) => (
        <QueryClientProvider client={queryClient}>
            {children}
        </QueryClientProvider>
    );
}

function createStatusCard() {
    return {
        provider_id: 'modal-primary',
        provider_type: 'modal',
        sync: {
            total_models: 4,
            stats: {
                installed: 3,
                pending: 1,
                downloading: 0,
                failed: 0,
            },
        },
        storage: {
            provider_id: 'modal-primary',
            total: 4,
            by_directory: {
                checkpoints: 2,
                loras: 2,
            },
        },
        reconciliation: {
            provider_id: 'modal-primary',
            status: 'idle',
            phase: null,
            stats: {},
            active_downloads: [],
            errors: [],
        },
        deploy: {
            status: 'idle',
        },
        runtime: {
            mode: 'container_http',
            connected: true,
        },
    };
}

describe('Providers realtime integration', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        wsListeners.clear();

        providersApiMock.list.mockResolvedValue([
            {
                id: 'modal-primary',
                type: 'modal',
                enabled: true,
                priority: 1,
                credentials: {},
                config: {},
                container_config: { port: 8000 },
            },
        ]);

        providersApiMock.getAllContainerStatuses.mockResolvedValue({
            statuses: {
                'modal-primary': {
                    status: 'running',
                    running: true,
                    healthy: true,
                },
            },
        });

        providersApiMock.getLoadBalancerConfig.mockResolvedValue({
            config: {
                strategy: 'round-robin',
                fallback_enabled: true,
            },
            stats: {
                total_providers: 1,
                provider_stats: [
                    {
                        id: 'modal-primary',
                        failures: 0,
                        jobs_assigned: 0,
                    },
                ],
            },
        });

        providersApiMock.getStatusCards.mockResolvedValue({
            status_cards: {
                'modal-primary': createStatusCard(),
            },
        });
    });

    it('updates provider card UI from websocket reconciliation and stats events', async () => {
        render(<Providers />, { wrapper: createWrapper() });

        await waitFor(() => {
            expect(screen.getByText('modal-primary')).toBeInTheDocument();
            expect(screen.getByText('4 models')).toBeInTheDocument();
        });

        act(() => {
            emitWsEvent('reconciliation.progress', {
                data: {
                    provider_id: 'modal-primary',
                    status: 'started',
                    phase: 'downloading',
                    message: 'Sync in progress',
                    stats: {
                        downloads_queued: 5,
                        downloads_completed: 1,
                        downloads_failed: 0,
                    },
                    active_downloads: [
                        { name: 'model-a.safetensors', index: 1, total: 5 },
                    ],
                },
            });
        });

        await waitFor(() => {
            expect(screen.getByText('Downloading')).toBeInTheDocument();
            expect(screen.getAllByText('1/5').length).toBeGreaterThan(0);
        });

        act(() => {
            emitWsEvent('provider.stats_update', {
                data: {
                    provider_id: 'modal-primary',
                    stats: {
                        total: 7,
                        by_directory: {
                            checkpoints: 3,
                            loras: 4,
                        },
                    },
                },
            });
        });

        await waitFor(() => {
            expect(screen.getByText('7 models')).toBeInTheDocument();
            expect(screen.getByText('LoRAs: 4')).toBeInTheDocument();
        });
    });
});
