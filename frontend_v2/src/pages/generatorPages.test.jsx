/**
 * Wiring tests for the guided generator pages.
 *
 * These verify the Phase-2b migration: each page's `runSubmission` builds a
 * workflow and calls `generateApi.workflow` with the page-specific
 * idempotency key (`generate-simple` / `generate-img2img` / `generate-inpaint`),
 * routed through the shared `useGeneratorJob.handleGenerate`.
 *
 * The shared handleGenerate state machine itself is unit-tested separately in
 * `useGeneratorJob.test.js`; here we only assert the per-page wiring +
 * idempotency-key contract.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

/* ------------------------------------------------------------------ */
/* Hoisted mocks: spies + factories referenced from vi.mock below.     */
/* ------------------------------------------------------------------ */
const mocks = vi.hoisted(() => {
    const workflow = vi.fn();
    const navigate = vi.fn();
    const uploadMask = vi.fn(async () => ({ filename: 'mask.png' }));
    const fn = () => vi.fn();

    const makeStore = (o = {}) => ({
        prompt: 'a prompt', negativePrompt: 'bad prompt', seed: 42, steps: 20, cfg: 7,
        sampler: 'euler', scheduler: 'normal', width: 512, height: 512, batchSize: 1,
        selectedCheckpoint: { name: 'ckpt.safetensors' }, selectedVae: 'Baked in',
        selectedLoras: [], controlnets: [], ipAdapters: [],
        hiresFix: false, enableFreeU: false, enablePAG: false, pagScale: 3,
        enableLatentUpscale: false, latentUpscaleMultiplier: 1.5, clipSkip: 1, denoise: 0.75, maskBlur: 4,
        randomizeSeed: fn(),
        setPrompt: fn(), setNegativePrompt: fn(), setSelectedCheckpoint: fn(), setSelectedVae: fn(),
        setSelectedClip: fn(), setSelectedClip2: fn(), setHiresFix: fn(), setHiresUpscaler: fn(),
        setHiresDenoise: fn(), setHiresUpscale: fn(), setHiresSteps: fn(), setAdetailer: fn(),
        setAdetailerModel: fn(), setAdetailerPrompt: fn(), setAdetailerSteps: fn(),
        setAdetailerDenoise: fn(), setAdetailerInpaintMasked: fn(), addLora: fn(), removeLora: fn(),
        updateLora: fn(), addControlNet: fn(), removeControlNet: fn(), updateControlNet: fn(),
        addIpAdapter: fn(), removeIpAdapter: fn(), updateIpAdapter: fn(), addTriggerWords: fn(),
        setSourceImage: fn(), setDenoise: fn(), setMaskImage: fn(), setMaskBlur: fn(),
        clearSourceImage: fn(),
        ...o,
    });

    const makeCore = (o = {}) => ({
        store: makeStore(o),
        providers: [], providersLoading: false,
        preflight: {
            isChecking: false, validationResult: {}, summary: {},
            isMissingModelsOpen: false, setIsMissingModelsOpen: fn(),
            // runWithPreflight immediately invokes onValid (which calls generateApi.workflow)
            // and returns a successful submission result, mirroring the real flow.
            // Tolerant of both call shapes on purpose: `useGeneratorJob` passes
            // `(fn, { onValid })`, while SimpleGenerator's variations path calls
            // it as `runWithPreflight(options)` and does its own queueing. A
            // mock shaped to one caller fails the other for the wrong reason.
            runWithPreflight: async (...args) => {
                await args[1]?.onValid?.();
                return { ok: true, submissionResult: { id: 'job-1' } };
            },
        },
    });

    return { workflow, navigate, uploadMask, makeCore, storeOverrides: { value: {} }, settingsOverrides: { value: {} } };
});

/* Shared leaf mocks for hooks / providers / API / utility modules. */
vi.mock('../api', () => ({
    generateApi: { workflow: (...args) => mocks.workflow(...args) },
    createIdempotencyKey: (k) => k,
    filesApi: { uploadMask: (...args) => mocks.uploadMask(...args) },
}));
vi.mock('../api/config', () => ({ getApiUrl: () => '/api' }));
/* `../utils/workflowBuilder` used to be mocked here with a `WorkflowBuilder`
 * class. No such module and no such class: the pages import
 * `useWorkflowBuilder` from `../hooks/useWorkflowBuilder` and
 * `compileReactFlowToComfy` from `../utils/WorkflowCompiler`. The mock
 * protected nothing, and while it was here a class that did not exist could
 * have been "verified" by the suite. */
vi.mock('../utils/modelType', () => ({
    isUnetModel: () => false, isFluxModel: () => false,
    isAuraFlowModel: () => false, isPonyModel: () => false,
    // The whole module's surface. A mock that leaves a member out makes it
    // `undefined`, and the page throws when it calls it - which is how a
    // mock that protected nothing can still break the suite.
    resolveModelType: () => 'sd15',
}));
vi.mock('../constants/modelDirectories', () => ({ GENERATOR_MODEL_REQUESTS: [] }));

