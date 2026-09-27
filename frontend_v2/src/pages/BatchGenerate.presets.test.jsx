import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import BatchGenerate from './BatchGenerate';
import useSettingsStore from '../store/settingsStore';
import { useGeneratorStore } from '../store/generatorStore';

const mockToast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const fetchMock = vi.hoisted(() => vi.fn());

vi.mock('react-hot-toast', () => ({ default: mockToast }));

// Deliberately free of "xl"/"sdxl"/"flux" hints: the generator store
// auto-applies per-architecture defaults when a checkpoint carries a base model,
// which would rewrite steps/cfg/sampler underneath the assertions below.
const INSTALLED_FILES = {
    'models/checkpoints': [{ name: 'dreamer.safetensors', display_name: 'Dreamer' }],
    'models/loras': [{ name: 'style.safetensors', display_name: 'Style' }],
    'models/vae': [{ name: 'extra_vae.safetensors', display_name: 'Extra VAE' }],
};

const JSON_HEADERS = new Headers({ 'content-type': 'application/json' });

function jsonResponse(body, status = 200) {
    return { ok: status >= 200 && status < 300, status, headers: JSON_HEADERS, json: async () => body };
}

const INITIAL_GENERATOR_STATE = { ...useGeneratorStore.getState() };

function renderPage() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
        <QueryClientProvider client={queryClient}>
            <BatchGenerate />
        </QueryClientProvider>
    );
    return { queryClient };
}

function postCalls() {
    return fetchMock.mock.calls.filter((call) => call[1]?.method === 'POST');
}

function lastBatchBody() {
    return JSON.parse(postCalls()[postCalls().length - 1][1].body);
}

function savedPresets() {
    return useSettingsStore.getState().settings.generator.batchPresets;
}

function seedPreset(name, preset) {
    useSettingsStore.setState((state) => ({
        settings: {
            ...state.settings,
            generator: {
                ...state.settings.generator,
                batchPresets: { ...state.settings.generator.batchPresets, [name]: preset },
            },
        },
    }));
}

/** The model lists arrive from React Query, so a <select> has no options yet. */
async function waitForModelOptions() {
    await waitFor(() => {
        expect(screen.getByRole('option', { name: 'Dreamer' })).toBeInTheDocument();
        expect(screen.getByRole('option', { name: 'extra_vae.safetensors' })).toBeInTheDocument();
    });
}

