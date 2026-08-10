/**
 * Centralized URL builders for ComfyUI output + thumbnail endpoints.
 *
 * Single source of truth for the `/api/view/output` and `/api/thumbnail` path
 * shapes so they are not copy-pasted (and inconsistently encoded) across the
 * dashboard, gallery, chat, and story components.
 *
 * The backend routes (`/api/view/{path:path}` and `/api/thumbnail/{size}/{filename:path}`)
 * URL-decode path params, so `encodeURIComponent` is safe and correctly handles
 * filenames containing spaces or other reserved characters.
 */

const OUTPUT_PREFIX = "/api/view/output";
const THUMBNAIL_PREFIX = "/api/thumbnail";

/** Full-resolution output asset URL. */
export function assetUrl(filename) {
  return `${OUTPUT_PREFIX}/${encodeURIComponent(filename)}`;
}

/** Metadata (.json) URL for an output asset. */
export function assetMetadataUrl(filename) {
  return `${OUTPUT_PREFIX}/${encodeURIComponent(filename)}.json`;
}

/**
 * Thumbnail URL for an output asset.
 * @param {string} filename
 * @param {{size?: string}} [opts]  thumbnail size, e.g. "medium" (default)
 */
export function thumbUrl(filename, { size = "medium" } = {}) {
  return `${THUMBNAIL_PREFIX}/${size}/${encodeURIComponent(filename)}`;
}

export default { assetUrl, assetMetadataUrl, thumbUrl };
