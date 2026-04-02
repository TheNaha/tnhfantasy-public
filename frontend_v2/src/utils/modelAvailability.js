export const ONLINE_RUNTIME_STATES = new Set(['running', 'starting', 'active', 'connected']);
export const AVAILABLE_MODEL_STATES = new Set(['ready', 'installed', 'available', 'completed']);

export function normalizeModelStatus(statusData) {
    if (typeof statusData === 'string') {
        return statusData.toLowerCase();
    }

    if (statusData && typeof statusData === 'object' && typeof statusData.status === 'string') {
        return statusData.status.toLowerCase();
    }

    return 'unknown';
}

export function isProviderOnline(provider) {
    if (!provider || provider.enabled === false) {
        return false;
    }

    const runtimeStatus = typeof provider.runtime_state?.status === 'string'
        ? provider.runtime_state.status.toLowerCase()
        : '';

    return ONLINE_RUNTIME_STATES.has(runtimeStatus);
}

export function formatAvailabilityBadgeLabel(label) {
    if (label === 'Loading providers') {
        return 'Loading';
    }
    if (label === 'No providers online') {
        return 'Offline';
    }
    return label;
}

export function availabilityTone(label) {
    if (label === 'Available') {
        return 'text-green-300 bg-green-500/15 border-green-500/30';
    }
    if (label === 'Partial') {
        return 'text-yellow-300 bg-yellow-500/15 border-yellow-500/30';
    }
    if (label === 'Unavailable') {
        return 'text-red-300 bg-red-500/15 border-red-500/30';
    }
    if (label === 'Loading providers') {
        return 'text-blue-300 bg-blue-500/15 border-blue-500/30';
    }
    return 'text-gray-300 bg-gray-500/15 border-gray-500/30';
}

export function getModelAvailabilitySummary(providerStatusesInput, runtimeProviders = [], { providersLoading = false } = {}) {
    const providerStatuses = providerStatusesInput && typeof providerStatusesInput === 'object'
        ? providerStatusesInput
        : {};

    const runtimeList = Array.isArray(runtimeProviders) ? runtimeProviders : [];
    const statusEntries = Object.entries(providerStatuses);
    const statusProviderIds = new Set(statusEntries.map(([providerId]) => providerId));
    const onlineProviderIds = new Set(
        runtimeList
            .filter((provider) => isProviderOnline(provider))
            .map((provider) => provider.id)
    );

    const readyByProviderId = new Map(
        statusEntries.map(([providerId, statusData]) => (
            [providerId, AVAILABLE_MODEL_STATES.has(normalizeModelStatus(statusData))]
        ))
    );

    let label = 'Unknown';
    let detail = '';
    let availableCount = 0;
    let scopeCount = 0;

    if (providersLoading && runtimeList.length > 0) {
        label = 'Loading providers';
    } else if (runtimeList.length > 0) {
        scopeCount = onlineProviderIds.size;
        availableCount = Array.from(onlineProviderIds).filter((providerId) => readyByProviderId.get(providerId)).length;

        if (scopeCount > 0) {
            if (availableCount === scopeCount) {
                label = 'Available';
            } else if (availableCount > 0) {
                label = 'Partial';
            } else {
                label = 'Unavailable';
            }
            detail = `${availableCount}/${scopeCount} online providers ready`;
        } else if (statusProviderIds.size > 0) {
            label = 'No providers online';
        }
    } else if (statusProviderIds.size > 0) {
        scopeCount = statusProviderIds.size;
        availableCount = Array.from(statusProviderIds).filter((providerId) => readyByProviderId.get(providerId)).length;

        if (availableCount === scopeCount) {
            label = 'Available';
        } else if (availableCount > 0) {
            label = 'Partial';
        } else {
            label = 'Unavailable';
        }

        detail = `${availableCount}/${scopeCount} providers ready`;
    }

    return {
        label,
        detail,
        availableCount,
        scopeCount,
        hasStatusData: statusProviderIds.size > 0,
        hasRuntimeData: runtimeList.length > 0,
    };
}