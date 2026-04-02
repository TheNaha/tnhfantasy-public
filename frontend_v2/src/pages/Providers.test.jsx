import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import Providers from './Providers';

const mockUseProviderServerData = vi.hoisted(() => vi.fn());

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

vi.mock('../hooks/useProviderServerData', () => ({
    default: mockUseProviderServerData,
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

function buildServerData(overrides = {}) {
    const base = {
        providers: [
            {
                id: 'modal-primary',
                type: 'modal',
                enabled: true,
                priority: 1,
                credentials: {},
                config: {},
                container_config: { port: 8000 },
            },
        ],
        containerStatuses: {
            'modal-primary': {
                status: 'running',
                running: true,
                healthy: true,
            },
        },
        providerStatusCards: {
            'modal-primary': {
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
            },
        },
        lbConfig: {
            strategy: 'round-robin',
            fallback_enabled: true,
        },
        lbStats: {
            total_providers: 1,
            provider_stats: [
                {
                    id: 'modal-primary',
                    failures: 0,
                    jobs_assigned: 0,
                },
            ],
        },
        isLoading: false,
        refreshAll: vi.fn(),
    };

    return {
        ...base,
        ...overrides,
    };
}

describe('Providers page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockUseProviderServerData.mockReturnValue(buildServerData());
    });

    it('renders storage breakdown from unified status-card payloads', () => {
        render(<Providers />);

        expect(screen.getByText('modal-primary')).toBeInTheDocument();
        expect(screen.getByText('Provider Storage')).toBeInTheDocument();
        expect(screen.getByText('4 models')).toBeInTheDocument();
        expect(screen.getByText('Checkpoints: 2')).toBeInTheDocument();
    });

    it('falls back to empty sync message when status-card payload is absent', () => {
        mockUseProviderServerData.mockReturnValue(
            buildServerData({
                providerStatusCards: {},
            })
        );

        render(<Providers />);

        expect(screen.getByText('No models synced')).toBeInTheDocument();
    });
});
