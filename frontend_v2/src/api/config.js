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
    let url = DEFAULT_API_URL;
    
    // Environment variable takes highest priority (except for SSR fallback)
    if (import.meta.env.VITE_API_URL) {
        url = import.meta.env.VITE_API_URL;
    } else if (canUseBrowserStorage()) {
        const stored = window.localStorage.getItem('comfy_backend_url');
        if (stored) url = stored;
    }

    // Fix Firefox NS_ERROR_WEBSOCKET_CONNECTION_REFUSED
    // Firefox aggressively blocks requests to 0.0.0.0. Chromium allows it.
    if (url.includes('0.0.0.0')) {
        url = url.replace('0.0.0.0', '127.0.0.1');
    }

    return url;
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
