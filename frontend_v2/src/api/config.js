/**
 * API Configuration
 * Centralized configuration for backend endpoints.
 */

// Backend options
export const BACKENDS = {
    V1: 'http://localhost:8000',
    V2: 'http://localhost:8002',
};

// Get backend URL from environment or localStorage
function getBackendUrl() {
    // Check localStorage first (for runtime switching)
    const stored = localStorage.getItem('comfy_backend_url');
    if (stored) return stored;

    // Check environment variable
    if (import.meta.env.VITE_API_URL) {
        return import.meta.env.VITE_API_URL;
    }

    // Default to V2 for frontend_v2
    return BACKENDS.V2;
}

// Current backend URL (reactive)
let _backendUrl = getBackendUrl();

export function getApiUrl() {
    return _backendUrl;
}

export function setApiUrl(url) {
    _backendUrl = url;
    localStorage.setItem('comfy_backend_url', url);
}

export function useBackendV2() {
    setApiUrl(BACKENDS.V2);
}

export function useBackendV1() {
    setApiUrl(BACKENDS.V1);
}
