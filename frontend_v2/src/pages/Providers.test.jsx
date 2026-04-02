import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import Providers from './Providers';

const mockUseProvidersPageData = vi.hoisted(() => vi.fn());

const mutationsState = vi.hoisted(() => ({
    actionLoading: {},
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

vi.mock('../hooks/useProvidersPageData', () => ({
    default: mockUseProvidersPageData,
    useProviderMutations: () => mutationsState,
}));

vi.mock('../store/reconciliationStore', () => ({
    default: () => reconciliationStoreState,
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

function buildProvider(overrides = {}) {
    return {
        id: 'modal-primary',
        type: 'modal',
        enabled: true,
        priority: 1,
        runtime_config: { port: 8000 },
        deploy_config: { deploy_mode: 'managed', app_name: 'comfy-modal-stack' },
        runtime_state: {
            mode: 'container_http',
            connected: true,
            status: 'running',
            worker_url: 'http://comfy-provider-modal-primary:8000',
        },
        deploy_state: {
            status: 'idle',
            message: '',
        },
        reconciliation_state: {
            status: 'idle',
            phase: null,
            message: '',
            stats: {},
            active_downloads: [],
            errors: [],
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
            managed_deploy: true,
            deploy: true,
            start_container: true,
            stop_container: true,
            restart_container: true,
            view_logs: true,
            setup: true,
            reconcile: true,
            reset_status: true,
        },
        capability_reasons: {},
        diagnostics: {
            warnings: [],
            errors: [],
            worker: {
                backend_url: 'http://backend_v2:8002',
                worker_url: 'http://comfy-provider-modal-primary:8000',
                mode: 'container_http',
            },
        },
        credential_summary: {
            configured_fields: ['token_id', 'token_secret', 'username'],
            account_label: 'modal-user',
            ready: true,
        },
        ...overrides,
    };
}

function buildHookData(overrides = {}) {
    return {
        providers: [buildProvider()],
        lbConfig: {
            strategy: 'round-robin',
            fallback_enabled: true,
        },
        lbStats: {
            total_providers: 1,
            provider_stats: [{ id: 'modal-primary', failures: 0, jobs_assigned: 0 }],
        },
        isLoading: false,
        refreshAll: vi.fn(),
        ...overrides,
    };
}

describe('Providers page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockUseProvidersPageData.mockReturnValue(buildHookData());
    });

    it('renders unified sync and storage sections from the canonical provider record', () => {
        render(<Providers />);

        expect(screen.getByText('modal-primary')).toBeInTheDocument();
        expect(screen.getByText('DB Sync')).toBeInTheDocument();
        expect(screen.getByText('Provider Storage')).toBeInTheDocument();
        expect(screen.getAllByText('4 models').length).toBeGreaterThan(0);
        expect(screen.getByText(/Checkpoints: 2/)).toBeInTheDocument();
    });

    it('shows a safe empty storage fallback when provider storage is unavailable', () => {
        mockUseProvidersPageData.mockReturnValue(
            buildHookData({
                providers: [
                    buildProvider({
                        storage: {
                            total: 0,
                            by_directory: {},
                        },
                    }),
                ],
            }),
        );

        render(<Providers />);

        expect(screen.getByText('Provider Storage')).toBeInTheDocument();
        expect(screen.getByText('No storage stats yet')).toBeInTheDocument();
    });
});
