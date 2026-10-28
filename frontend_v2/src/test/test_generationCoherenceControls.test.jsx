import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Three controls that used to lie.
 *
 *  1. The ControlNet preprocessor dropdown offered Depth, OpenPose and
 *     Lineart. The backend implements ONLY Canny - every other value feeds
 *     the raw photo to the ControlNet as the control image, silently. So
 *     three of the five options were a control that did nothing.
 *
 *  2. The ADetailer detector list came from the provider's capabilities
 *     VERBATIM, and the provider's list is directory-prefixed
 *     (`detection/bbox/face_yolov8n.pt`) while the backend prefixes it again
 *     (`f"bbox/{options.adetailerModel}"`) - so the model that was loaded
 *     was `bbox/bbox/face_yolov8n.pt`, which does not exist.
 *
 *  3. The Hi-Res Fix card was rendered on every mode, with the VALUE
 *     suppressed outside t2i but the setter passed - so the card looked
 *     live, and clicking it wrote to the shared store: turning Hi-Res Fix ON
 *     for the Simple page from the Img2Img page.
 */

const store = vi.hoisted(() => ({ current: null }));

vi.mock('../hooks/useGeneratorCore', () => ({
    useGeneratorCore: () => ({
        store: store.current,
        providers: [],
        providersLoading: false,
        preflight: {
            isChecking: false,
            validationResult: {},
            summary: {},
            isMissingModelsOpen: false,
            setIsMissingModelsOpen: vi.fn(),
            runWithPreflight: vi.fn(),
        },
    }),
}));

vi.mock('../hooks/useActiveJobs', () => ({ useActiveJobs: () => ({ data: [] }) }));
vi.mock('../hooks/useModelDirectories', () => ({
    useModelDirectories: () => ({ modelsByKey: {}, loading: false }),
}));
vi.mock('../hooks/useProviderCapabilities', () => ({
    useProviderCapabilities: () => ({ capabilities: null, isLoading: false, isError: false }),
}));
vi.mock('../store/settingsStore', () => ({
    default: (sel) => sel({ settings: { generator: { prompt_shortcuts: {} }, ui: {} } }),
    useSettings: () => ({ settings: { generator: { prompt_shortcuts: {} }, ui: {} } }),
}));

/* The heavy children of the generator layout. The ControlNet and
 * Enhancements sections are left REAL - they are what is under test. */
vi.mock('../components/generator/PromptPanel', () => ({ default: () => null }));
vi.mock('../components/generator/ModelSection', () => ({ default: () => null }));
vi.mock('../components/generator/IPAdapterSection', () => ({ default: () => null }));
vi.mock('../api/files', () => ({
    default: {
        uploadInput: vi.fn(async () => ({
            status: 'success',
            filename: 'a1b2c3d4e5f6.png',
            path: 'models/input/a1b2c3d4e5f6.png',
            width: 512,
            height: 512,
        })),
    },
}));

vi.mock('../components/generator/GeneratorReadinessPanel', () => ({ default: () => null }));
vi.mock('../components/generator/SamplingSettings', () => ({ default: () => null }));
vi.mock('../components/generator/NoCheckpointCTA', () => ({ default: () => null }));
vi.mock('../components/ModelMetadataModal', () => ({ default: () => null }));

import ControlNetSection from '../components/generator/ControlNetSection';
import EnhancementsSection from '../components/generator/EnhancementsSection';
import UnifiedGeneratorLayout from '../components/generator/UnifiedGeneratorLayout';

describe('the ControlNet preprocessor dropdown', () => {
    it('offers only the preprocessors the backend implements', () => {
        render(
            <ControlNetSection
                controlnets={[{ name: 'canny.safetensors', image: 'ref.png', strength: 1, preprocessor: 'Canny' }]}
                addControlNet={vi.fn()}
                removeControlNet={vi.fn()}
                updateControlNet={vi.fn()}
                controlNetModels={[{ name: 'canny.safetensors' }]}
            />
        );

        // The selected option's TEXT is what a select is matched by.
        const select = screen.getByDisplayValue('Canny Edge');
        const values = Array.from(select.querySelectorAll('option')).map((o) => o.value);

        // `backend_v2/core/workflow_builder.py` builds preprocessor nodes for
        // "Canny", "Depth", and "OpenPose". Everything else feeds the raw
        // photo to the ControlNet.
        expect(values).toEqual(['None', 'Canny', 'Depth', 'OpenPose']);
        expect(screen.queryByRole('option', { name: 'Lineart' })).toBeNull();
    });

    it('stores the uploaded UUID filename, not the local file name', async () => {
        const updateControlNet = vi.fn();
        const { container } = render(
            <ControlNetSection
                controlnets={[{ name: 'canny.safetensors', image: '', strength: 1, preprocessor: 'Canny' }]}
                addControlNet={vi.fn()}
                removeControlNet={vi.fn()}
                updateControlNet={updateControlNet}
                controlNetModels={[{ name: 'canny.safetensors' }]}
            />
        );

        const input = container.querySelector('input[type="file"]');
        expect(input).not.toBeNull();
        const file = new File(['fake'], 'vacation-photo.jpg', { type: 'image/jpeg' });
        fireEvent.change(input, { target: { files: [file] } });

        // uploadInput is async and toast.promise resolves on a microtask, so
        // wait for the state update before asserting.
        await waitFor(() =>
            expect(updateControlNet).toHaveBeenCalledWith(0, 'image', 'a1b2c3d4e5f6.png')
        );
        expect(updateControlNet).not.toHaveBeenCalledWith(0, 'image', 'vacation-photo.jpg');
    });
});

