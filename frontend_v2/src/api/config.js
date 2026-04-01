/**
 * API Configuration
 * Centralized configuration for backend endpoints.
 */

export const DEFAULT_API_URL = 'http://localhost:8002';

function canUseBrowserStorage() {
    return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

// Get backend URL from environment or localStorage
function getBackendUrl() {
    // Check localStorage first (for runtime switching)
    if (canUseBrowserStorage()) {
        const stored = window.localStorage.getItem('comfy_backend_url');
        if (stored) return stored;
    }

    // Check environment variable
    if (import.meta.env.VITE_API_URL) {
        return import.meta.env.VITE_API_URL;
    }

    return DEFAULT_API_URL;
}

// Current backend URL (reactive)
let _backendUrl = getBackendUrl();

export function getApiUrl() {
    return _backendUrl;
}

export function setApiUrl(url) {
    _backendUrl = url;
    if (canUseBrowserStorage()) {
        window.localStorage.setItem('comfy_backend_url', url);
    }
}