vi.mock('../hooks/useGeneratorCore', () => ({
    useGeneratorCore: () => mocks.makeCore(mocks.storeOverrides.value),
}));
vi.mock('../hooks/useActiveJobs', () => ({ useActiveJobs: () => ({ data: [] }) }));
/* The capabilities hook is a real React Query hook, and this file renders
   the pages without a QueryClientProvider - every other data hook it uses is
   mocked away. It is mocked here for the same reason. */
vi.mock('../hooks/useProviderCapabilities', () => ({
    useProviderCapabilities: () => ({ capabilities: null, isLoading: false, isError: false }),
}));
/* AdvancedGenerator reaches for these two directly instead of through
   useGeneratorCore. */
vi.mock('../hooks/useProvidersPageData', () => ({
    default: () => ({ providers: [], isLoading: false }),
}));
vi.mock('../hooks/useGenerationPreflight', () => ({
    default: () => mocks.makeCore().preflight,
}));vi.mock('../hooks/useModelDirectories', () => ({ useModelDirectories: () => ({ modelsByKey: {} }) }));
vi.mock('../hooks/useJobStatus', () => ({ useJobStatus: () => ({ data: null }) }));
vi.mock('../hooks/useKeyboardShortcuts', () => ({ useKeyboardShortcuts: () => {} }));
vi.mock('../store/settingsStore', () => ({
    default: (sel) => sel({
        settings: {
            generator: {
                autoRandomizeSeed: false,
                redirectAfterGenerate: true,
                redirectDelay: 0,
                prompt_shortcuts: {},
                ...mocks.settingsOverrides.value,
            },
        },
    }),
    useSettings: () => ({
        settings: {
            generator: {
                autoRandomizeSeed: false,
                redirectAfterGenerate: true,
                redirectDelay: 0,
                prompt_shortcuts: {},
                ...mocks.settingsOverrides.value,
            },
        },
    }),
}));
vi.mock('react-router-dom', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        useNavigate: () => mocks.navigate,
        useLocation: () => ({ state: undefined }),
    };
});
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));

/* Stub all heavy child components so the page renders without pulling in their
   own hook/provider graphs (which would cascade into a mock explosion).
   vi.mock must be top-level (hoisted) — not wrapped in a helper. */
vi.mock('../components/ModelMetadataModal', () => ({ default: () => null }));
vi.mock('../components/generator/MissingModelsDialog', () => ({ default: () => null }));
vi.mock('../components/generator/GeneratorReadinessPanel', () => ({ default: () => null }));
vi.mock('../components/generator/PromptPanel', () => ({ default: () => null }));
vi.mock('../components/generator/GeneratorTabs', () => ({ default: () => null }));
vi.mock('../components/generator/ModelSection', () => ({ default: () => null }));
vi.mock('../components/generator/ControlNetSection', () => ({ default: () => null }));
vi.mock('../components/generator/IPAdapterSection', () => ({ default: () => null }));
vi.mock('../components/generator/EnhancementsSection', () => ({ default: () => null }));
vi.mock('../components/generator/ResolutionSettings', () => ({ default: () => null }));
vi.mock('../components/generator/SamplingSettings', () => ({ default: () => null }));
vi.mock('../components/generator/ImageUploader', () => ({ default: () => null }));
vi.mock('../components/generator/PresetManager', () => ({ default: () => null }));
vi.mock('../components/ModelSelector', () => ({ default: () => null }));
vi.mock('../components/generator/InpaintCanvas', () => ({ default: () => null }));
/* GenerateButtonBar (Simple only) — expose a clickable button wired to onGenerate,
   and one wired to onGenerateVariations so the seed-variations path is reachable
   without rendering the real (menu-and-dropdown) button bar. */
vi.mock('../components/generator/GenerateButtonBar', () => ({
    default: ({ onGenerate, onGenerateVariations }) =>
        React.createElement(
            'div',
            null,
            React.createElement('button', { 'data-testid': 'simple-generate', onClick: () => onGenerate() }, 'Generate'),
            React.createElement('button', { 'data-testid': 'simple-variations', onClick: () => onGenerateVariations(2) }, 'Variations'),
        ),
}));
vi.mock('../components/generator/ReactFlowEditor', () => ({ default: () => null }));

const renderInRouter = (Page) =>
    render(<MemoryRouter><Page /></MemoryRouter>);

const assertWired = async (key, expectedNavigate = false) => {
    await waitFor(() => expect(mocks.workflow).toHaveBeenCalledTimes(1));
    expect(mocks.workflow).toHaveBeenCalledWith(
        expect.any(Object),
        expect.any(Object),
        { idempotencyKey: key },
    );
    if (expectedNavigate) {
        // Not synchronous any more, and that is the point of the change: the
        // redirect is armed at submit for exactly `redirectDelay` ms, so even
        // `redirectDelay: 0` goes through a timer. Waiting for it is the
        // assertion; loosening it to accept zero calls would pass whether or
        // not the redirect was ever wired up.
        await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/gallery'));
    } else {
        expect(mocks.navigate).not.toHaveBeenCalled();
    }
};

beforeEach(() => {
    mocks.workflow.mockClear();
    mocks.navigate.mockClear();
    mocks.uploadMask.mockClear();
    mocks.storeOverrides.value = {};
    mocks.settingsOverrides.value = {};
});

