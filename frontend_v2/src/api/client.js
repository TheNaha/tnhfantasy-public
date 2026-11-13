/**
 * API Client
 * Centralized HTTP client for all backend requests.
 */

import { getApiUrl, DEFAULT_API_URL } from './config';

const DEFAULT_TIMEOUT = 30000; // 30 seconds

// Use relative URLs when no explicit API URL is configured.
// In production, nginx proxies /api/ to the backend.
// In development, Vite's proxy handles CORS.
// Only use an absolute URL when the user explicitly sets VITE_API_URL or localStorage.
// Exported so the XHR-based uploader (which cannot use fetch) resolves the same base.
export const getBaseUrl = () => {
    const apiUrl = getApiUrl();
    if (apiUrl && apiUrl !== DEFAULT_API_URL) {
        return apiUrl;
    }
    return '';
};

class ApiError extends Error {
    constructor(message, status, data) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.data = data;
    }
}

function extractErrorMessage(payload) {
    if (!payload) {
        return null;
    }

    if (typeof payload === 'string') {
        const trimmed = payload.trim();
        return trimmed || null;
    }

    if (Array.isArray(payload)) {
        for (const entry of payload) {
            const message = extractErrorMessage(entry);
            if (message) {
                return message;
            }
        }
        return null;
    }

    if (typeof payload === 'object') {
        const directKeys = ['message', 'error', 'detail', 'reason', 'description'];
        for (const key of directKeys) {
            const message = extractErrorMessage(payload[key]);
            if (message) {
                return payload.code ? `${message} (${payload.code})` : message;
            }
        }
    }

    return null;
}

export function createIdempotencyKey(scope = 'request') {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return `${scope}-${crypto.randomUUID()}`;
    }
    return `${scope}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Base fetch wrapper with error handling
 */
async function request(endpoint, options = {}) {
    let url = `${getBaseUrl()}${endpoint}`;

    const { idempotencyKey, timeout, signal: userSignal, params, ...requestOptions } = options;

    // Merge `params` into the query string. `params` is a data property, not a
    // fetch option — it must never be spread into the request config.
    if (params) {
        const query = params instanceof URLSearchParams ? params : new URLSearchParams();
        if (!(params instanceof URLSearchParams)) {
            for (const [key, value] of Object.entries(params)) {
                if (value === undefined || value === null) continue;
                query.append(key, Array.isArray(value) ? value.join(',') : value);
            }
        }
        const queryString = query.toString();
        if (queryString) {
            url += (url.includes('?') ? '&' : '?') + queryString;
        }
    }

    const config = {
        ...requestOptions,
        headers: {
            'Content-Type': 'application/json',
            ...requestOptions.headers,
        },
    };

    if (idempotencyKey) {
        config.headers['Idempotency-Key'] = idempotencyKey;
    }

    // Don't set Content-Type for FormData
    if (options.body instanceof FormData) {
        delete config.headers['Content-Type'];
    }

    /*
     * One controller for both reasons to stop.
     *
     * A caller-supplied signal used to *replace* the timeout guard rather than
     * join it, so a request that had one had no timeout at all — and that was
     * free until every `queryFn` started forwarding React Query's signal, at
     * which point the 30s guard would have quietly disappeared from the entire
     * app. Both now abort the same controller.
     *
     * `timedOut` is what tells the two apart afterwards. Without it, an abort
     * raised because a keystroke superseded the previous one was reported as
     * `ApiError(message, 0)` — status 0 is the network-failure shape — so
     * react-query could not recognise it as a cancellation: it counted as a
     * failed query, showed up in `isError`, and re-ran the queryFn.
     */
    const timeoutMs = typeof timeout === 'number' ? timeout : DEFAULT_TIMEOUT;
    let abortTimeout;
    let timedOut = false;
    let controller = null;

    const onUserAbort = () => controller?.abort();

    if (userSignal || timeoutMs > 0) {
        controller = new AbortController();
        config.signal = controller.signal;
        if (userSignal) {
            if (userSignal.aborted) {
                timedOut = false;
                controller.abort();
            } else {
                userSignal.addEventListener('abort', onUserAbort, { once: true });
            }
        }
        if (timeoutMs > 0) {
            abortTimeout = setTimeout(() => {
                timedOut = true;
                controller?.abort();
            }, timeoutMs);
        }
    }

    const detachUserSignal = () => {
        if (userSignal) userSignal.removeEventListener('abort', onUserAbort);
    };

    try {
        const response = await fetch(url, config);
        clearTimeout(abortTimeout);
        detachUserSignal();

        // Handle non-JSON responses (like file downloads)
        const contentType = response.headers?.get?.('content-type');
        if (contentType && !contentType.includes('application/json')) {
            if (!response.ok) {
                throw new ApiError('Request failed', response.status);
            }
            if (options.responseType === 'blob') {
                return await response.blob();
            }
            return response;
        }

        const data = await response.json();

        if (!response.ok) {
            throw new ApiError(
                extractErrorMessage(data) || 'Request failed',
                response.status,
                data
            );
        }

        return data;
    } catch (error) {
        clearTimeout(abortTimeout);
        detachUserSignal();
        if (error instanceof ApiError) throw error;
        if (error?.name === 'AbortError') {
            if (timedOut) throw new ApiError('Request timed out', 408);
            // A cancellation, not a failure. Re-thrown with the name react-query
            // looks for (`error instanceof Error && error.name === 'AbortError'`)
            // so it cancels the query silently instead of landing in `isError`
            // and re-triggering the fetcher.
            throw toAbortError(error);
        }
        throw new ApiError(error.message, 0);
    }
}

/**
 * Normalise a platform abort into an `Error` whose `name` is `AbortError`.
 *
 * `fetch` rejects with a `DOMException`, which react-query's `isCancelledError`
 * does accept — but only because `DOMException` inherits from `Error` in every
 * engine it runs in today. Re-naming our own error makes the guarantee explicit
 * rather than incidental, and preserves the original as `cause`.
 */
function toAbortError(cause) {
    if (cause instanceof Error) return cause;
    const error = new Error('The operation was aborted.');
    error.name = 'AbortError';
    error.cause = cause;
    return error;
}

// HTTP method helpers

/**
 * Base path prefix for all V2 (World Vault, providers, models) endpoints.
 * Centralizing this here lets us change the version prefix in one place.
 */
export const API_V2_BASE = '/api/v2';

/**
 * Base path prefix for legacy (pre-V2) endpoints.
 * Generation, jobs, files, nodes, statistics remain on the unversioned /api/ prefix.
 */
export const API_BASE = '/api';

export const api = {
    get: (endpoint, options) => request(endpoint, { method: 'GET', ...options }),

    post: (endpoint, body, options) => request(endpoint, {
        method: 'POST',
        body: body instanceof FormData ? body : JSON.stringify(body),
        ...options,
    }),

    put: (endpoint, body, options) => request(endpoint, {
        method: 'PUT',
        body: JSON.stringify(body),
        ...options,
    }),

    patch: (endpoint, body, options) => request(endpoint, {
        method: 'PATCH',
        body: JSON.stringify(body),
        ...options,
    }),

    delete: (endpoint, options) => request(endpoint, { method: 'DELETE', ...options }),
};

export { ApiError };
export default api;
