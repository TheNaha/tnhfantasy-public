import { render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Regression test for the 2026-10-01 audit.
 *
 * The dashboard's "Copy Asset" action posted `{ copy: true }` to
 * `POST /api/v2/assets/{id}/move`. `MoveAssetRequest` declares `copy_file`, so
 * pydantic dropped `copy` without complaint, `copy_file` stayed False, and the
 * handler took the `os.rename` branch — the "copy" moved the original file off
 * disk and the UI toasted "Asset copied". Silent data loss behind a success
 * message, from a field name pydantic drops by design.
 *
 * The test drives the real handler rather than reading the source, so it fails
 * if the field is misspelled again for any reason.
 */

const apiPost = vi.fn();
const confirmFn = vi.fn();
const imageActions = {};

vi.mock('../../api', () => ({
    api: {
        get: vi.fn().mockResolvedValue({}),
        post: (...args) => apiPost(...args),
        delete: vi.fn().mockResolvedValue({}),
    },
    ApiError: class ApiError extends Error {},
    createIdempotencyKey: () => 'key',
    generateApi: () => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }),
}));

vi.mock('../../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: confirmFn }),
}));

vi.mock('../../store/settingsStore', () => ({
    default: () => ({ settings: {} }),
}));

vi.mock('react-hot-toast', () => {
    const toast = vi.fn();
    toast.success = vi.fn();
    toast.error = vi.fn();
    return { default: toast };
});

vi.mock('../ProgressiveImage', () => ({
    default: ({ alt }) => <img alt={alt} />,
}));

vi.mock('../ContextMenu', () => ({
    default: () => null,
    createImageActions: (handlers) => {
        Object.assign(imageActions, handlers);
        return [];
    },
}));

const ITEM = {
    id: 'asset-1',
    name: 'shot.png',
    filename: 'shot.png',
    workspace: 'main',
    relative_path: 'main/shot.png',
};

async function renderCard() {
    const FeedCard = (await import('./FeedCard')).default;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
        <QueryClientProvider client={client}>
            <MemoryRouter>
                <FeedCard item={ITEM} workspace="main" />
            </MemoryRouter>
        </QueryClientProvider>
    );
    await waitFor(() => expect(imageActions.onCopyAsset).toBeTypeOf('function'));
    return imageActions;
}

describe('FeedCard asset move/copy payload', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        Object.keys(imageActions).forEach((k) => delete imageActions[k]);
        apiPost.mockResolvedValue({});
        confirmFn.mockResolvedValue(true);
        // `prompt()` is how the handler asks for the destination workspace.
        vi.spyOn(window, 'prompt').mockReturnValue('archive');
    });

    it('sends copy_file, not copy, for Copy Asset', async () => {
        const actions = await renderCard();
        await actions.onCopyAsset();

        expect(apiPost).toHaveBeenCalledTimes(1);
        const [url, body] = apiPost.mock.calls[0];
        expect(url).toBe('/api/v2/assets/asset-1/move');
        expect(body.copy_file).toBe(true);
        // The misspelling is asserted absent, not merely unused: pydantic drops
        // unknown keys silently, which is how the original bug was invisible.
        expect(body).not.toHaveProperty('copy');
    });

    it('sends copy_file: false for Move Asset', async () => {
        const actions = await renderCard();
        await actions.onMoveAsset();

        const [, body] = apiPost.mock.calls[0];
        expect(body.copy_file).toBe(false);
        expect(body).not.toHaveProperty('copy');
    });

    it('does not toast success when the request fails', async () => {
        const toast = (await import('react-hot-toast')).default;
        apiPost.mockRejectedValue(new Error('boom'));
        const actions = await renderCard();

        await actions.onCopyAsset();

        await waitFor(() => expect(toast.error).toHaveBeenCalled());
        expect(toast.success).not.toHaveBeenCalled();
    });
});
