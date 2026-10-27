import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import AddModelToProviderModal from './AddModelToProviderModal';
import { providersApi } from '../../api';

vi.mock('../../api', () => ({
    providersApi: {
        getSyncManifest: vi.fn(),
        downloadModels: vi.fn(),
    },
}));

vi.mock('../../hooks/useProviderModels', () => ({
    useAddModelToProviders: () => ({
        mutateAsync: vi.fn(),
        isPending: false,
    }),
}));

const MOCK_PROVIDERS = [
    { id: 'modal-image-worker', type: 'modal', worker_type: 'image', enabled: true },
    { id: 'beam-image-worker', type: 'beam', worker_type: 'image', enabled: true },
];

const MOCK_MANIFEST = {
    models: [
        {
            file_id: 'file-1',
            model_name: 'Test Model A',
            version_name: 'v1.0',
            directory: 'checkpoints',
            storage_filename: 'model_a.safetensors',
            size_kb: 2048,
        },
        {
            file_id: 'file-2',
            model_name: 'Test LoRA B',
            version_name: 'v2.0',
            directory: 'loras',
            storage_filename: 'lora_b.safetensors',
            size_kb: 512,
        },
    ],
};

function renderModal(onClose = vi.fn()) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <AddModelToProviderModal providers={MOCK_PROVIDERS} onClose={onClose} />
        </QueryClientProvider>
    );
}

describe('AddModelToProviderModal', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        providersApi.getSyncManifest.mockResolvedValue(MOCK_MANIFEST);
        providersApi.downloadModels.mockResolvedValue({ status: 'started' });
    });

    it('renders library catalog models by default', async () => {
        renderModal();
        expect(screen.getByText('From Library Catalog')).toBeTruthy();
        await waitFor(() => {
            expect(screen.getByText('Test Model A')).toBeTruthy();
            expect(screen.getByText('Test LoRA B')).toBeTruthy();
        });
    });

    it('allows switching to custom download URL mode', async () => {
        renderModal();
        fireEvent.click(screen.getByText('Custom Download URL'));
        expect(screen.getByPlaceholderText('e.g. sd_v1.5.safetensors')).toBeTruthy();
        expect(screen.getByPlaceholderText('https://...')).toBeTruthy();
    });

    it('selects library models and triggers download to selected provider', async () => {
        const onClose = vi.fn();
        renderModal(onClose);

        await waitFor(() => {
            expect(screen.getByText('Test Model A')).toBeTruthy();
        });

        // Click on Test Model A row to select it
        fireEvent.click(screen.getByText('Test Model A'));

        // Select modal-image-worker checkbox
        const providerCheckbox = screen.getByRole('checkbox', { name: /modal-image-worker/i });
        fireEvent.click(providerCheckbox);

        // Click submit button
        const submitBtn = screen.getByText(/Download to 1 Provider/i);
        fireEvent.click(submitBtn);

        await waitFor(() => {
            expect(providersApi.downloadModels).toHaveBeenCalledWith(
                'modal-image-worker',
                { file_ids: ['file-1'] }
            );
            expect(onClose).toHaveBeenCalled();
        });
    });
});
