import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import BatchGenerate from '../pages/BatchGenerate';
import { useGeneratorStore } from '../store/generatorStore';
import useSettingsStore from '../store/settingsStore';

/**
 * The Batch page's two remaining lies.
 *
 *  1. It re-implemented the sampling and resolution controls and dropped the
 *     `lockedParams` guard. The shared components guard locked parameters
 *     (`SamplingSettings`: `if (!lockedParams.steps) setSteps(...)`) and the
 *     store's bulk writer skips locked keys - but the store's INDIVIDUAL
 *     setters know nothing about the locks, so loading a preset overwrote a
 *     locked step count, a locked resolution and a locked sampler.
 *
 *  2. The "Auto (default)" checkpoint option had no default behind it: it
 *     meant "send no checkpoint at all", the backend's own fallback is an
 *     empty string, and the preflight reported a missing model with an empty
 *     name. The server HAS a default - the configured one, and the
 *     compiled-in one the settings schema documents - so "Auto" now names a
 *     real model, and a request that would name no model at all is refused.
 */

const mockToast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const fetchMock = vi.hoisted(() => vi.fn());

vi.mock('react-hot-toast', () => ({ default: mockToast }));

const INSTALLED_FILES = {
    'models/checkpoints': [{ name: 'dreamer.safetensors', display_name: 'Dreamer' }],
    'models/loras': [],
    'models/vae': [],
};

const JSON_HEADERS = new Headers({ 'content-type': 'application/json' });

function jsonResponse(body, status = 200) {
    return { ok: status >= 200 && status < 300, status, headers: JSON_HEADERS, json: async () => body };
}

const INITIAL_GENERATOR_STATE = { ...useGeneratorStore.getState() };

/** What the server says its default checkpoint is. `null` = it says nothing. */
let serverDefaultCheckpoint = null;

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

function batchPostCalls() {
    return postCalls().filter((call) => String(call[0]).includes('/api/generate/batch'));
}

/** A user preset, in the settings store the page reads them from. */
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

describe('the Batch page and the locked parameters', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        serverDefaultCheckpoint = null;
        useGeneratorStore.setState({
            ...INITIAL_GENERATOR_STATE,
            steps: 20,
            cfg: 3,
            selectedCheckpoint: { name: 'dreamer.safetensors', display_name: 'Dreamer' },
            lockedParams: { ...INITIAL_GENERATOR_STATE.lockedParams },
        });
        globalThis.fetch = fetchMock;

        fetchMock.mockImplementation((url, init = {}) => {
            const href = String(url);
            if ((init.method || 'GET') === 'POST') {
                if (href.includes('/api/jobs/validate')) {
                    return Promise.resolve(jsonResponse({
                        valid: true,
                        eligible_providers: ['p1'],
                        global_missing: {},
                    }));
                }
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
            if (href.includes('/api/settings/schema')) {
                return Promise.resolve(jsonResponse({
                    generator: { fields: { default_checkpoint: { default: 'compiled-in.safetensors' } } },
                }));
            }
            if (href.includes('/api/settings')) {
                return Promise.resolve(jsonResponse({
                    settings: {
                        generator: serverDefaultCheckpoint
                            ? { default_checkpoint: serverDefaultCheckpoint }
                            : {},
                    },
                }));
            }
            const directory = new URL(href, 'http://localhost').searchParams.get('directory');
            return Promise.resolve(jsonResponse({
                files: INSTALLED_FILES[directory] || [],
                total: (INSTALLED_FILES[directory] || []).length,
            }));
        });
    });

    it('does not overwrite a locked parameter when it loads a preset', async () => {
        useGeneratorStore.setState({
            steps: 20,
            cfg: 3,
            lockedParams: { ...INITIAL_GENERATOR_STATE.lockedParams, steps: true },
        });
        seedPreset('Locked', { steps: 7, cfg: 3.5, prompts: ['a {char}'] });

        renderPage();

        fireEvent.click(screen.getByRole('button', { name: 'Load preset Locked' }));

        // The preset's own values (7 steps, CFG 3.5). The locked one stays.
        expect(useGeneratorStore.getState().steps).toBe(20);
        expect(useGeneratorStore.getState().cfg).toBe(3.5);
    });

    it('locks the inline controls it locks', () => {
        useGeneratorStore.setState({
            steps: 20,
            lockedParams: { ...INITIAL_GENERATOR_STATE.lockedParams, steps: true },
        });

        renderPage();

        const stepsInput = screen.getByLabelText('Steps');
        expect(stepsInput).toBeDisabled();

        fireEvent.change(stepsInput, { target: { value: '9' } });
        expect(useGeneratorStore.getState().steps).toBe(20);
    });
});

describe('the Batch page and the default checkpoint', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        serverDefaultCheckpoint = null;
        useGeneratorStore.setState({
            ...INITIAL_GENERATOR_STATE,
            selectedCheckpoint: null,
            lockedParams: { ...INITIAL_GENERATOR_STATE.lockedParams },
        });
        globalThis.fetch = fetchMock;

        fetchMock.mockImplementation((url, init = {}) => {
            const href = String(url);
            if ((init.method || 'GET') === 'POST') {
                if (href.includes('/api/jobs/validate')) {
                    return Promise.resolve(jsonResponse({
                        valid: true,
                        eligible_providers: ['p1'],
                        global_missing: {},
                    }));
                }
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
            if (href.includes('/api/settings/schema')) {
                return Promise.resolve(jsonResponse({
                    generator: { fields: { default_checkpoint: { default: 'compiled-in.safetensors' } } },
                }));
            }
            if (href.includes('/api/settings')) {
                return Promise.resolve(jsonResponse({
                    settings: {
                        generator: serverDefaultCheckpoint
                            ? { default_checkpoint: serverDefaultCheckpoint }
                            : {},
                    },
                }));
            }
            const directory = new URL(href, 'http://localhost').searchParams.get('directory');
            return Promise.resolve(jsonResponse({
                files: INSTALLED_FILES[directory] || [],
                total: (INSTALLED_FILES[directory] || []).length,
            }));
        });
    });

    it('resolves "Auto (default)" to the server\'s default checkpoint', async () => {
        serverDefaultCheckpoint = 'dreamer.safetensors';

        renderPage();

        await waitFor(() => expect(
            screen.getByRole('option', { name: 'Auto (default: dreamer.safetensors)' })
        ).toBeInTheDocument(), { timeout: 10_000 });

        fireEvent.click(screen.getByRole('button', { name: /Generate 4 Images/ }));
        await waitFor(() => expect(batchPostCalls()).toHaveLength(1));

        const body = JSON.parse(batchPostCalls()[0][1].body);
        // The request names a real model, instead of nothing at all.
        expect(body.workflows[0].options.checkpoint).toBe('dreamer.safetensors');
    });

    it('refuses to submit a request that would name no model', () => {
        renderPage();

        // Nothing is selected and the server has no default to fall back on.
        expect(screen.getByRole('option', { name: 'None — pick a checkpoint' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Generate 4 Images/ })).toBeDisabled();
    });
});