describe('SimpleGenerator wiring', () => {
    it('submits with idempotencyKey `generate-simple` and redirects to /gallery', async () => {
        const { default: SimpleGenerator } = await import('./SimpleGenerator');
        renderInRouter(SimpleGenerator);
        fireEvent.click(screen.getAllByTestId('simple-generate')[0]);
        await assertWired('generate-simple', true);
    });
});

describe('SimpleGenerator seed variations', () => {
    async function generateVariations() {
        const { default: SimpleGenerator } = await import('./SimpleGenerator');
        renderInRouter(SimpleGenerator);
        // This file does not clean up between cases, so queries use `All…[0]`
        // throughout; see the existing `simple-generate` cases.
        fireEvent.click(screen.getAllByTestId('simple-variations')[0]);
    }

    it('queues one job per variation with its own idempotency key', async () => {
        await generateVariations();
        await waitFor(() => expect(mocks.workflow).toHaveBeenCalledTimes(2));
        expect(mocks.workflow).toHaveBeenCalledWith(
            expect.any(Object), expect.any(Object), { idempotencyKey: 'generate-variation-0' },
        );
        expect(mocks.workflow).toHaveBeenCalledWith(
            expect.any(Object), expect.any(Object), { idempotencyKey: 'generate-variation-1' },
        );
    });

    it('honours redirectDelay instead of navigating synchronously', async () => {
        // 300ms is long enough to be unambiguously "not yet" by the time the
        // assertions below run, and short enough not to need fake timers.
        mocks.settingsOverrides.value = { redirectDelay: 300 };
        await generateVariations();
        await waitFor(() => expect(mocks.workflow).toHaveBeenCalledTimes(2));

        // Queued, but the redirect is still pending: the whole point of the
        // setting is to let the queued jobs appear in the gallery first. The old
        // code navigated on the `await Promise.all`, so this was true for zero
        // milliseconds whatever the slider said.
        expect(mocks.navigate).not.toHaveBeenCalled();

        await waitFor(() => expect(mocks.navigate).toHaveBeenCalledWith('/gallery'));
    });

    it('does not redirect at all when redirectAfterGenerate is off', async () => {
        mocks.settingsOverrides.value = { redirectAfterGenerate: false };
        await generateVariations();
        await vi.waitFor(() => expect(mocks.workflow).toHaveBeenCalledTimes(2));
        // Long enough for any redirect timer to have fired.
        await new Promise((resolve) => setTimeout(resolve, 60));
        expect(mocks.navigate).not.toHaveBeenCalled();
    });
});

describe('Img2ImgGenerator wiring', () => {
    it('submits with idempotencyKey `generate-img2img` (source image present, redirects to /gallery)', async () => {
        mocks.storeOverrides.value = {
            sourceImage: { filename: 'src.png', width: 512, height: 512 },
        };
        const { default: Img2ImgGenerator } = await import('./Img2ImgGenerator');
        renderInRouter(Img2ImgGenerator);
        fireEvent.click(screen.getAllByRole('button', { name: /generate img2img/i })[0]);
        await assertWired('generate-img2img', true);
    });
});

describe('InpaintGenerator wiring', () => {
    it('uploads mask then submits with idempotencyKey `generate-inpaint` (redirects to /gallery)', async () => {
        mocks.storeOverrides.value = {
            sourceImage: { filename: 'src.png', width: 512, height: 512, previewUrl: 'blob:x' },
            maskImage: { data: 'mask-data' },
        };
        const { default: InpaintGenerator } = await import('./InpaintGenerator');
        renderInRouter(InpaintGenerator);
        fireEvent.click(screen.getAllByRole('button', { name: /generate inpaint/i })[0]);
        await waitFor(() => expect(mocks.uploadMask).toHaveBeenCalledWith(
            { data: 'mask-data' }, 'src.png',
        ));
        await assertWired('generate-inpaint', true);
    });
});

describe('AdvancedGenerator wiring', () => {
    it('submits through the shared hook handler and stays on the editor', async () => {
        const { default: AdvancedGenerator } = await import('./AdvancedGenerator');
        renderInRouter(AdvancedGenerator);
        fireEvent.click(screen.getByRole('button', { name: /run workflow/i }));

        await waitFor(() => expect(mocks.workflow).toHaveBeenCalledTimes(1));
        expect(mocks.workflow).toHaveBeenCalledWith(
            expect.any(Object),
            expect.any(Object),
            { idempotencyKey: 'generate-advanced' },
        );
        // `redirectAfterGenerate` is on by default; the advanced editor must
        // override it or every run would navigate off the graph.
        expect(mocks.navigate).not.toHaveBeenCalled();
    });

    it('says out loud that the global auto-randomize seed setting does not apply here', async () => {
        mocks.settingsOverrides.value = { autoRandomizeSeed: true };
        const { default: AdvancedGenerator } = await import('./AdvancedGenerator');
        renderInRouter(AdvancedGenerator);

        expect(
            screen.getByText(/auto-randomize seed does not apply in advanced mode/i)
        ).toBeInTheDocument();
    });
});