/** The props the Enhancements panel needs to render. */
function enhancementProps(overrides = {}) {
    return {
        capabilities: null,
        modelType: 'sdxl',
        hiresFix: false,
        setHiresFix: vi.fn(),
        hiresUpscaler: 'Latent',
        setHiresUpscaler: vi.fn(),
        hiresDenoise: 0.3,
        setHiresDenoise: vi.fn(),
        hiresUpscale: 1.5,
        setHiresUpscale: vi.fn(),
        hiresSteps: 10,
        setHiresSteps: vi.fn(),
        upscalerModels: [],
        adetailer: true,
        setAdetailer: vi.fn(),
        adetailerModel: 'face_yolov8n.pt',
        setAdetailerModel: vi.fn(),
        adetailerPrompt: '',
        setAdetailerPrompt: vi.fn(),
        adetailerSteps: 20,
        setAdetailerSteps: vi.fn(),
        adetailerDenoise: 0.4,
        setAdetailerDenoise: vi.fn(),
        adetailerInpaintMasked: true,
        setAdetailerInpaintMasked: vi.fn(),
        adetailerModels: [],
        enableFreeU: false,
        setEnableFreeU: vi.fn(),
        enablePAG: false,
        setEnablePAG: vi.fn(),
        pagScale: 3,
        setPagScale: vi.fn(),
        enableLatentUpscale: false,
        setEnableLatentUpscale: vi.fn(),
        latentUpscaleMultiplier: 1.5,
        setLatentUpscaleMultiplier: vi.fn(),
        ...overrides,
    };
}

describe('the ADetailer detector list', () => {
    it('uses the bare file names from the provider\'s own list', () => {
        render(
            <EnhancementsSection
                {...enhancementProps({
                    capabilities: {
                        known: true,
                        nodes: { adetailer: true, detector: true },
                        models: { detector: ['detection/bbox/face_yolov8n.pt'] },
                    },
                })}
            />
        );

        // The backend prefixes the name AGAIN (`bbox/{name}`), so a
        // directory-prefixed name became `bbox/bbox/face_yolov8n.pt`.
        expect(screen.getByRole('option', { name: 'face_yolov8n.pt' })).toBeInTheDocument();
        expect(screen.queryByRole('option', { name: 'detection/bbox/face_yolov8n.pt' })).toBeNull();
    });

    it('keeps the local list when the provider has none', () => {
        render(
            <EnhancementsSection
                {...enhancementProps({
                    adetailerModel: '',
                    adetailerModels: [{ name: 'face_yolov8n.pt' }],
                })}
            />
        );

        expect(screen.getByRole('option', { name: 'face_yolov8n.pt' })).toBeInTheDocument();
    });
});

describe('the Hi-Res Fix card', () => {
    beforeEach(() => {
        store.current = {
            prompt: '', negativePrompt: '',
            selectedCheckpoint: null, selectedVae: 'Baked in', selectedClip: null, selectedClip2: null,
            selectedLoras: [], controlnets: [], ipAdapters: [],
            hiresFix: false, hiresUpscaler: 'Latent', hiresDenoise: 0.3, hiresUpscale: 1.5, hiresSteps: 10,
            // ADetailer is ON, so the Enhancements section is OPEN in every
            // mode - otherwise the card's absence would prove nothing.
            adetailer: true, adetailerModel: '', adetailerPrompt: '', adetailerSteps: 20,
            adetailerDenoise: 0.4, adetailerInpaintMasked: true,
            setPrompt: vi.fn(), setNegativePrompt: vi.fn(),
            setSelectedCheckpoint: vi.fn(), setSelectedVae: vi.fn(), setSelectedClip: vi.fn(),
            setSelectedClip2: vi.fn(), setHiresFix: vi.fn(), setHiresUpscaler: vi.fn(),
            setHiresDenoise: vi.fn(), setHiresUpscale: vi.fn(), setHiresSteps: vi.fn(),
            setAdetailer: vi.fn(), setAdetailerModel: vi.fn(), setAdetailerPrompt: vi.fn(),
            setAdetailerSteps: vi.fn(), setAdetailerDenoise: vi.fn(), setAdetailerInpaintMasked: vi.fn(),
            enableFreeU: false, setEnableFreeU: vi.fn(), enablePAG: false, setEnablePAG: vi.fn(),
            pagScale: 3, setPagScale: vi.fn(), enableLatentUpscale: false,
            setEnableLatentUpscale: vi.fn(), latentUpscaleMultiplier: 1.5,
            setLatentUpscaleMultiplier: vi.fn(),
            addLora: vi.fn(), removeLora: vi.fn(), updateLora: vi.fn(),
            addControlNet: vi.fn(), removeControlNet: vi.fn(), updateControlNet: vi.fn(),
            addIpAdapter: vi.fn(), removeIpAdapter: vi.fn(), updateIpAdapter: vi.fn(),
            addTriggerWords: vi.fn(),
        };
    });

    it('is offered where it can work', () => {
        render(
            <MemoryRouter>
                <UnifiedGeneratorLayout mode="t2i" />
            </MemoryRouter>
        );

        expect(screen.getByText('Hi-Res Fix')).toBeInTheDocument();
    });

    it('is not offered where it cannot work', () => {
        render(
            <MemoryRouter>
                <UnifiedGeneratorLayout mode="img2img" />
            </MemoryRouter>
        );

        // The card used to be rendered on every mode, with the setter passed
        // - so it looked live, and clicking it turned Hi-Res Fix ON for the
        // Simple page.
        expect(screen.queryByText('Hi-Res Fix')).toBeNull();
        // The section itself IS open - so the absence above is the card's,
        // not the section's.
        expect(screen.getByText('ADetailer')).toBeInTheDocument();
    });
});
