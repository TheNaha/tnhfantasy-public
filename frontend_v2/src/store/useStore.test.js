import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('zustand/middleware', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        persist: (fn) => fn,
    };
});

describe('useStore basic state', () => {
    let useStore;

    beforeEach(async () => {
        vi.resetModules();
        const storeMod = await import('./useStore.js');
        useStore = storeMod.default;

        useStore.setState({
            viewMode: 'grid',
            favorites: [],
            activeCollection: null,
        });
    });



    it('manages favorites', () => {
        expect(useStore.getState().favorites).toEqual([]);
        useStore.getState().toggleFavorite('image1.png');
        expect(useStore.getState().favorites).toEqual(['image1.png']);
        expect(useStore.getState().isFavorite('image1.png')).toBe(true);
        
        useStore.getState().toggleFavorite('image1.png');
        expect(useStore.getState().favorites).toEqual([]);
        expect(useStore.getState().isFavorite('image1.png')).toBe(false);
    });

    it('manages activeCollection', () => {
        expect(useStore.getState().activeCollection).toBe(null);
        useStore.getState().setActiveCollection('coll-1');
        expect(useStore.getState().activeCollection).toBe('coll-1');
    });
});
