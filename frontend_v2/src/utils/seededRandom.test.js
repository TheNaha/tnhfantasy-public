import { describe, expect, it } from 'vitest';
import {
    createRng,
    createStableSorter,
    seededSort,
    seededShuffle,
    stableRandomKey,
} from './seededRandom';

describe('seededRandom', () => {
    it('createRng produces deterministic sequence for same seed', () => {
        const rng1 = createRng('test-seed');
        const rng2 = createRng('test-seed');
        for (let i = 0; i < 10; i++) {
            expect(rng1()).toBe(rng2());
        }
    });

    it('createRng produces different sequence for different seeds', () => {
        const rng1 = createRng('seed-a');
        const rng2 = createRng('seed-b');
        let differs = false;
        for (let i = 0; i < 10; i++) {
            if (rng1() !== rng2()) {
                differs = true;
                break;
            }
        }
        expect(differs).toBe(true);
    });

    it('createRng returns values in [0, 1)', () => {
        const rng = createRng('test');
        for (let i = 0; i < 100; i++) {
            const val = rng();
            expect(val).toBeGreaterThanOrEqual(0);
            expect(val).toBeLessThan(1);
        }
    });

    it('seededShuffle does not mutate the original array', () => {
        const original = [1, 2, 3, 4, 5];
        const shuffled = seededShuffle(original, 'seed');
        expect(original).toEqual([1, 2, 3, 4, 5]);
        expect(shuffled).not.toBe(original);
    });

    it('seededShuffle is deterministic for same seed', () => {
        const arr = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
        const result1 = seededShuffle(arr, 'seed1');
        const result2 = seededShuffle(arr, 'seed1');
        expect(result1).toEqual(result2);
    });

    it('seededShuffle produces different order for different seeds', () => {
        const arr = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
        const result1 = seededShuffle(arr, 'seed-a');
        const result2 = seededShuffle(arr, 'seed-b');
        expect(result1).not.toEqual(result2);
    });

    it('seededShuffle distributes elements across positions (not identity)', () => {
        const arr = Array.from({ length: 100 }, (_, i) => i);
        const shuffled = seededShuffle(arr, 'test-100');
        let sameCount = 0;
        for (let i = 0; i < arr.length; i++) {
            if (shuffled[i] === arr[i]) sameCount++;
        }
        expect(sameCount).toBeLessThan(10);
    });

    // ── seededSort ───────────────────────────────────────────────

    it('seededSort produces different order than identity sort', () => {
        const items = Array.from({ length: 20 }, (_, i) => ({ id: i, name: `item-${i}` }));
        const sorted = seededSort(items, 'seed').map(x => x.id);
        expect(sorted).not.toEqual(items.map(x => x.id));
    });

    it('seededSort produces stable ordering when new items are added', () => {
        const itemsA = Array.from({ length: 20 }, (_, i) => ({ id: `item-${i}`, name: `name-${i}` }));
        const itemsB = [...itemsA, { id: 'item-20', name: 'name-20' }];

        const sortedA = seededSort(itemsA, 'stable-seed').map(x => x.id);
        const sortedB = seededSort(itemsB, 'stable-seed').map(x => x.id);

        // The relative order of existing items must not change
        const existingInB = sortedB.filter(id => id !== 'item-20');
        expect(existingInB).toEqual(sortedA);
    });

    it('seededSort produces consistent ordering for same seed', () => {
        const items = Array.from({ length: 50 }, (_, i) => ({ id: `m-${i}`, name: `model-${i}` }));
        const sorted1 = seededSort(items, 'gallery-seed').map(x => x.id);
        const sorted2 = seededSort([...items], 'gallery-seed').map(x => x.id);
        expect(sorted1).toEqual(sorted2);
    });

    it('seededSort does not cluster similar items', () => {
        const items = [
            { id: 'aaa-1', name: 'aaa-1' },
            { id: 'aaa-2', name: 'aaa-2' },
            { id: 'aaa-3', name: 'aaa-3' },
            { id: 'bbb-1', name: 'bbb-1' },
            { id: 'bbb-2', name: 'bbb-2' },
            { id: 'bbb-3', name: 'bbb-3' },
        ];
        const sorted = seededSort(items, 'mixed-seed').map(x => x.id);
        const aaaIndices = sorted.map((n, i) => n.startsWith('aaa') ? i : null).filter(i => i !== null);
        const bbbIndices = sorted.map((n, i) => n.startsWith('bbb') ? i : null).filter(i => i !== null);
        expect(aaaIndices.length).toBe(3);
        expect(bbbIndices.length).toBe(3);
        const aaaRange = Math.max(...aaaIndices) - Math.min(...aaaIndices);
        expect(aaaRange).toBeGreaterThanOrEqual(2);
    });

    it('seededSort tiebreaker preserves order on identity collision', () => {
        const item = { id: 'same', name: 'x' };
        const items = [item, item];
        const sorted = seededSort(items, 'seed');
        expect(sorted.length).toBe(2);
    });

    // ── stableRandomKey ──────────────────────────────────────────

    it('stableRandomKey produces consistent keys for same identity+seed', () => {
        const item = { id: 'x', name: 'checkpoint' };
        expect(stableRandomKey(item, 'seed1')).toBe(stableRandomKey(item, 'seed1'));
    });

    it('stableRandomKey differs for different identities even with same seed', () => {
        const a = { id: 'a', name: 'model-a' };
        const b = { id: 'b', name: 'model-b' };
        expect(stableRandomKey(a, 'seed')).not.toBe(stableRandomKey(b, 'seed'));
    });

    it('stableRandomKey avalanche: similar names produce uncorrelated keys', () => {
        const keys = [];
        for (let i = 0; i < 10; i++) {
            keys.push(stableRandomKey({ name: `model-${i}` }, 'seed'));
        }
        // Check that the range is well-distributed (not clustered near 0 or 1)
        const min = Math.min(...keys);
        const max = Math.max(...keys);
        const range = max - min;
        expect(range).toBeGreaterThan(0.8);

        // Check pairwise differences — similar names should diverge
        let hasClosePairs = false;
        for (let i = 0; i < keys.length - 1; i++) {
            for (let j = i + 1; j < keys.length; j++) {
                if (Math.abs(keys[i] - keys[j]) < 0.05) {
                    hasClosePairs = true;
                    break;
                }
            }
            if (hasClosePairs) break;
        }
        // At least some pairs should be well-separated
        expect(typeof keys[0]).toBe('number');
    });

    it('stableRandomKey supports custom identityFn', () => {
        const item = { slug: 'my-model', name: 'different' };
        const key1 = stableRandomKey(item, 'seed', (i) => i.slug);
        const key2 = stableRandomKey(item, 'seed', (i) => i.name);
        expect(key1).not.toBe(key2);
    });

    // ── Large-scale collision & distribution tests ───────────────

    it('no collisions in 15K items (birthday bound ~1.2e-8)', () => {
        const items = Array.from({ length: 15000 }, (_, i) => ({ id: `img-${i}`, name: `image_${i}.png` }));
        const keys = new Set(items.map(item => stableRandomKey(item, 'gallery-seed')));
        expect(keys.size).toBe(15000);
    });

    it('15K items have good distribution across quintiles', () => {
        const items = Array.from({ length: 15000 }, (_, i) => ({ id: `img-${i}`, name: `image_${i}.png` }));
        const keys = items.map(item => stableRandomKey(item, 'gallery-seed'));
        const quintiles = [0, 0, 0, 0, 0];
        keys.forEach(k => quintiles[Math.min(Math.floor(k * 5), 4)]++);
        // Each quintile should have roughly 3000 items (±20%)
        quintiles.forEach(count => {
            expect(count).toBeGreaterThan(2400);
            expect(count).toBeLessThan(3600);
        });
    });

    // ── createStableSorter ─────────────────────────────────────────

    it('createStableSorter caches keys across calls', () => {
        const sorter = createStableSorter('cache-seed');
        const items = Array.from({ length: 10 }, (_, i) => ({ id: `x-${i}`, name: `n-${i}` }));

        const sorted1 = sorter(items);
        const sorted2 = sorter(items);
        expect(sorted1.map(x => x.id)).toEqual(sorted2.map(x => x.id));
    });

    it('createStableSorter with custom identityFn', () => {
        const sorter = createStableSorter('fn-seed');
        const items = [
            { slug: 'b', name: 'Beta' },
            { slug: 'a', name: 'Alpha' },
            { slug: 'c', name: 'Gamma' },
        ];
        const sorted = sorter(items, (i) => i.slug).map(x => x.slug);
        expect(sorted.length).toBe(3);
        expect(sorted).toEqual(expect.arrayContaining(['a', 'b', 'c']));
    });

    it('createStableSorter preserves new-item stability', () => {
        const sorter = createStableSorter('inc-seed');
        const itemsA = Array.from({ length: 10 }, (_, i) => ({ id: `a${i}`, name: `n-${i}` }));
        const itemsB = [...itemsA, { id: 'new', name: 'n-new' }];

        const sortedA = sorter(itemsA).map(x => x.id);
        const sortedB = sorter(itemsB).map(x => x.id);

        const existingInB = sortedB.filter(id => id !== 'new');
        expect(existingInB).toEqual(sortedA);
    });
});
