/**
 * Shared provider utility functions used across hooks and components.
 */

export function unwrapPayload(payload) {
    return payload?.data ?? payload ?? {};
}

export function normalizeObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

export function extractProviderId(payload) {
    const source = unwrapPayload(payload);
    return source.provider_id ?? source.providerId ?? source.id ?? null;
}

export function getProviderDisplayName(providerId) {
    if (!providerId) return null;
    return providerId.replace('comfy-provider-', '').replace('modal-', '');
}
