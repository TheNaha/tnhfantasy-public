/**
 * Upload helpers
 *
 * Client-side mirror of the backend upload budgets (see
 * backend_v2/core/upload_validation.py) so an oversized or wrong-type file
 * fails immediately with a readable message instead of after a slow round
 * trip, plus an XHR-based uploader that reports progress and can be cancelled
 * (fetch cannot report upload progress).
 */

import { ApiError, getBaseUrl } from './client';

export const MB = 1024 * 1024;

/** Mirrors MAX_CARD_SIZE_MB in backend_v2/core/upload_validation.py. */
export const CARD_MAX_BYTES = 25 * MB;

/**
 * Client-side limits. The backend remains the authority - these only avoid
 * wasting a round trip, and its error payload always wins when it disagrees.
 */
export const UPLOAD_LIMITS = {
    // /api/upload/input, /api/upload/mask
    input: { maxBytes: 50 * MB, imageOnly: true },
    // /api/upload
    file: { maxBytes: 500 * MB, imageOnly: false },
    // character avatars / location images
    avatar: { maxBytes: 20 * MB, imageOnly: true },
    // /api/v2/characters/import (PNG or JSON card)
    card: { maxBytes: CARD_MAX_BYTES, imageOnly: false },
    // /api/files/batch-download
    export: { maxFiles: 500 },
};

const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff', 'tif', 'svg', 'avif'];

export function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) return 'unknown size';
    if (bytes >= MB) return `${(bytes / MB).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${Math.round(bytes)} B`;
}

export function isImageFile(file) {
    if (file?.type?.startsWith('image/')) return true;
    const ext = String(file?.name || '').split('.').pop()?.toLowerCase();
    return Boolean(ext) && IMAGE_EXTENSIONS.includes(ext);
}

/**
 * Throw a readable ApiError before uploading when a file obviously breaks the
 * backend's rules. `kind` is a key of UPLOAD_LIMITS.
 */
export function assertUploadAllowed(file, kind = 'file') {
    const limits = UPLOAD_LIMITS[kind] || UPLOAD_LIMITS.file;

    if (!file) {
        throw new ApiError('No file selected', 0, { code: 'UPLOAD_INVALID' });
    }
    if (file.size === 0) {
        throw new ApiError('Selected file is empty', 0, { code: 'UPLOAD_INVALID', field: 'file' });
    }
    if (limits.imageOnly && !isImageFile(file)) {
        throw new ApiError('Please select an image file', 0, {
            code: 'UNSUPPORTED_FILE_TYPE',
            field: 'file',
        });
    }
    if (file.size > limits.maxBytes) {
        throw new ApiError(
            `File is too large (${formatBytes(file.size)}). Max size is ${formatBytes(limits.maxBytes)}.`,
            0,
            {
                code: 'UPLOAD_TOO_LARGE',
                field: 'file',
                max_bytes: limits.maxBytes,
                received_bytes: file.size,
            }
        );
    }
    return true;
}

function messageFromBody(body, fallback) {
    if (!body) return fallback;
    if (typeof body === 'string') return body.trim() || fallback;
    const base = body.error || body.message || body.detail;
    return body.code && base ? `${base} (${body.code})` : base || fallback;
}

/**
 * POST a FormData body with upload progress and cancellation.
 *
 * `fetch` cannot report upload progress, so this uses XMLHttpRequest. The
 * returned promise resolves with the parsed JSON body and rejects with an
 * ApiError carrying the server's message/code, matching the fetch path.
 */
export function uploadWithProgress(endpoint, formData, { onProgress, signal, timeout = 30000, headers } = {}) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        const url = `${getBaseUrl()}${endpoint}`;

        if (onProgress) {
            xhr.upload.onprogress = (event) => {
                if (!event.lengthComputable) return;
                onProgress({
                    loaded: event.loaded,
                    total: event.total,
                    ratio: event.total ? event.loaded / event.total : 0,
                });
            };
        }

        const onAbort = () => xhr.abort();
        if (signal) {
            if (signal.aborted) {
                reject(new ApiError('Upload cancelled', 0, { code: 'UPLOAD_CANCELLED' }));
                return;
            }
            signal.addEventListener('abort', onAbort, { once: true });
        }

        let timedOut = false;
        const timer = timeout > 0
            ? setTimeout(() => {
                timedOut = true;
                xhr.abort();
            }, timeout)
            : null;

        const cleanup = () => {
            if (timer) clearTimeout(timer);
            if (signal) signal.removeEventListener('abort', onAbort);
        };

        xhr.open('POST', url, true);
        // Let the browser set the multipart boundary.
        xhr.setRequestHeader('Accept', 'application/json');
        if (headers) {
            Object.entries(headers).forEach(([key, value]) => xhr.setRequestHeader(key, value));
        }

        xhr.onload = () => {
            cleanup();
            let body = null;
            try {
                body = xhr.responseText ? JSON.parse(xhr.responseText) : null;
            } catch {
                body = xhr.responseText;
            }

            if (xhr.status >= 200 && xhr.status < 300) {
                resolve(body);
                return;
            }
            reject(new ApiError(messageFromBody(body, `Upload failed (${xhr.status})`), xhr.status, body));
        };

        xhr.onerror = () => {
            cleanup();
            reject(new ApiError('Upload failed: network error', 0, null));
        };

        xhr.onabort = () => {
            cleanup();
            reject(timedOut
                ? new ApiError('Upload timed out', 408, { code: 'UPLOAD_TIMEOUT' })
                : new ApiError('Upload cancelled', 0, { code: 'UPLOAD_CANCELLED' }));
        };

        xhr.send(formData);
    });
}
