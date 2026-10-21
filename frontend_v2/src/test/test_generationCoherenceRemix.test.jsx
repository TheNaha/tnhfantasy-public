import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * "Quick Remix" rebuilds a request from a finished job's metadata.
 *
 * It used to be a SECOND request builder: it assembled its own options
 * object and posted them itself, and it never ran the preflight. The two
 * builders did not agree:
 *
 *  - The guided metadata carries only `checkpoint` and `vae`, so the remix
 *    read `meta.unet` and `meta.clip` as undefined and sent
 *    `unet: undefined, clip: undefined, checkpoint: "flux1-dev.safetensors"`.
 *    The backend then built `CheckpointLoaderSimple{ckpt_name:
 *    "flux1-dev.safetensors"}` - a UNET file asked of models/checkpoints/,
 *    where it does not exist.
 *  - The model type and the IP adapter's "Stop At" were lost.
 *  - `strength || 1.0` turned a LoRA the user had deliberately turned off
 *    back on to full strength.
 *
 * The remix goes through the shared builder now, and through the preflight.
 */

const generateApiWorkflow = vi.hoisted(() => vi.fn());
const jobsApiValidate = vi.hoisted(() => vi.fn());
const apiGet = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock('../api', () => ({
    api: { get: apiGet, post: vi.fn(), put: vi.fn(), delete: vi.fn() },
    ApiError: class ApiError extends Error {},
    createIdempotencyKey: () => 'remix-key',
    generateApi: { workflow: generateApiWorkflow },
    jobsApi: { validate: jobsApiValidate },
}));

vi.mock('react-hot-toast', () => {
    const toast = vi.fn();
    toast.success = toastSuccess;
    toast.error = toastError;
    return { default: toast };
});

vi.mock('../components/ProgressiveImage', () => ({
    default: ({ alt }) => <img alt={alt} />,
}));

vi.mock('../components/ContextMenu', () => ({
    default: ({ children }) => children,
    createImageActions: () => [],
}));

/** A guided Flux job: a UNET model with two text encoders. */
const FLUX_METADATA = {
    type: 't2i',
    prompt: 'a cat',
    negativePrompt: 'blurry',
    seed: 42,
    steps: 20,
    cfg: 7,
    sampler: 'euler',
    scheduler: 'normal',
    width: 1024,
    height: 1024,
    checkpoint: {
        name: 'flux1-dev.safetensors',
        display_name: 'Flux 1 Dev',
        base_model: 'flux_1',
    },
    unet: 'flux1-dev.safetensors',
    clip: 't5xxl_fp16.safetensors',
    clip2: 'clip_l.safetensors',
    modelType: 'flux',
    vae: 'Baked in',
    loras: [{ name: 'style.safetensors', strength: 0 }],
    ipAdapters: [{
        model: 'ip-adapter-plus.safetensors',
        clipVision: 'clip_vision_h.safetensors',
        image: 'ref.png',
        weight: 0.8,
        stopAt: 0.4,
    }],
};

const ITEM = {
    id: 'asset-1',
    name: 'shot.png',
    filename: 'shot.png',
    workspace: 'main',
    relative_path: 'main/shot.png',
    metadata: FLUX_METADATA,
};

async function renderCard() {
    const FeedCardComponent = (await import('../components/dashboard/FeedCard')).default;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
        <QueryClientProvider client={client}>
            <MemoryRouter>
                <FeedCardComponent item={ITEM} workspace="main" />
            </MemoryRouter>
        </QueryClientProvider>
    );
    return client;
}

describe('Quick Remix', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        generateApiWorkflow.mockResolvedValue({ job: { id: 'job-1' } });
        jobsApiValidate.mockResolvedValue({
            valid: true,
            eligible_providers: ['p1'],
            global_missing: {},
        });
        apiGet.mockResolvedValue(FLUX_METADATA);
    });

    it('rebuilds the request with the shared builder', async () => {
        await renderCard();

        fireEvent.click(screen.getByRole('button', { name: 'Quick Remix (new seed)' }));

        await waitFor(() => expect(generateApiWorkflow).toHaveBeenCalledTimes(1));

        const [options, metadata, requestOptions] = generateApiWorkflow.mock.calls[0];

        // The UNET and its text encoders. Without them the backend asked
        // models/checkpoints/ for a file that lives in models/unet/.
        expect(options.unet).toBe('flux1-dev.safetensors');
        expect(options.clip).toBe('t5xxl_fp16.safetensors');
        expect(options.clip2).toBe('clip_l.safetensors');
        expect(options.checkpoint).toBeNull();
        expect(options.modelType).toBe('flux');

        // The kind is stated, so the API layer never has to infer it.
        expect(requestOptions.kind).toBe('guided');

        // The new seed is the remix's one change.
        expect(metadata.seed).not.toBe(42);
    });

    it('keeps a deliberate zero and the IP adapter\'s "Stop At"', async () => {
        await renderCard();

        fireEvent.click(screen.getByRole('button', { name: 'Quick Remix (new seed)' }));

        await waitFor(() => expect(generateApiWorkflow).toHaveBeenCalledTimes(1));

        const [options] = generateApiWorkflow.mock.calls[0];

        // `strength || 1.0` used to turn this back on to full strength.
        expect(options.loras[0].strength).toBe(0);
        expect(options.ipAdapters[0].stopAt).toBe(0.4);
    });

    it('runs the preflight before it submits', async () => {
        await renderCard();

        fireEvent.click(screen.getByRole('button', { name: 'Quick Remix (new seed)' }));

        await waitFor(() => expect(generateApiWorkflow).toHaveBeenCalledTimes(1));

        // The preflight is what tells the user that the model they are
        // remixing is not installed - instead of the job failing on the
        // provider a minute later.
        expect(jobsApiValidate).toHaveBeenCalledTimes(1);
        const [validated] = jobsApiValidate.mock.calls[0];
        expect(validated.unet).toBe('flux1-dev.safetensors');
    });

    it('does not submit when the preflight says a model is missing', async () => {
        jobsApiValidate.mockResolvedValue({
            valid: false,
            eligible_providers: [],
            global_missing: { checkpoints: ['flux1-dev.safetensors'] },
        });

        await renderCard();

        fireEvent.click(screen.getByRole('button', { name: 'Quick Remix (new seed)' }));

        await waitFor(() => expect(jobsApiValidate).toHaveBeenCalledTimes(1));
        expect(generateApiWorkflow).not.toHaveBeenCalled();
    });
});
