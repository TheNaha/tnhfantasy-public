/**
 * Seeded random utilities for stable pseudo-random ordering.
 *
 * The PRNG is mulberry32 — a small, fast, well-distributed generator.
 * Seeds are derived from a user-facing "re-roll" value (stored in localStorage)
 * so that the same seed always produces the same ordering across re-renders,
 * while different seeds give genuinely different permutations.
 *
 * KEY DESIGN DECISION: We use **per-item deterministic random keys** rather
 * than Fisher-Yates shuffle. Each item's key is computed as createRng(seed +
 * itemIdentity)(). This means adding a new item does NOT change the relative
 * order of existing items — the new item simply slots into whatever position
 * its own key dictates. This is critical for galleries where items are
 * added incrementally (new image generations) without a full re-shuffle.
 */

function stringToSeed(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) {
        h = Math.imul(31, h) + str.charCodeAt(i) | 0;
    }
    return h >>> 0;
}

export function createRng(seedStr) {
    let t = stringToSeed(seedStr || String(Math.random()));
    return function () {
        t += 0x6D2B79F5;
        let r = t;
        r = Math.imul(r ^ (r >>> 15), r | 1);
        r ^= r + Math.imul(r ^ (r >>> 7), r | 0x42B7);
        return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
}

/**
 * Generate a stable random key [0, 1) for a single item.
 * The key depends only on `seedStr + itemIdentity`, so it is:
 *   - Deterministic: same seed + identity → same key
 *   - Stable: adding/removing other items does not change this key
 *   - Independent: each item gets its own value from a fresh PRNG
 */
export function stableRandomKey(item, seedStr) {
    const identity = (item && typeof item === 'object' && item !== null)
        ? (item.name || item.id || item.filename || item.title || JSON.stringify(item))
        : String(item);
    return createRng(seedStr + '|' + identity)();
}

/**
 * Sort items by a seeded random key computed from each item's identity.
 * Returns a new array; does not mutate the input.
 *
 * Unlike Fisher-Yates shuffle, this approach is **stable**: appending a new
 * item to the list does not change the relative order of existing items.
 */
export function seededSort(items, seedStr) {
    const keys = new WeakMap();
    return [...items].sort((a, b) => {
        if (!keys.has(a)) keys.set(a, stableRandomKey(a, seedStr));
        if (!keys.has(b)) keys.set(b, stableRandomKey(b, seedStr));
        return keys.get(a) - keys.get(b);
    });
}

/**
 * Fisher-Yates shuffle with a seeded PRNG.
 * Returns a new array; does not mutate the input.
 * NOTE: This reorders ALL items when the set changes. Prefer `seededSort`
 * when incremental additions should not disturb existing ordering.
 */
export function seededShuffle(array, seedStr) {
    const rng = createRng(seedStr);
    const result = [...array];
    for (let i = result.length - 1; i > 0; i--) {
        const j = Math.floor(rng() * (i + 1));
        [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
}

/**
 * Build a comparator that sorts items by a seeded random key based on
 * object identity (WeakMap cache). Useful for inline sort() calls.
 * NOTE: WeakMap cache is tied to object reference identity, so
 * refetched data with new references will get new keys. For data
 * that changes references on every refetch, use `stableRandomKey`
 * directly with a stable item identity.
 */
export function seededRandomComparator(seedStr) {
    const rng = createRng(seedStr);
    const cache = new WeakMap();
    return (a, b) => {
        if (!cache.has(a)) cache.set(a, rng());
        if (!cache.has(b)) cache.set(b, rng());
        return cache.get(a) - cache.get(b);
    };
}
