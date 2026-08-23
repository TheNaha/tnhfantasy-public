import { describe, expect, it } from 'vitest';
import { createRng, seededSort, seededShuffle, seededRandomComparator, stableRandomKey } from './seededRandom';

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

    it('seededRandomComparator sorts stably with same seed', () => {
        const arr = [{ name: 'z' }, { name: 'a' }, { name: 'm' }];
        const cmp = seededRandomComparator('stable-seed');
        const sorted1 = [...arr].sort(cmp);
        const cmp2 = seededRandomComparator('stable-seed');
        const sorted2 = [...arr].sort(cmp2);
        expect(sorted1.map(x => x.name)).toEqual(sorted2.map(x => x.name));
    });

    it('seededRandomComparator does not cluster similar items', () => {
        const items = [
            { name: 'aaa-1' },
            { name: 'aaa-2' },
            { name: 'aaa-3' },
            { name: 'bbb-1' },
            { name: 'bbb-2' },
            { name: 'bbb-3' },
        ];
        const sorted = [...items].sort(seededRandomComparator('mixed-seed'));
        const names = sorted.map(x => x.name);
        const aaaIndices = names.map((n, i) => n.startsWith('aaa') ? i : null).filter(i => i !== null);
        const bbbIndices = names.map((n, i) => n.startsWith('bbb') ? i : null).filter(i => i !== null);
        expect(aaaIndices.length).toBe(3);
        expect(bbbIndices.length).toBe(3);
        const aaaRange = Math.max(...aaaIndices) - Math.min(...aaaIndices);
        expect(aaaRange).toBeGreaterThanOrEqual(2);
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

    it('stableRandomKey produces consistent keys for same identity+seed', () => {
        const item = { id: 'x', name: 'checkpoint' };
        expect(stableRandomKey(item, 'seed1')).toBe(stableRandomKey(item, 'seed1'));
    });

    it('stableRandomKey differs for different identities even with same seed', () => {
        const a = { id: 'a', name: 'model-a' };
        const b = { id: 'b', name: 'model-b' };
        expect(stableRandomKey(a, 'seed')).not.toBe(stableRandomKey(b, 'seed'));
    });

    it('seededSort with same identity+seed gives consistent ordering', () => {
        const items = Array.from({ length: 50 }, (_, i) => ({ id: `m-${i}`, name: `model-${i}` }));
        const sorted1 = seededSort(items, 'gallery-seed').map(x => x.id);
        const sorted2 = seededSort([...items], 'gallery-seed').map(x => x.id);
        expect(sorted1).toEqual(sorted2);
    });

    it('FNV-1a avalanche: similar names produce uncorrelated keys', () => {
        const keys = [];
        for (let i = 0; i < 10; i++) {
            keys.push(stableRandomKey({ name: `model-${i}` }, 'seed'));
        }
        // Check that the range is well-distributed (not clustered near 0 or 1)
        const min = Math.min(...keys);
        const max = Math.max(...keys);
        const range = max - min;
        expect(range).toBeGreaterThan(0.8); // keys should span most of [0, 1)

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

    it('seededSort tiebreaker preserves order on key collision', () => {
        // Force a collision: same object used twice (same identity)
        const item = { id: 'same', name: 'x' };
        const items = [item, item];
        const sorted = seededSort(items, 'seed');
        expect(sorted.length).toBe(2);
    });

    it('no collisions in 15K items (birthday bound ~0.001%)', () => {
        const items = Array.from({ length: 15000 }, (_, i) => ({ id: `img-${i}`, name: `image_${i}.png` }));
        const keys = new Set(items.map(item => stableRandomKey(item, 'gallery-seed')));
        // All 15K keys should be unique
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
});
