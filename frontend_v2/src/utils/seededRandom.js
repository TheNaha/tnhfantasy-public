/**
 * Seeded random utilities for stable pseudo-random ordering.
 *
 * KEY DESIGN DECISION: We use **per-item deterministic random keys** rather
 * than Fisher-Yates shuffle. Each item's key is computed from a hash of
 * `seed + itemIdentity`. This means adding a new item does NOT change the
 * relative order of existing items — the new item simply slots into whatever
 * position its own key dictates. This is critical for galleries where items
 * are added incrementally (new image generations) without a full re-shuffle.
 *
 * HASH + PRNG: FNV-1a 64-bit hashes the seed+identity string, then splitmix64
 * expands the hash into a well-distributed [0, 1) float. This two-stage
 * approach is critical: FNV-1a alone has weak avalanche for strings differing
 * in only one character (e.g. "model-0" vs "model-1" produce correlated
 * lower bits). Splitmix64 provides full avalanche — even a 1-bit change in
 * the seed produces a completely different output.
 *
 * COLLISION RESISTANCE: The key is 53 bits (JS double mantissa). Birthday-bound
 * collision probability: ~0.001% at 15K items, ~0.17% at 100K items.
 * For reference, the old 32-bit hash had ~2.6% at 15K items.
 *
 * Even if a collision somehow occurred, seededSort uses index-based
 * tiebreaking to guarantee a deterministic, stable order.
 */

const FNV64_OFFSET = 14695981039346656037n;
const FNV64_PRIME = 1099511628211n;

/**
 * FNV-1a 64-bit hash using BigInt — excellent avalanche for short strings,
 * used as the initial PRNG seed (not as the final key directly).
 */
function fnv1a64(str) {
    let h = FNV64_OFFSET;
    for (let i = 0; i < str.length; i++) {
        h = (h ^ BigInt(str.charCodeAt(i))) * FNV64_PRIME;
    }
    return h & 0xFFFFFFFFFFFFFFFFn;
}

/**
 * Splitmix64 — a high-quality PRNG with full avalanche.
 * Even a 1-bit change in the seed produces a completely different output
 * sequence. We use a single call (no internal state progression) to get
 * one well-distributed value per item.
 */
function splitmix64(seed) {
    let z = (seed + 0x9E3779B97F4A7C15n) & 0xFFFFFFFFFFFFFFFFn;
    z = ((z ^ (z >> 30n)) * 0xBF58476D1CE4E5B9n) & 0xFFFFFFFFFFFFFFFFn;
    z = ((z ^ (z >> 27n)) * 0x94D049BB133111EBn) & 0xFFFFFFFFFFFFFFFFn;
    z = z ^ (z >> 31n);
    // Return as float in [0, 1) using 53 bits of precision (JS double mantissa)
    return Number(z & ((1n << 53n) - 1n)) / Number(1n << 53n);
}

/**
 * Generate a stable random key [0, 1) for a single item.
 * The key depends only on `seedStr + itemIdentity`, so it is:
 *   - Deterministic: same seed + identity → same key
 *   - Stable: adding/removing other items does not change this key
 *   - Independent: similar items get uncorrelated keys (splitmix64 avalanche)
 */
export function stableRandomKey(item, seedStr) {
    const identity = (item && typeof item === 'object' && item !== null)
        ? (item.name || item.id || item.filename || item.title || JSON.stringify(item))
        : String(item);
    const seed = fnv1a64(seedStr + '|' + identity);
    return splitmix64(seed);
}

/**
 * Sort items by a seeded random key computed from each item's identity.
 * Returns a new array; does not mutate the input.
 *
 * Unlike Fisher-Yates shuffle, this approach is **stable**: appending a new
 * item to the list does not change the relative order of existing items.
 *
 * Collision handling: if two items produce the same hash key (effectively
 * impossible with 53-bit keys for real-world item counts), the original
 * index is used as a tiebreaker to guarantee a deterministic, stable order.
 */
export function seededSort(items, seedStr) {
    const seen = new WeakMap();
    return [...items].sort((a, b) => {
        if (!seen.has(a)) seen.set(a, stableRandomKey(a, seedStr));
        if (!seen.has(b)) seen.set(b, stableRandomKey(b, seedStr));
        const diff = seen.get(a) - seen.get(b);
        if (diff !== 0) return diff;
        return items.indexOf(a) - items.indexOf(b);
    });
}

/**
 * @deprecated Use `stableRandomKey` directly in a comparator instead.
 * This function uses sequential PRNG calls (WeakMap cache) which are
 * unstable across refetches with new object references.
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

// ── mulberry32 PRNG (used by seededShuffle and seededRandomComparator) ──

const FNV_OFFSET = 2166136261;
const FNV_PRIME = 16777619;

function stringToSeed(str) {
    let h = FNV_OFFSET;
    for (let i = 0; i < str.length; i++) {
        h = Math.imul(h ^ str.charCodeAt(i), FNV_PRIME);
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
