import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * A `blob:` URL was being persisted into localStorage.
 *
 * `partialize` stripped `sourceImage, maskImage, preflightTick,
 * preflightChecking, isMissingModelsOpen` and returned `...rest` — and
 * `ipAdapters` was in `rest`. Each adapter's `image` is a `blob:` URL produced
 * by `URL.createObjectURL(file)` in `ImageUploader.jsx` and written into
 * `ipAdapters[i].image` by `IPAdapterSection.jsx`.
 *
 * A `blob:` URL is scoped to the document that created it and is dead the
 * instant the tab reloads, but the persisted entry stays truthy. On restore,
 * `ImageUploader` saw a non-null image, rendered `<img src="blob:http://…">`,
 * and displayed a broken image over the dropzone — which was therefore
 * unreachable, leaving only the clear button as an escape.
 *
 * Asserted against what actually reaches localStorage, not against
 * `partialize` in isolation: the bug was never in what partialize computes, it
 * was in a field being omitted from it.
 *
 * NOTE: this file must NOT mock `zustand/middleware`. The real `persist` is the
 * subject — a mocked-out middleware makes every assertion here vacuous, which is
 * what the sibling `generatorStore.test.js` does for its own purposes.
 */

beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
});

const STORAGE_KEY = 'generator-storage';

async function loadStore() {
    const { useGeneratorStore } = await import('../store/generatorStore.js');
    return useGeneratorStore;
}

/**
 * What zustand's `persist` actually wrote.
 *
 * It nests under `{state, version}` — read the envelope off rather than
 * asserting against it, so these tests describe the PERSISTED STATE and not the
 * storage format, which is an implementation detail that could change without
 * any of the behaviour under test changing.
 */
function readPersisted() {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && 'state' in parsed ? parsed.state : parsed;
}

const BLOB_URL = 'blob:http://100.150.0.4:5174/2f1c-4d8a-9b31-77fe';

describe('the generator store never persists a blob: URL', () => {
    it('drops the reference image and keeps the settings', async () => {
        const store = await loadStore();

        store.getState().setAll({
            ipAdapters: [{
                image: BLOB_URL,
                model: 'ip-adapter_sd15',
                clipVision: 'CLIP-ViT-H-14',
                weight: 0.65,
                stopAt: 0.8,
            }],
        });

        const persisted = readPersisted();
        expect(persisted).not.toBeNull();

        // The blob URL is scoped to the document that made it and is dead on
        // reload, so persisting it produced a truthy-but-broken entry.
        expect(JSON.stringify(persisted)).not.toContain('blob:');
        expect(persisted.ipAdapters[0].image).toBeNull();

        // The settings are worth keeping: re-picking a reference image should
        // not also mean re-typing its weight and clip model.
        expect(persisted.ipAdapters[0]).toMatchObject({
            model: 'ip-adapter_sd15',
            clipVision: 'CLIP-ViT-H-14',
            weight: 0.65,
            stopAt: 0.8,
        });
    });

    it('keeps every other generator setting intact', async () => {
        const store = await loadStore();

        store.getState().setAll({
            ipAdapters: [{ image: BLOB_URL, model: 'm', weight: 0.5 }],
            prompt: 'a weathered lighthouse keeper',
            steps: 37,
            cfg: 6.5,
            width: 1024,
            height: 768,
        });

        const persisted = readPersisted();
        expect(persisted).toMatchObject({
            prompt: 'a weathered lighthouse keeper',
            steps: 37,
            cfg: 6.5,
            width: 1024,
            height: 768,
        });
    });

    it('handles several adapters, clearing every reference image', async () => {
        const store = await loadStore();

        store.getState().setAll({
            ipAdapters: [
                { image: BLOB_URL, model: 'a', weight: 0.1 },
                { image: null, model: 'b', weight: 0.2 },
                { image: 'blob:http://localhost:5174/deadbeef', model: 'c', weight: 0.3 },
            ],
        });

        const persisted = readPersisted();
        expect(JSON.stringify(persisted)).not.toContain('blob:');
        expect(persisted.ipAdapters.map((a) => a.image)).toEqual([null, null, null]);
        expect(persisted.ipAdapters.map((a) => a.model)).toEqual(['a', 'b', 'c']);
    });

    it('does not persist the other excluded runtime fields', async () => {
        const store = await loadStore();

        store.getState().setAll({
            sourceImage: 'data:image/png;base64,AAAA',
            maskImage: 'data:image/png;base64,BBBB',
            preflightTick: 7,
            preflightChecking: true,
            isMissingModelsOpen: true,
        });

        const persisted = readPersisted();
        expect(persisted.sourceImage).toBeUndefined();
        expect(persisted.maskImage).toBeUndefined();
        expect(persisted.preflightTick).toBeUndefined();
        expect(persisted.preflightChecking).toBeUndefined();
        expect(persisted.isMissingModelsOpen).toBeUndefined();
    });

    it('survives a store with no ipAdapters at all', async () => {
        const store = await loadStore();

        store.getState().setAll({ prompt: 'plain' });
        const persisted = readPersisted();

        expect(persisted.ipAdapters).toEqual([]);
        expect(persisted.prompt).toBe('plain');
    });
});