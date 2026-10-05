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

/** The generation prompt, or null when the asset predates metadata capture.
 *
 * `getAssetNegativePrompt`, `getAssetSeed`, `getAssetCheckpoint`,
 * `getAssetLoras` and `getAssetTimestamp` were deleted from here: zero consumers
 * production or test. The grid card reads seed, LoRAs and the checkpoint off the
 * `metadata` object inline, and the date rail orders on the server's own
 * timeline, so five accessors documented a contract nobody held to.
 */
export function getAssetPrompt(asset) {
    const meta = getAssetMetadata(asset);
    if (!meta) return null;
    return meta.prompt ?? asset.prompt ?? null;
}
