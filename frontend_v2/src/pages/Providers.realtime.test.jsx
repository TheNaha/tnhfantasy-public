import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
    getLoadBalancing: vi.fn(),
}));

vi.mock('../api', () => ({
    providersApi: providersApiMock,
}));

vi.mock('../api/websocket', () => ({
    connect: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn().mockResolvedValue(undefined),
    unsubscribe: vi.fn(),
    getConnectionStatus: vi.fn(() => false),
    on: vi.fn((event, callback) => {
        const callbacks = wsListeners.get(event) || [];
        callbacks.push(callback);
        wsListeners.set(event, callbacks);
        return () => {
            const current = wsListeners.get(event) || [];
            wsListeners.set(event, current.filter((fn) => fn !== callback));
        };
    }),
    EventTypes: {
        PROVIDER_STATUS: 'provider.status',
        PROVIDER_STATS_UPDATE: 'provider.stats_update',
        RECONCILIATION_STARTED: 'reconciliation.started',
        RECONCILIATION_PROGRESS: 'reconciliation.progress',
        RECONCILIATION_COMPLETED: 'reconciliation.completed',
        MODEL_STATUS_UPDATE: 'model.status_update',
    },
}));

vi.mock('../components/providers/ProviderModal', () => ({
    default: () => null,
}));

vi.mock('../components/providers/AddModelToProviderModal', () => ({
    default: () => null,
}));

vi.mock('../components/ConfirmationModal', () => ({
    default: () => null,
}));

function createWrapper() {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: { retry: false },
        },
    });

    return ({ children }) => (
        <QueryClientProvider client={queryClient}>
            {children}
        </QueryClientProvider>
    );
}

function createProviderRecord() {
    return {
        id: 'modal-primary',
        type: 'modal',
        enabled: true,
        priority: 1,
        runtime_state: {
            mode: 'in_process',
            connected: true,
            status: 'running',        },
        reconciliation_state: {
            status: 'idle',
            phase: null,
            stats: {},
            active_downloads: [],
            errors: [],
            message: '',
        },
        model_sync: {
            total_models: 4,
            stats: {
                installed: 3,
                pending: 1,
                downloading: 0,
                failed: 0,
            },
        },
        storage: {
            total: 4,
            by_directory: {
                checkpoints: 2,
                loras: 2,
            },
        },
        capabilities: {
            setup: true,
            reconcile: true,
            reset_status: true,
        },
        capability_reasons: {},
        diagnostics: {
            warnings: [],
            errors: [],
            worker: {
            },
        },
        credential_summary: {
            configured_fields: ['token_id', 'token_secret', 'username'],
            account_label: 'modal-user',
            ready: true,
        },
    };
}

describe('Providers realtime integration', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        wsListeners.clear();

        providersApiMock.list.mockResolvedValue({
            providers: [createProviderRecord()],
        });

        providersApiMock.getLoadBalancing.mockResolvedValue({
            config: {
                strategy: 'round-robin',
                fallback_enabled: true,
            },
            stats: {
                total_providers: 1,
                provider_stats: [{ id: 'modal-primary', failures: 0, jobs_assigned: 0 }],
            },
        });
    });

    it('updates provider card UI from websocket reconciliation and storage events', async () => {
        render(<Providers />, { wrapper: createWrapper() });

        await waitFor(() => {
            expect(screen.getByText('modal-primary')).toBeInTheDocument();
        });

        fireEvent.click(screen.getByText('modal-primary'));
        fireEvent.click(screen.getByRole('button', { name: 'Model Sync' }));

        await waitFor(() => {
            expect(screen.getAllByText('4 models').length).toBeGreaterThan(0);
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
                    },
                    active_downloads: [
                        { name: 'model-a.safetensors', index: 1, total: 5 },
                    ],
                },
            });
        });

        await waitFor(() => {
            expect(screen.getByText('Queued')).toBeInTheDocument();
        });

        await waitFor(() => {
            expect(screen.getByText('Syncing')).toBeInTheDocument();
        });

        act(() => {
            emitWsEvent('provider.stats_update', {
                data: {
                    provider_id: 'modal-primary',
                    stats: {
                        total: 6,
                        by_directory: {
                            checkpoints: 4,
                            loras: 2,
                        },
                    },
                },
            });
        });

        await waitFor(() => {
            expect(screen.getAllByText('6 models').length).toBeGreaterThan(0);
            expect(screen.getByText(/Checkpoints: 4/)).toBeInTheDocument();
        });
    }, 15000);
});
