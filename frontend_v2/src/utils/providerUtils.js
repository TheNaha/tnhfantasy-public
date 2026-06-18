export function extractProviderId(payload) {
    if (typeof payload === 'string') return payload;
    if (payload?.provider_id) return payload.provider_id;
    if (payload?.id) return payload.id;
    return null;
}
