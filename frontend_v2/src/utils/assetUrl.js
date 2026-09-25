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

import { getApiUrl } from '../api/config';

function encodeAssetPath(filename) {
  return String(filename)
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

/** Full-resolution output asset URL. */
export function assetPath(asset) {
    if (typeof asset === 'string') return asset;
    return asset?.relative_path || asset?.path || asset?.name || '';
}

function apiPath(path) {
    const base = String(getApiUrl() || '').replace(/\/$/, '');
    return `${base}${path}`;
}

export function assetUrl(filename) {
    return apiPath(`/api/view/output/${encodeAssetPath(filename)}`);
}


/** Metadata (.json) URL for an output asset. */
export function assetMetadataUrl(filename) {
    return apiPath(`/api/view/output/${encodeAssetPath(filename)}.json`);
}


/**
 * Thumbnail URL for an output asset.
 * @param {string} filename
 * @param {{size?: string}} [opts]  thumbnail size, e.g. "medium" (default)
 */
export function thumbUrl(filename, { size = "medium" } = {}) {
    return apiPath(`/api/thumbnail/${size}/${encodeAssetPath(filename)}`);
}


export default { assetUrl, assetMetadataUrl, thumbUrl };
