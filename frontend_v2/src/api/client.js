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
const getBaseUrl = () => {
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
                return message;
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

    // Timeout guard: only create AbortController when no manual signal is provided
    let abortTimeout;
    if (!userSignal) {
        const timeoutMs = typeof timeout === 'number' ? timeout : DEFAULT_TIMEOUT;
        if (timeoutMs > 0) {
            const controller = new AbortController();
            abortTimeout = setTimeout(() => controller.abort(), timeoutMs);
            config.signal = controller.signal;
        }
    } else {
        config.signal = userSignal;
    }

    try {
        const response = await fetch(url, config);
        clearTimeout(abortTimeout);

        // Handle non-JSON responses (like file downloads)
        const contentType = response.headers.get('content-type');
        if (contentType && !contentType.includes('application/json')) {
            if (!response.ok) {
                throw new ApiError('Request failed', response.status);
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
        if (error instanceof ApiError) throw error;
        if (abortTimeout !== undefined && error.name === 'AbortError') {
            throw new ApiError('Request timed out', 408);
        }
        throw new ApiError(error.message, 0);
    }
}

// HTTP method helpers

/**
 * Base path prefix for all V2 (World Vault, providers, models) endpoints.
 * Centralizing this here lets us change the version prefix in one place.
 */
export const API_V2_BASE = '/api/v2';

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
