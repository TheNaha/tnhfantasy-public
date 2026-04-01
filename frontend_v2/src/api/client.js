/**
 * API Client
 * Centralized HTTP client for all backend requests.
 */

import { getApiUrl } from './config';

// In development, use relative URLs so Vite's proxy handles CORS
// In production, use the configured API URL
const getBaseUrl = () => {
    // Check if we're in development mode (Vite sets this)
    if (import.meta.env.DEV) {
        return ''; // Use relative URLs - Vite proxy will handle
    }
    return getApiUrl();
};

class ApiError extends Error {
    constructor(message, status, data) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.data = data;
    }
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
    const url = `${getBaseUrl()}${endpoint}`;

    const { idempotencyKey, ...requestOptions } = options;

    const config = {
        headers: {
            'Content-Type': 'application/json',
            ...requestOptions.headers,
        },
        ...requestOptions,
    };

    if (idempotencyKey) {
        config.headers['Idempotency-Key'] = idempotencyKey;
    }

    // Don't set Content-Type for FormData
    if (options.body instanceof FormData) {
        delete config.headers['Content-Type'];
    }

    try {
        const response = await fetch(url, config);

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
                data.error || data.detail || 'Request failed',
                response.status,
                data
            );
        }

        return data;
    } catch (error) {
        if (error instanceof ApiError) throw error;
        throw new ApiError(error.message, 0);
    }
}

// HTTP method helpers
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
