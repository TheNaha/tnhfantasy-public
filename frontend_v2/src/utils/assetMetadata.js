/**
 * Accessors for the generation metadata carried on a gallery asset.
 *
 * The list payload nests everything generated under `metadata` (and the ORM
 * alias `metadata_`), and nothing hoists individual fields to the top level.
 * Several call sites were reading `item.prompt` and `item.checkpoint`
 * directly, which is always undefined — the grid card's hover overlay, its
 * aria-label, and the timeline's prompt line were all silently dead.
 *
 * `toImageItem` in `utils/dashboardItems.js` is `{ ...file, type, date,
 * timelineDate }`, so the nesting is the contract. Anything reading prompt,
 * seed, LoRAs or the checkpoint off an asset should go through here rather
 * than re-deriving the fallback chain.
 */

/** The metadata object for an asset, tolerating both spellings. */
export function getAssetMetadata(asset) {
    if (!asset) return null;
    return asset.metadata ?? asset.metadata_ ?? null;
}

/** The generation prompt, or null when the asset predates metadata capture. */
export function getAssetPrompt(asset) {
    const meta = getAssetMetadata(asset);
    if (!meta) return null;
    return meta.prompt ?? asset.prompt ?? null;
}

/** The negative prompt, or null. */
export function getAssetNegativePrompt(asset) {
    const meta = getAssetMetadata(asset);
    if (!meta) return null;
    return meta.negativePrompt ?? meta.negative_prompt ?? asset.negativePrompt ?? null;
}

/** The seed, or null. `0` is a real seed, so this must not be a truthiness test. */
export function getAssetSeed(asset) {
    const meta = getAssetMetadata(asset);
    const seed = meta?.seed ?? asset?.seed;
    return typeof seed === 'number' ? seed : null;
}

/** The checkpoint as stored (an object, or a bare filename string), or null. */
export function getAssetCheckpoint(asset) {
    const meta = getAssetMetadata(asset);
    return meta?.checkpoint ?? asset?.checkpoint ?? null;
}

/** The LoRA list, each entry `{ name, display_name, strength, ... }`. */
export function getAssetLoras(asset) {
    const meta = getAssetMetadata(asset);
    return Array.isArray(meta?.loras) ? meta.loras : [];
}

/**
 * The most recent timestamp available on an asset, preferring the generation
 * time over the import time. The backend orders and groups on the same
 * coalesce, so anything date-related should use this rather than picking a
 * field by hand.
 */
export function getAssetTimestamp(asset) {
    return asset?.generated_at ?? asset?.created_at ?? null;
}