describe('BatchGenerate presets and control parity', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        window.localStorage.clear();
        useGeneratorStore.setState({ ...INITIAL_GENERATOR_STATE });
        useSettingsStore.getState().resetSettings();
        globalThis.fetch = fetchMock;

        fetchMock.mockImplementation((url, init = {}) => {
            if ((init.method || 'GET') === 'POST') {
                const count = JSON.parse(init.body).workflows.length;
                return Promise.resolve(jsonResponse({
                    count,
                    jobs: Array.from({ length: count }, (_, index) => ({
                        id: `j${index}`,
                        status: 'queued',
                        metadata: { prompt: `prompt-${index}` },
                    })),
                }));
            }
            const directory = new URL(String(url), 'http://localhost').searchParams.get('directory');
            return Promise.resolve(jsonResponse({
                files: INSTALLED_FILES[directory] || [],
                total: (INSTALLED_FILES[directory] || []).length,
            }));
        });
    });

    describe('control parity with Simple Generate', () => {
        it('puts every shared control into the submitted payload', async () => {
            renderPage();
            await waitForModelOptions();
            fireEvent.change(screen.getByLabelText('Steps'), { target: { value: '9' } });
            fireEvent.change(screen.getByLabelText('CFG'), { target: { value: '4.5' } });
            fireEvent.change(screen.getByLabelText('Clip Skip'), { target: { value: '3' } });
            fireEvent.change(screen.getByLabelText('Sampler'), { target: { value: 'dpmpp_sde' } });
            fireEvent.change(screen.getByLabelText('Scheduler'), { target: { value: 'karras' } });
            fireEvent.change(screen.getByLabelText('VAE'), { target: { value: 'extra_vae.safetensors' } });
            fireEvent.change(screen.getByLabelText('Checkpoint'), { target: { value: 'dreamer.safetensors' } });
            fireEvent.change(screen.getByLabelText('Negative Prompt'), { target: { value: 'blurry' } });
            fireEvent.change(screen.getByLabelText('Batch Size (images per prompt)'), { target: { value: '2' } });

            fireEvent.click(screen.getByRole('button', { name: /Generate 8 Images/ }));
            await waitFor(() => expect(postCalls()).toHaveLength(1));

            const { options, metadata } = lastBatchBody().workflows[0];
            expect(options).toMatchObject({
                mode: 't2i',
                steps: 9,
                cfg: 4.5,
                clipSkip: 3,
                sampler: 'dpmpp_sde',
                scheduler: 'karras',
                vae: 'extra_vae.safetensors',
                checkpoint: 'dreamer.safetensors',
                negativePrompt: 'blurry',
                batchSize: 2,
            });
            expect(metadata).toMatchObject({
                checkpoint: 'dreamer.safetensors',
                sampler: 'dpmpp_sde',
                steps: 9,
            });
        });

        it('shares the seed with Simple Generate and derives increment seeds from it', async () => {
            renderPage();
            fireEvent.click(screen.getByText('increment'));
            fireEvent.change(screen.getByPlaceholderText('Base seed'), { target: { value: '42' } });

            // The base seed is the shared generator-store seed, not a page copy.
            expect(useGeneratorStore.getState().seed).toBe(42);

            fireEvent.click(screen.getByRole('button', { name: /Generate 4 Images/ }));
            await waitFor(() => expect(postCalls()).toHaveLength(1));
            expect(lastBatchBody().workflows.map((wf) => wf.options.seed)).toEqual([42, 43, 44, 45]);
        });

        it('randomises the shared seed from the page', () => {
            renderPage();
            const before = useGeneratorStore.getState().seed;
            fireEvent.click(screen.getByRole('button', { name: 'Randomize seed' }));
            expect(useGeneratorStore.getState().seed).not.toBe(before);
        });
    });

    describe('user presets', () => {
        it('persists a created preset and shows what is inside it', () => {
            renderPage();
            fireEvent.change(screen.getByLabelText('Steps'), { target: { value: '9' } });
            fireEvent.change(screen.getByLabelText('Sampler'), { target: { value: 'dpmpp_sde' } });
            fireEvent.change(screen.getByPlaceholderText('e.g. Elara Moonwhisper'), { target: { value: 'Elara' } });
            fireEvent.change(screen.getByPlaceholderText('Preset name'), { target: { value: 'My Sheet' } });
            fireEvent.click(screen.getByRole('button', { name: 'Save' }));

            const stored = savedPresets()['My Sheet'];
            expect(stored).toMatchObject({
                name: 'My Sheet',
                bakedType: 'character_sheet',
                charName: 'Elara',
                steps: 9,
                sampler: 'dpmpp_sde',
                seedMode: 'random',
            });
            expect(stored.prompts).toHaveLength(4);

            // The picker describes the configuration, not just the name.
            expect(screen.getByText('My Sheet')).toBeInTheDocument();
            expect(screen.getByText(/9 steps/)).toBeInTheDocument();
            expect(screen.getByText(/dpmpp_sde\/normal/)).toBeInTheDocument();
        });

        it('round-trips a per-LoRA weight through save and load', async () => {
            renderPage();
            await waitForModelOptions();
            fireEvent.click(screen.getByRole('button', { name: /Add LoRA/ }));
            await screen.findByRole('option', { name: 'style.safetensors' });
            fireEvent.change(screen.getByLabelText('LoRA 1 model'), { target: { value: 'style.safetensors' } });
            fireEvent.change(screen.getByLabelText('LoRA 1 strength'), { target: { value: '0.65' } });
            // The store's model object (name + display_name) is kept by the
            // shared addLora/updateLora actions; the weight is what a preset owns.
            expect(useGeneratorStore.getState().selectedLoras[0])
                .toMatchObject({ name: 'style.safetensors', strength: 0.65 });

            fireEvent.change(screen.getByPlaceholderText('Preset name'), { target: { value: 'Weights' } });
            fireEvent.click(screen.getByRole('button', { name: 'Save' }));

            // Stored as a filename + weight, not the store's model object.
            expect(savedPresets().Weights.loras).toEqual([{ filename: 'style.safetensors', strength: 0.65 }]);

            // Drift the live weight, then reload the preset: the saved weight returns.
            fireEvent.change(screen.getByLabelText('LoRA 1 strength'), { target: { value: '1.5' } });
            expect(useGeneratorStore.getState().selectedLoras[0].strength).toBe(1.5);

            fireEvent.click(screen.getByRole('button', { name: 'Load preset Weights' }));
            expect(useGeneratorStore.getState().selectedLoras).toEqual([{ name: 'style.safetensors', strength: 0.65 }]);
            expect(screen.getByLabelText('LoRA 1 strength')).toHaveValue(0.65);

            fireEvent.click(screen.getByRole('button', { name: /Generate 4 Images/ }));
            await waitFor(() => expect(postCalls()).toHaveLength(1));
            expect(lastBatchBody().workflows[0].options.loras)
                .toEqual([{ name: 'style.safetensors', strength: 0.65 }]);
        });

        it('restores every field the preset owns', async () => {
            seedPreset('Full', {
                bakedType: 'scene_variations',
                prompts: ['a {scene} at dawn', 'a {scene} at dusk'],
                sceneName: 'Old Forest',
                seedMode: 'increment',
                negativePrompt: 'blurry',
                steps: 7,
                cfg: 3.5,
                sampler: 'ddim',
                scheduler: 'sgm_uniform',
                clipSkip: 2,
                batchSize: 3,
                width: 768,
                height: 1024,
                checkpoint: 'dreamer.safetensors',
                vae: 'extra_vae.safetensors',
                loras: [{ filename: 'style.safetensors', strength: 0.25 }],
            });
            renderPage();
            await waitForModelOptions();
            fireEvent.click(screen.getByRole('button', { name: 'Load preset Full' }));

            const store = useGeneratorStore.getState();
            expect(store.steps).toBe(7);
            expect(store.cfg).toBe(3.5);
            expect(store.sampler).toBe('ddim');
            expect(store.scheduler).toBe('sgm_uniform');
            expect(store.clipSkip).toBe(2);
            expect(store.batchSize).toBe(3);
            expect(store.width).toBe(768);
            expect(store.height).toBe(1024);
            expect(store.negativePrompt).toBe('blurry');
            expect(store.selectedCheckpoint.name).toBe('dreamer.safetensors');
            expect(store.selectedVae).toBe('extra_vae.safetensors');
            expect(store.selectedLoras).toEqual([{ name: 'style.safetensors', strength: 0.25 }]);

            // Batch-only fields come back too, and drive the generated prompts.
            expect(screen.getByPlaceholderText('e.g. Enchanted Forest')).toHaveValue('Old Forest');
            expect(screen.getByText('a Old Forest at dawn')).toBeInTheDocument();
            expect(screen.getByRole('button', { name: 'increment' })).toHaveAttribute('aria-pressed', 'true');
            expect(screen.getByRole('button', { name: /Generate 6 Images/ })).toBeInTheDocument();
        });

        it('renames, duplicates and deletes a preset', () => {
            seedPreset('Original', { steps: 12, loras: [] });
            renderPage();

            fireEvent.click(screen.getByRole('button', { name: 'Show details for Original' }));
            fireEvent.click(screen.getByRole('button', { name: 'Rename preset Original' }));
            fireEvent.change(screen.getByLabelText('Rename Original'), { target: { value: 'Renamed' } });
            fireEvent.click(screen.getByRole('button', { name: 'Confirm rename' }));
            expect(Object.keys(savedPresets())).toEqual(['Renamed']);

            fireEvent.click(screen.getByRole('button', { name: 'Duplicate Renamed' }));
            expect(Object.keys(savedPresets()).sort()).toEqual(['Renamed', 'Renamed copy']);

            fireEvent.click(screen.getByRole('button', { name: 'Delete Renamed' }));
            expect(Object.keys(savedPresets())).toEqual(['Renamed copy']);
        });

        it('refuses a rename that would collide', () => {
            seedPreset('A', { steps: 1 });
            seedPreset('B', { steps: 1 });
            renderPage();
            fireEvent.click(screen.getByRole('button', { name: 'Show details for A' }));
            fireEvent.click(screen.getByRole('button', { name: 'Rename preset A' }));
            fireEvent.change(screen.getByLabelText('Rename A'), { target: { value: 'B' } });
            fireEvent.click(screen.getByRole('button', { name: 'Confirm rename' }));
            expect(mockToast.error).toHaveBeenCalledWith('A preset named "B" already exists');
            expect(Object.keys(savedPresets()).sort()).toEqual(['A', 'B']);
        });

        it('imports a preset file, keeping the per-LoRA weight', async () => {
            renderPage();
            const payload = {
                kind: 'tnhcomfy.batch-preset',
                version: 1,
                name: 'Imported',
                preset: { steps: 15, loras: [{ filename: 'style.safetensors', strength: -0.5 }] },
            };
            const file = new File([JSON.stringify(payload)], 'preset.json', { type: 'application/json' });
            await fireEvent.change(screen.getByLabelText('Import preset JSON file'), { target: { files: [file] } });

            await waitFor(() => expect(savedPresets().Imported).toBeDefined());
            expect(savedPresets().Imported.loras).toEqual([{ filename: 'style.safetensors', strength: -0.5 }]);
            expect(mockToast.success).toHaveBeenCalledWith('Imported preset "Imported"');
        });

        it('reports a file it cannot read instead of failing silently', async () => {
            renderPage();
            const file = new File(['not json'], 'preset.json', { type: 'application/json' });
            await fireEvent.change(screen.getByLabelText('Import preset JSON file'), { target: { files: [file] } });
            await waitFor(() => expect(mockToast.error).toHaveBeenCalledWith('That file is not valid JSON'));
            expect(savedPresets()).toEqual({});
        });
    });

    describe('baked presets', () => {
        it('duplicates a baked preset to the user list without removing the original', () => {
            renderPage();
            fireEvent.click(screen.getByRole('button', { name: 'Duplicate Character Sheet to my presets' }));

            expect(savedPresets()['Character Sheet copy'].prompts).toEqual([
                'portrait of {char}, front view, neutral expression',
                'portrait of {char}, side profile, neutral expression',
                'portrait of {char}, three-quarter view, smiling',
                'portrait of {char}, close-up, detailed face',
            ]);
            // All four baked cards are still there — nothing is deleted.
            ['Character Sheet', 'Scene Variations', 'Concept Grid', 'Custom']
                .forEach((name) => expect(screen.getByText(name)).toBeInTheDocument());
        });

        it('captures the live configuration into the duplicate, not the baked defaults', () => {
            renderPage();
            fireEvent.change(screen.getByLabelText('CFG'), { target: { value: '2.5' } });
            fireEvent.click(screen.getByRole('button', { name: 'Duplicate Scene Variations to my presets' }));
            expect(savedPresets()['Scene Variations copy']).toMatchObject({ cfg: 2.5, bakedType: 'scene_variations' });
        });
    });

    describe('missing models', () => {
        it('warns before submit when a preset references an uninstalled model', async () => {
            seedPreset('Ghost', {
                checkpoint: 'ghost.safetensors',
                loras: [{ filename: 'ghost_lora.safetensors', strength: 0.5 }],
            });
            renderPage();
            await waitForModelOptions();

            // The picker already flags it; nothing has been submitted.
            expect(screen.getByRole('alert')).toHaveTextContent('checkpoint "ghost.safetensors"');
            expect(postCalls()).toHaveLength(0);

            fireEvent.click(screen.getByRole('button', { name: 'Load preset Ghost' }));
            const pageWarning = screen.getByText(/cannot resolve that model/).closest('div[role="alert"]');
            expect(pageWarning).toHaveTextContent('ghost.safetensors');
            expect(pageWarning).toHaveTextContent('ghost_lora.safetensors');
            expect(postCalls()).toHaveLength(0);
        });

        it('flags a preset in the picker even when it is not the loaded one', async () => {
            seedPreset('Ghost', { checkpoint: 'ghost.safetensors', loras: [] });
            renderPage();
            await waitForModelOptions();
            expect(screen.getByRole('alert')).toHaveTextContent('checkpoint "ghost.safetensors"');
        });

        it('stays quiet when every referenced model is installed', async () => {
            seedPreset('Fine', {
                checkpoint: 'dreamer.safetensors',
                loras: [{ filename: 'style.safetensors', strength: 1 }],
            });
            renderPage();
            await waitForModelOptions();
            fireEvent.click(screen.getByRole('button', { name: 'Load preset Fine' }));
            expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        });
    });

    describe('batch limit', () => {
        const sixtyOnePrompts = Array.from({ length: 61 }, (_, index) => `shot ${index}`).join('\n');

        it('blocks a submit above the backend cap and says why', async () => {
            renderPage();
            fireEvent.click(screen.getByText('Custom'));
            fireEvent.change(screen.getByLabelText('Custom prompt list'), { target: { value: sixtyOnePrompts } });

            expect(screen.getByRole('alert')).toHaveTextContent('61 workflows (limit 60)');
            const submit = screen.getByRole('button', { name: /Generate 61 Images/ });
            expect(submit).toBeDisabled();

            fireEvent.click(submit);
            await waitFor(() => expect(postCalls()).toHaveLength(0));
        });

        it('allows exactly the cap', async () => {
            renderPage();
            fireEvent.click(screen.getByText('Custom'));
            fireEvent.change(screen.getByLabelText('Custom prompt list'), {
                target: { value: sixtyOnePrompts.split('\n').slice(0, 60).join('\n') },
            });

            expect(screen.queryByRole('alert')).not.toBeInTheDocument();
            fireEvent.click(screen.getByRole('button', { name: /Generate 60 Images/ }));
            await waitFor(() => expect(postCalls()).toHaveLength(1));
            expect(lastBatchBody().workflows).toHaveLength(60);
        });

        it('surfaces the backend rejection when the cap is hit server-side anyway', async () => {
            // The exact body api/error_handlers.py renders for UploadValidationError.
            fetchMock.mockImplementation((url, init = {}) => {
                if ((init.method || 'GET') === 'POST') {
                    return Promise.resolve(jsonResponse({
                        error: 'Too many items requested: 61 (limit 60)',
                        code: 'BATCH_TOO_LARGE',
                        field: 'workflows',
                        details: { received: 61, max_items: 60 },
                    }, 400));
                }
                const directory = new URL(String(url), 'http://localhost').searchParams.get('directory');
                return Promise.resolve(jsonResponse({ files: INSTALLED_FILES[directory] || [], total: 0 }));
            });
            renderPage();
            fireEvent.click(screen.getByRole('button', { name: /Generate 4 Images/ }));

            await waitFor(() => expect(mockToast.error).toHaveBeenCalledTimes(1));
            expect(mockToast.error.mock.calls[0][0]).toBe(
                'Too many items requested: 61 (limit 60) (BATCH_TOO_LARGE)'
            );
            expect(screen.queryByText('Batch Jobs')).not.toBeInTheDocument();
        });
    });
});
