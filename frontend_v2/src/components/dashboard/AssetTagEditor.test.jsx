/**
 * The Tags filter dimension, and the producer that was missing for it.
 *
 * `GalleryFilterPanel` shipped a first-class `Tags` facet with a typeahead and
 * counts, `assetsApi` had the three write/read methods, the backend had
 * `GET /api/v2/tags`, `GET|POST /api/v2/asset/{id}/tags`,
 * `DELETE …/tags/{tag}` and `POST /api/v2/assets/auto-tag` — and
 * `useAssetTags` had **zero importers**. Nothing could create a tag, so a user
 * could filter by a tag that nothing in the product could ever produce.
 *
 * These tests render the real `ImageLightbox` with the real `AssetTagEditor` and
 * the real hooks against a mocked HTTP client. The mock is the HTTP client, not
 * `useAssetTags`: a test that mocked the hook would have stayed green through
 * exactly this gap, which is what the 2026-09-29 and 2026-09-29b audits both
 * found in other places.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ImageLightbox from './ImageLightbox';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
}));

const filesApiMock = vi.hoisted(() => ({
    assetTags: vi.fn(),
    addAssetTag: vi.fn(),
    removeAssetTag: vi.fn(),
    tagVocabulary: vi.fn(),
    metadata: vi.fn(),
}));

vi.mock('../../api', async (importOriginal) => {
    const actual = await importOriginal();
    // `assetsApi` is a separate export from the same module and is what
    // `useAssetTags` calls; overriding only `filesApi` (the files namespace) left
    // the tag calls going to the real HTTP client.
    return { ...actual, api: apiMock, filesApi: filesApiMock, assetsApi: filesApiMock };
});

const ASSET_ID = 'asset-77';

const IMAGE = {
    id: ASSET_ID,
    filename: 'emberfall.png',
    metadata: {},
    created_at: '2026-01-01T00:00:00Z',
};

const TAGS = {
    asset_id: ASSET_ID,
    tags: [
        { tag: 'emberfall', source: 'user', confidence: null },
        { tag: 'night_lighting', source: 'user', confidence: null },
        { tag: 'detail_upscale', source: 'auto', confidence: 0.82 },
    ],
};

function renderLightbox(overrides = {}) {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <ImageLightbox
                image={IMAGE}
                onClose={vi.fn()}
                onNext={vi.fn()}
                onPrev={vi.fn()}
                onDelete={vi.fn()}
                onReuseParameters={vi.fn()}
                {...overrides}
            />
        </QueryClientProvider>,
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    filesApiMock.assetTags.mockResolvedValue(TAGS);
    filesApiMock.addAssetTag.mockResolvedValue({ status: 'success', asset_id: ASSET_ID, tag: 'x', source: 'user', created: true });
    filesApiMock.removeAssetTag.mockResolvedValue({ status: 'success', asset_id: ASSET_ID, tag: 'x', source: 'user' });
    filesApiMock.tagVocabulary.mockResolvedValue({
        tags: [
            { tag: 'ruins', count: 41, user_count: 12 },
            { tag: 'emberfall', count: 3, user_count: 3 },
        ],
        limit: 12,
        truncated: false,
    });
    filesApiMock.metadata.mockResolvedValue({});
    apiMock.get.mockResolvedValue({});
});

describe('asset tag editor', () => {
    it('is reachable from the gallery lightbox, keyed to the asset id', async () => {
        renderLightbox();
        const editor = await screen.findByTestId('asset-tag-editor');
        expect(editor).toBeInTheDocument();
        await waitFor(() => {
            expect(filesApiMock.assetTags).toHaveBeenCalledWith(ASSET_ID, {});
        });
    });

    it('shows the tags the backend returned, both provenances', async () => {
        renderLightbox();
        expect(await screen.findByText('emberfall')).toBeInTheDocument();
        expect(screen.getByText('night_lighting')).toBeInTheDocument();
        expect(screen.getByText('detail_upscale')).toBeInTheDocument();
    });

    it('offers removal only for user tags, and the auto tag is locked', async () => {
        renderLightbox();
        await screen.findByText('emberfall');
        expect(screen.getByRole('button', { name: 'Remove tag emberfall' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Remove tag night_lighting' })).toBeInTheDocument();
        // `source='auto'` is re-derived on the next rescan; the backend 404s a
        // delete on one, so no button is offered rather than one that lies.
        expect(screen.queryByRole('button', { name: /remove tag detail_upscale/i })).not.toBeInTheDocument();
    });

    it('writes a typed tag through POST /api/v2/asset/{id}/tags', async () => {
        renderLightbox();
        await screen.findByText('emberfall');

        fireEvent.change(screen.getByLabelText('Add a tag'), { target: { value: 'ruins' } });
        fireEvent.click(screen.getByLabelText('Save tag'));

        await waitFor(() => {
            expect(filesApiMock.addAssetTag).toHaveBeenCalledWith(ASSET_ID, 'ruins');
        });
    });

    it('suggests from the vocabulary and adds on click, skipping ones already on', async () => {
        renderLightbox();
        await screen.findByText('emberfall');

        fireEvent.focus(screen.getByLabelText('Add a tag'));
        fireEvent.change(screen.getByLabelText('Add a tag'), { target: { value: 'r' } });

        const ruins = await screen.findByRole('button', { name: /ruins/ });
        expect(filesApiMock.tagVocabulary).toHaveBeenCalledWith(
            expect.objectContaining({ prefix: 'r' }),
        );
        // `emberfall` is in the vocabulary AND already on this image, so it is
        // filtered out of the suggestions.
        expect(screen.queryByRole('button', { name: /^emberfall/ })).not.toBeInTheDocument();

        fireEvent.click(ruins);
        await waitFor(() => {
            expect(filesApiMock.addAssetTag).toHaveBeenCalledWith(ASSET_ID, 'ruins');
        });
    });

    it('removes a user tag through the DELETE route', async () => {
        renderLightbox();
        await screen.findByText('emberfall');
        fireEvent.click(screen.getByRole('button', { name: 'Remove tag emberfall' }));
        await waitFor(() => {
            expect(filesApiMock.removeAssetTag).toHaveBeenCalledWith(ASSET_ID, 'emberfall');
        });
    });

    it('does not submit an empty tag', async () => {
        renderLightbox();
        await screen.findByText('emberfall');
        fireEvent.click(screen.getByLabelText('Save tag'));
        expect(filesApiMock.addAssetTag).not.toHaveBeenCalled();
    });

    it('says so when the tags cannot be read, rather than showing an empty list', async () => {
        filesApiMock.assetTags.mockRejectedValue(new Error('down'));
        renderLightbox();
        expect(await screen.findByRole('alert')).toBeInTheDocument();
        expect(screen.queryByText('No tags yet.')).not.toBeInTheDocument();
    });

    it('renders nothing without an asset id, and does not fetch', async () => {
        renderLightbox({ image: { ...IMAGE, id: undefined } });
        expect(screen.queryByTestId('asset-tag-editor')).not.toBeInTheDocument();
        expect(filesApiMock.assetTags).not.toHaveBeenCalled();
    });
});

describe('the vocabulary query key is the one the invalidation targets', () => {
    it('registers under [gallery, tags, …] so useInvalidateAssetTags reaches it', async () => {
        const { useTagVocabulary } = await import('../../hooks/useAssetTags');
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
        const { renderHook, act } = await import('@testing-library/react');
        const { createElement } = await import('react');

        renderHook(() => useTagVocabulary({ prefix: '' }), {
            wrapper: ({ children }) => createElement(QueryClientProvider, { client: queryClient }, children),
        });
        await waitFor(() => {
            expect(queryClient.getQueryState(['gallery', 'tags', '', ''])?.status).toBe('success');
        });

        // The invalidation that existed before this query did. It is a prefix
        // match in react-query, so the empty-prefix variant a mounted editor
        // would hold is the one that has to go stale.
        await act(async () => {
            queryClient.getQueryCache().findAll({ queryKey: ['gallery', 'tags'] })
                .forEach((q) => q.invalidate());
        });
        expect(queryClient.getQueryState(['gallery', 'tags', '', ''])?.isInvalidated).toBe(true);
    });
});
