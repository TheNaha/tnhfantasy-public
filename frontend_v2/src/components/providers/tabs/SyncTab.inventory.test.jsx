import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import SyncTab from './SyncTab';
import { providersApi } from '../../../api';

vi.mock('../../../api', () => ({
    providersApi: {
        getSyncManifest: vi.fn(),
        downloadModels: vi.fn(),
    },
}));

vi.mock('../../../hooks/useProvidersPageData', () => ({
    useProviderReconciliationState: () => ({
        reconciliationState: { status: 'idle', phase: null, stats: {} },
    }),
}));

const MOCK_STORAGE = {
    total: 10,
    by_directory: { checkpoints: 4, loras: 6 },
};

const MOCK_MANIFEST = {
    models: [
        {
            file_id: 'file-ready',
            model_name: 'SDXL Base',
            version_name: 'v1.0',
            directory: 'checkpoints',
            storage_filename: 'sdxl.safetensors',
            size_kb: 6000000,
            status: 'ready',
            needs_download: false,
        },
        {
            file_id: 'file-missing',
            model_name: 'Pony Diffusion',
            version_name: 'v6',
            directory: 'checkpoints',
            storage_filename: 'pony.safetensors',
            size_kb: 6000000,
            status: 'missing',
            needs_download: true,
        },
    ],
};

function renderSyncTab() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <SyncTab
                providerId="modal-test-prov"
                modelSync={{ total_models: 2 }}
                storage={MOCK_STORAGE}
                storageLoaded={true}
                reconciliation={{ status: 'idle' }}
                capabilities={{ reconcile: true, reset_status: true }}
                loading={false}
                onReconcile={vi.fn()}
                onQuickSync={vi.fn()}
                onResetStatus={vi.fn()}
            />
        </QueryClientProvider>
    );
}

describe('SyncTab Inventory Matrix', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        providersApi.getSyncManifest.mockResolvedValue(MOCK_MANIFEST);
        providersApi.downloadModels.mockResolvedValue({ status: 'started' });
    });

    it('renders provider model inventory with status badges', async () => {
        renderSyncTab();

        expect(screen.getByText('Provider Model Inventory')).toBeTruthy();

        await waitFor(() => {
            expect(screen.getByText('SDXL Base')).toBeTruthy();
            expect(screen.getByText('Ready')).toBeTruthy();
            expect(screen.getByText('Pony Diffusion')).toBeTruthy();
            expect(screen.getByText('Missing')).toBeTruthy();
        });
    });

    it('triggers targeted download when clicking inline Download button', async () => {
        renderSyncTab();

        await waitFor(() => {
            expect(screen.getByText('Pony Diffusion')).toBeTruthy();
        });

        const downloadBtn = screen.getByRole('button', { name: /^download$/i });
        fireEvent.click(downloadBtn);

        await waitFor(() => {
            expect(providersApi.downloadModels).toHaveBeenCalledWith(
                'modal-test-prov',
                { file_ids: ['file-missing'] }
            );
        });
    });

    it('triggers download of all missing models when clicking Download Missing header button', async () => {
        renderSyncTab();

        await waitFor(() => {
            expect(screen.getByText(/Download Missing \(1\)/i)).toBeTruthy();
        });

        fireEvent.click(screen.getByText(/Download Missing \(1\)/i));

        await waitFor(() => {
            expect(providersApi.downloadModels).toHaveBeenCalledWith(
                'modal-test-prov',
                { file_ids: ['file-missing'] }
            );
        });
    });
});
