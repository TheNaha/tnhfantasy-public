import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ModelMetadataModal from './ModelMetadataModal';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
});

function renderWithClient(ui) {
    return render(
        <QueryClientProvider client={queryClient}>
            {ui}
        </QueryClientProvider>
    );
}

describe('ModelMetadataModal', () => {
    const mockMetadata = {
        id: 'model-1',
        civitai_id: 12345,
        display_name: 'Test Anime Model',
        name: 'test_anime_model.safetensors',
        type: 'Checkpoint',
        base_model: 'SDXL 1.0',
        description: 'A great test model',
        version_description: 'v1.0 release notes',
        trained_words: ['masterpiece', '1girl', 'solo'],
        tags: ['anime', 'style', 'art'],
        images: [
            { url: 'https://example.com/img1.jpg', width: 1024, height: 1024 },
            { url: 'https://example.com/img2.jpg', width: 1024, height: 1024 },
            { url: 'https://example.com/img3.jpg', width: 1024, height: 1024 },
        ],
    };

    it('renders model info, trigger words, and gallery thumbnails', () => {
        const onAddTriggerWords = vi.fn();
        const onClose = vi.fn();

        renderWithClient(
            <ModelMetadataModal
                metadata={mockMetadata}
                onClose={onClose}
                onAddTriggerWords={onAddTriggerWords}
            />
        );

        expect(screen.getAllByText('Test Anime Model').length).toBeGreaterThan(0);
        expect(screen.getAllByText('SDXL 1.0').length).toBeGreaterThan(0);
        expect(screen.getAllByText('Checkpoint').length).toBeGreaterThan(0);
        // Trigger words and insert buttons
        expect(screen.getByText('masterpiece')).toBeInTheDocument();
        expect(screen.getByText('1girl')).toBeInTheDocument();
        expect(screen.getByText('solo')).toBeInTheDocument();

        const insertButtons = screen.getAllByRole('button', { name: /\+ Insert/i });
        expect(insertButtons.length).toBe(3);
        fireEvent.click(insertButtons[0]);
        expect(onAddTriggerWords).toHaveBeenCalledWith(['masterpiece']);

        // Gallery thumbnails
        const thumbnails = screen.getAllByRole('button', { name: /View image \d+/i });
        expect(thumbnails.length).toBe(3);
    });
});
