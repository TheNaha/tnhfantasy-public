import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import ModelSection from './ModelSection';

describe('ModelSection LoRA version/outfit switcher', () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const mockLora = {
        name: 'rem_casual.safetensors',
        display_name: 'Rem (Re:Zero)',
        base_model: 'SDXL',
        strength: 0.8,
        selectedVersionId: 'v1',
        versions: [
            {
                id: 'v1',
                name: 'Casual Outfit',
                base_model: 'SDXL',
                trained_words: ['rem_casual, maid'],
                file: { filename: 'rem_casual.safetensors', size_kb: 45000 },
            },
            {
                id: 'v2',
                name: 'Swimsuit Outfit',
                base_model: 'Illustrious',
                trained_words: ['rem_swimsuit, bikini'],
                file: { filename: 'rem_swimsuit.safetensors', size_kb: 48000 },
            },
        ],
    };

    it('renders outfit selector when lora has multiple versions', () => {
        const updateLora = vi.fn();
        render(
            <QueryClientProvider client={queryClient}>
                <ModelSection
                    selectedLoras={[mockLora]}
                    updateLora={updateLora}
                    removeLora={vi.fn()}
                    addLora={vi.fn()}
                    addTriggerWords={vi.fn()}
                    checkpoints={[]}
                    unetModels={[]}
                    vaeModels={[]}
                    clipModels={[]}
                    embeddingModels={[]}
                    promptShortcuts={{}}
                />
            </QueryClientProvider>
        );

        expect(screen.getByText('Rem (Re:Zero)')).toBeInTheDocument();
        expect(screen.getByText('Outfit:')).toBeInTheDocument();
        const select = screen.getByRole('combobox', { name: /outfit/i });
        expect(select).toBeInTheDocument();
        expect(screen.getByText('Casual Outfit (SDXL)')).toBeInTheDocument();
        expect(screen.getByText('Swimsuit Outfit (Illustrious)')).toBeInTheDocument();

        // Switch to Swimsuit
        fireEvent.change(select, { target: { value: 'v2' } });
        expect(updateLora).toHaveBeenCalledWith(
            0,
            'model',
            expect.objectContaining({
                name: 'rem_swimsuit.safetensors',
                base_model: 'Illustrious',
                trained_words: ['rem_swimsuit, bikini'],
                selectedVersionId: 'v2',
            })
        );
    });

    it('renders embeddings with shortened names and allows flexible positive/negative targeting', () => {
        const setPrompt = vi.fn();
        const setNegativePrompt = vi.fn();
        const mockEmbeddings = [
            { name: '_lazy_embeddings_for_all_illus_lazypos_1833157.safetensors', size: 50000 },
            { name: '_lazy_embeddings_for_all_illus_lazynsfw_1833157.safetensors', size: 50000 },
        ];

        render(
            <QueryClientProvider client={queryClient}>
                <ModelSection
                    selectedLoras={[]}
                    updateLora={vi.fn()}
                    removeLora={vi.fn()}
                    addLora={vi.fn()}
                    addTriggerWords={vi.fn()}
                    prompt="masterpiece, best quality"
                    negativePrompt="bad hands"
                    setPrompt={setPrompt}
                    setNegativePrompt={setNegativePrompt}
                    checkpoints={[]}
                    unetModels={[]}
                    vaeModels={[]}
                    clipModels={[]}
                    embeddingModels={mockEmbeddings}
                    promptShortcuts={{}}
                />
            </QueryClientProvider>
        );

        // Check that names are shortened
        expect(screen.getByText('lazypos')).toBeInTheDocument();
        expect(screen.getByText('lazynsfw')).toBeInTheDocument();

        // Check flexible targeting buttons
        const posButtons = screen.getAllByRole('button', { name: /\+Pos/i });
        const negButtons = screen.getAllByRole('button', { name: /\+Neg/i });
        expect(posButtons.length).toBe(2);
        expect(negButtons.length).toBe(2);

        // Click +Pos on lazynsfw
        fireEvent.click(posButtons[1]);
        expect(setPrompt).toHaveBeenCalledWith(
            expect.stringContaining('embedding:_lazy_embeddings_for_all_illus_lazynsfw_1833157.safetensors')
        );

        // Click +Neg on lazypos
        fireEvent.click(negButtons[0]);
        expect(setNegativePrompt).toHaveBeenCalledWith(
            expect.stringContaining('embedding:_lazy_embeddings_for_all_illus_lazypos_1833157.safetensors')
        );
    });
});

