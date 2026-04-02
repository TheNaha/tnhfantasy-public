import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('zustand/middleware', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        persist: (fn) => fn,
    };
});

vi.mock('../api/collectionsApi', () => ({
    listCollections: vi.fn(),
    getCollection: vi.fn(),
    createCollection: vi.fn(),
    updateCollection: vi.fn(),
    deleteCollection: vi.fn(),
    addImagesToCollection: vi.fn(),
    removeImagesFromCollection: vi.fn(),
    importCollections: vi.fn(),
    exportCollections: vi.fn(),
}));

describe('useStore collections integration', () => {
    let useStore;
    let collectionsApi;

    beforeEach(async () => {
        vi.resetModules();
        const apiMod = await import('../api/collectionsApi');
        collectionsApi = apiMod;
        const storeMod = await import('./useStore.js');
        useStore = storeMod.default;

        useStore.setState({
            models: {},
            viewMode: 'grid',
            favorites: [],
            collections: {},
            activeCollection: null,
            collectionsLoading: false,
            collectionsInitialized: false,
            page: 0,
            hasMore: true,
        });
    });

    it('initCollections loads server collections with image counts without eagerly loading images', async () => {
        collectionsApi.listCollections.mockResolvedValue({
            collections: [{
                id: 'collection-1',
                name: 'Favorites',
                color: '#3B82F6',
                thumbnail: 'thumb.png',
                image_count: 3,
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-02T00:00:00Z',
            }],
        });

        await useStore.getState().initCollections();

        const state = useStore.getState();
        expect(state.collectionsInitialized).toBe(true);
        expect(state.collections['collection-1']).toMatchObject({
            id: 'collection-1',
            name: 'Favorites',
            imageCount: 3,
            images: [],
            thumbnail: 'thumb.png',
        });
    });

    it('loadCollectionImages hydrates images while preserving canonical count fields', async () => {
        useStore.setState({
            collections: {
                'collection-1': {
                    id: 'collection-1',
                    name: 'Favorites',
                    color: '#3B82F6',
                    thumbnail: 'thumb.png',
                    images: [],
                    imageCount: 2,
                },
            },
        });

        collectionsApi.getCollection.mockResolvedValue({
            id: 'collection-1',
            images: ['one.png', 'two.png'],
            image_count: 2,
        });

        const images = await useStore.getState().loadCollectionImages('collection-1');
        const collection = useStore.getState().collections['collection-1'];

        expect(images).toEqual(['one.png', 'two.png']);
        expect(collection.images).toEqual(['one.png', 'two.png']);
        expect(collection.imageCount).toBe(2);
    });
});
