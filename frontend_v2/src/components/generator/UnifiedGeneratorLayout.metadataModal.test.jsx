import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import UnifiedGeneratorLayout from './UnifiedGeneratorLayout';

vi.mock('../../hooks/useGeneratorCore', () => ({
    useGeneratorCore: () => ({
        store: {
            prompt: 'test prompt',
            negativePrompt: 'test neg',
            selectedCheckpoint: { name: 'test_model.safetensors', display_name: 'Test Model Checkpoint', civitai_id: 12345 },
            selectedVae: 'Baked in',
            selectedClip: null,
            selectedClip2: null,
            selectedLoras: [],
            controlnets: [],
            ipAdapters: [],
            hiresFix: false,
            setPrompt: vi.fn(),
            setNegativePrompt: vi.fn(),
            setSelectedCheckpoint: vi.fn(),
            setSelectedVae: vi.fn(),
            addLora: vi.fn(),
            removeLora: vi.fn(),
            updateLora: vi.fn(),
            addTriggerWords: vi.fn(),
        },
        providers: [],
        providersLoading: false,
        preflight: {
            isChecking: false,
            summary: null,
            isMissingModelsOpen: false,
            setIsMissingModelsOpen: vi.fn(),
        },
        models: {
            checkpoints: [{ name: 'test_model.safetensors', display_name: 'Test Model Checkpoint', civitai_id: 12345 }],
            unetModels: [],
            vaeModels: [],
            clipModels: [],
            embeddingModels: [],
            promptShortcuts: [],
        },
    }),
}));

vi.mock('./PromptPanel', () => ({ default: () => <div data-testid="prompt-panel" /> }));
vi.mock('./SamplingSettings', () => ({ default: () => <div data-testid="sampling-settings" /> }));
vi.mock('./ResolutionSettings', () => ({ default: () => <div data-testid="resolution-settings" /> }));
vi.mock('./GeneratorReadinessPanel', () => ({ default: () => <div data-testid="readiness-panel" /> }));
vi.mock('./GeneratorShell', () => ({
    default: ({ leftColumn, rightColumn }) => (
        <div data-testid="generator-shell">
            <div data-testid="left-col">{leftColumn}</div>
            <div data-testid="right-col">{rightColumn}</div>
        </div>
    ),
}));

describe('UnifiedGeneratorLayout ModelMetadataModal integration', () => {
    it('opens ModelMetadataModal with proper metadata when info button is clicked', async () => {
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        render(
            <QueryClientProvider client={queryClient}>
                <MemoryRouter>
                    <UnifiedGeneratorLayout
                        mode="t2i"
                        showAdvancedSampling={true}
                        showAdvancedSections={true}
                    />
                </MemoryRouter>
            </QueryClientProvider>
        );

        // Find the "View Model Details" info button in TriggerBox
        const infoButton = screen.getByRole('button', { name: /View details for test_model\.safetensors/i });
        expect(infoButton).toBeInTheDocument();

        // Click info button
        fireEvent.click(infoButton);

        // The ModelMetadataModal dialog should now be open with the model's display name
        expect(await screen.findByRole('dialog')).toBeInTheDocument();
        expect(screen.getAllByText('Test Model Checkpoint').length).toBeGreaterThan(0);
    });
});
