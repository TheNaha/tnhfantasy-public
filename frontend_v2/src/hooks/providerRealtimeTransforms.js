function normalizeObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

export function unwrapEventData(payload) {
    return payload?.data ?? payload ?? {};
}

export function extractProviderId(payload) {
    const source = unwrapEventData(payload);
    return source.provider_id ?? source.providerId ?? source.id ?? null;
}

export function normalizeReconciliationStatus(status) {
    if (['started', 'queued'].includes(status)) {
        return 'queued';
    }
    if (['running', 'progress', 'reconciling'].includes(status)) {
        return 'reconciling';
    }
    return status || 'idle';
}

export function normalizeReconciliationState(payload, fallbackState = {}) {
    const source = unwrapEventData(payload);
    const fallback = normalizeObject(fallbackState);
    const sourceStats = normalizeObject(source.stats);
    const fallbackStats = normalizeObject(fallback.stats);

    return {
        ...fallback,
        provider_id: source.provider_id ?? source.providerId ?? fallback.provider_id ?? null,
        status: normalizeReconciliationStatus(source.status ?? fallback.status),
        phase: source.phase ?? fallback.phase ?? null,
        message: source.message ?? fallback.message ?? '',
        stats: Object.keys(sourceStats).length > 0 ? sourceStats : fallbackStats,
        active_downloads: Array.isArray(source.active_downloads)
            ? source.active_downloads
            : Array.isArray(fallback.active_downloads)
                ? fallback.active_downloads
                : [],
        errors: Array.isArray(source.errors)
            ? source.errors
            : Array.isArray(fallback.errors)
                ? fallback.errors
                : [],
        current_download: source.current_download ?? fallback.current_download ?? null,
        updated_at: source.updated_at ?? fallback.updated_at ?? null,
        started_at: source.started_at ?? fallback.started_at ?? null,
        finished_at: source.finished_at ?? fallback.finished_at ?? null,
    };
}
