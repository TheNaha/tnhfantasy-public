import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import Providers from './Providers';

const mockUseProvidersPageData = vi.hoisted(() => vi.fn());

const mutationsState = vi.hoisted(() => ({
    actionLoading: {},
    reconcileProvider: vi.fn(),
    setupProvider: vi.fn(),
    resetProviderModelStatus: vi.fn(),
    toggleProviderEnabled: vi.fn(),
    deleteProvider: vi.fn(),
    updateLoadBalancerStrategy: vi.fn(),
    saveProvider: vi.fn(),
}));

vi.mock('../hooks/useProvidersPageData', () => ({
    default: mockUseProvidersPageData,
    useProviderMutations: () => mutationsState,
}));

vi.mock('../components/providers/ProviderModal', () => ({
    default: () => null,
}));

vi.mock('../components/providers/AddModelToProviderModal', () => ({
    default: () => null,
}));

const mockConfirm = vi.hoisted(() => vi.fn(async () => true));

vi.mock('../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: mockConfirm }),
}));

vi.mock('../components/ConfirmationModal', () => ({
    default: () => null,
}));

// The detail panel pulls in a websocket console and job cards; only its dialog
// behaviour is under test here.
vi.mock('../hooks/useActiveJobs', () => ({ useActiveJobs: () => ({ data: [] }) }));
vi.mock('../components/dashboard/JobCard', () => ({ default: () => null }));
vi.mock('../components/providers/tabs/RuntimeTab', () => ({ default: () => <div data-testid="runtime-tab" /> }));
vi.mock('../components/providers/tabs/SyncTab', () => ({ default: () => null }));
vi.mock('../components/providers/tabs/DiagnosticsTab', () => ({ default: () => null }));

function buildProvider(overrides = {}) {
    return {
        id: 'modal-primary',
        type: 'modal',
        enabled: true,
        priority: 1,
        runtime_state: {
            mode: 'in_process',
            connected: true,
            status: 'running',        },
        model_sync: { total_models: 4, stats: { installed: 3, pending: 1, downloading: 0, failed: 0 } },
        storage: { total: 4, by_directory: { checkpoints: 2, loras: 2 } },
        capabilities: {
            setup: true, reconcile: true, reset_status: true,
        },
        capability_reasons: {},
        diagnostics: {
            warnings: [], errors: [],
            worker: {
                backend_url: 'http://backend_v2:8002',                mode: 'in_process',
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
        lbConfig: { strategy: 'round-robin', fallback_enabled: true },
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

    it('renders the provider list with provider name and status visible', () => {
        render(<Providers />);

        // Provider name should be visible in the list row
        expect(screen.getByText('modal-primary')).toBeInTheDocument();
        // Running status should be shown as a metric chip
        expect(screen.getAllByText('Running').length).toBeGreaterThan(0);
        // Load balancer bar should show strategy
        expect(screen.getByText('Round Robin')).toBeInTheDocument();
    });

    it('shows empty state when no providers are configured', () => {
        mockUseProvidersPageData.mockReturnValue(
            buildHookData({ providers: [], lbStats: { total_providers: 0, provider_stats: [] } }),
        );

        render(<Providers />);

        expect(screen.getByText('No providers configured')).toBeInTheDocument();
    });

    it('triggers provider row action buttons', async () => {
        render(<Providers />);

        fireEvent.click(screen.getByLabelText('Disable Provider'));
        await waitFor(() => {
            expect(mutationsState.toggleProviderEnabled).toHaveBeenCalledWith('modal-primary', true);
        });

        fireEvent.click(screen.getByLabelText('Delete Provider'));
        await waitFor(() => {
            expect(mockConfirm).toHaveBeenCalled();
            expect(mutationsState.deleteProvider).toHaveBeenCalledWith('modal-primary');
        });
    });

    it('does not delete a provider when the confirmation is declined', async () => {
        mockConfirm.mockResolvedValueOnce(false);
        render(<Providers />);

        fireEvent.click(screen.getByLabelText('Delete Provider'));
        await waitFor(() => {
            expect(mockConfirm).toHaveBeenCalled();
        });
        expect(mutationsState.deleteProvider).not.toHaveBeenCalled();
    });

    it('opens the provider detail panel as a dialog and closes it on Escape', async () => {
        render(<Providers />);

        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: /modal-primary/i }));
        const dialog = await screen.findByRole('dialog', { name: /modal-primary provider/i });
        expect(dialog).toHaveAttribute('aria-modal', 'true');
        expect(dialog).toHaveFocus();

        fireEvent.keyDown(window, { key: 'Escape' });
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    });
});
