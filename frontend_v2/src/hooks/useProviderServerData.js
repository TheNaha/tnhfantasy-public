import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { providersApi } from '../api';
import * as ws from '../api/websocket';

export const PROVIDER_QUERY_KEYS = {
    providers: ['providers'],
    containerStatuses: ['providerContainerStatuses'],
    loadBalancer: ['providerLoadBalancer'],
    statusCards: ['providerStatusCards'],
};

export function unwrapEventData(data) {
    return data?.data ?? data ?? {};
}

export function normalizeObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

export function extractProviderId(data) {
    const eventData = unwrapEventData(data);
    return eventData.provider_id ?? eventData.providerId ?? eventData.id ?? null;
}

export function normalizeProvidersPayload(payload) {
    if (Array.isArray(payload)) {
        return payload;
    }

    if (Array.isArray(payload?.providers)) {
        return payload.providers;
    }

    return [];
}

export function mergeContainerStatus(currentStatuses, eventData) {
    const payload = unwrapEventData(eventData);
    const current = normalizeObject(currentStatuses);

    if (payload.statuses && typeof payload.statuses === 'object') {
        return payload.statuses;
    }

    const providerId = extractProviderId(payload);
    if (!providerId || !payload.status) {
        return current;
    }

    return {
        ...current,
        [providerId]: {
            ...(current[providerId] || {}),
            status: payload.status,
            running: payload.running ?? ['running', 'starting'].includes(payload.status),
            healthy: payload.healthy ?? current[providerId]?.healthy,
        },
    };
}

export function mergeProviderStats(currentData, eventData) {
    const rawPayload = unwrapEventData(eventData);
    const statsPayload = normalizeObject(rawPayload.stats ?? rawPayload.provider_stats ?? rawPayload.lb_stats ?? rawPayload);
    if (Object.keys(statsPayload).length === 0) {
        return currentData;
    }

    const current = normalizeObject(currentData);
    return {
        ...current,
        stats: {
            ...(normalizeObject(current.stats)),
            ...statsPayload,
        },
    };
}

export function normalizeReconciliationStatus(status) {
    if (['started', 'progress', 'running'].includes(status)) {
        return 'reconciling';
    }
    return status || 'idle';
}

export function mergeStatusCardReconciliation(currentCards, eventData) {
    const payload = unwrapEventData(eventData);
    const providerId = extractProviderId(payload);
    const current = normalizeObject(currentCards);

    if (!providerId) {
        return current;
    }

    const card = normalizeObject(current[providerId]);
    const previousReconciliation = normalizeObject(card.reconciliation);
    const nextStatus = normalizeReconciliationStatus(payload.status ?? previousReconciliation.status);

    const nextReconciliation = {
        ...previousReconciliation,
        provider_id: providerId,
        status: nextStatus,
        phase: payload.phase ?? previousReconciliation.phase ?? (
            nextStatus === 'completed'
                ? 'completed'
                : nextStatus === 'failed'
                    ? 'failed'
                    : null
        ),
        message: payload.message ?? previousReconciliation.message ?? '',
        stats: Object.keys(normalizeObject(payload.stats)).length > 0
            ? normalizeObject(payload.stats)
            : normalizeObject(previousReconciliation.stats),
        current_download: payload.current_download ?? previousReconciliation.current_download ?? null,
        active_downloads: Array.isArray(payload.active_downloads)
            ? payload.active_downloads
            : Array.isArray(previousReconciliation.active_downloads)
                ? previousReconciliation.active_downloads
                : [],
        errors: Array.isArray(payload.errors)
            ? payload.errors
            : Array.isArray(previousReconciliation.errors)
                ? previousReconciliation.errors
                : [],
    };

    return {
        ...current,
        [providerId]: {
            ...card,
            provider_id: providerId,
            reconciliation: nextReconciliation,
        },
    };
}

export function mergeStatusCardStorage(currentCards, eventData) {
    const payload = unwrapEventData(eventData);
    const providerId = extractProviderId(payload);
    const current = normalizeObject(currentCards);

    if (!providerId) {
        return current;
    }

    const storagePayload = normalizeObject(payload.storage ?? payload.modal_stats ?? payload.stats);
    const rawDirectory = normalizeObject(storagePayload.by_directory ?? storagePayload.byDirectory);
    const hasStoragePatch = storagePayload.total !== undefined
        || storagePayload.total_models !== undefined
        || storagePayload.total_models_in_storage !== undefined
        || storagePayload.total_models_in_modal !== undefined
        || Object.keys(rawDirectory).length > 0
        || storagePayload.error !== undefined;

    if (!hasStoragePatch) {
        return current;
    }

    const card = normalizeObject(current[providerId]);
    const previousStorage = normalizeObject(card.storage);
    const previousDirectory = normalizeObject(previousStorage.by_directory);
    const nextStorage = {
        ...previousStorage,
        provider_id: providerId,
        total: Number(
            storagePayload.total
            ?? storagePayload.total_models
            ?? storagePayload.total_models_in_storage
            ?? storagePayload.total_models_in_modal
            ?? previousStorage.total
            ?? 0
        ),
        by_directory: {
            ...previousDirectory,
            ...rawDirectory,
        },
    };

    if (storagePayload.error !== undefined) {
        nextStorage.error = storagePayload.error;
    }

    return {
        ...current,
        [providerId]: {
            ...card,
            provider_id: providerId,
            storage: nextStorage,
        },
    };
}

export function useProviderServerData(options = {}) {
    const { realtime = true } = options;
    const queryClient = useQueryClient();

    const providersQuery = useQuery({
        queryKey: PROVIDER_QUERY_KEYS.providers,
        queryFn: async () => {
            const data = await providersApi.list();
            return normalizeProvidersPayload(data);
        },
        staleTime: 30 * 1000,
        refetchOnWindowFocus: true,
    });

    const containerStatusesQuery = useQuery({
        queryKey: PROVIDER_QUERY_KEYS.containerStatuses,
        queryFn: async () => {
            const data = await providersApi.getAllContainerStatuses();
            return data.statuses || {};
        },
        staleTime: 15 * 1000,
        refetchOnWindowFocus: true,
    });

    const loadBalancerQuery = useQuery({
        queryKey: PROVIDER_QUERY_KEYS.loadBalancer,
        queryFn: async () => providersApi.getLoadBalancerConfig(),
        staleTime: 30 * 1000,
        refetchOnWindowFocus: true,
    });

    const statusCardsQuery = useQuery({
        queryKey: PROVIDER_QUERY_KEYS.statusCards,
        queryFn: async () => {
            const data = await providersApi.getStatusCards();
            return data.status_cards || {};
        },
        staleTime: 15 * 1000,
        refetchOnWindowFocus: true,
    });

    useEffect(() => {
        if (!realtime) {
            return undefined;
        }

        let unsubContainerStatus;
        let unsubProviderStatus;
        let unsubStats;
        let unsubReconciliationStarted;
        let unsubReconciliationProgress;
        let unsubReconciliationCompleted;
        let unsubModelStatus;
        let statusCardsRefreshTimeout = null;

        const scheduleStatusCardsRefresh = () => {
            if (statusCardsRefreshTimeout) {
                return;
            }

            statusCardsRefreshTimeout = setTimeout(() => {
                statusCardsRefreshTimeout = null;
                queryClient.invalidateQueries({ queryKey: PROVIDER_QUERY_KEYS.statusCards });
            }, 1000);
        };

        const init = async () => {
            try {
                await ws.connect();
                await ws.subscribe(['provider', 'reconciliation', 'model']);

                unsubProviderStatus = ws.on(ws.EventTypes.PROVIDER_STATUS, () => {
                    queryClient.invalidateQueries({ queryKey: PROVIDER_QUERY_KEYS.providers });
                    scheduleStatusCardsRefresh();
                });

                unsubContainerStatus = ws.on(ws.EventTypes.PROVIDER_CONTAINER_STATUS, (event) => {
                    const eventData = unwrapEventData(event);
                    queryClient.setQueryData(PROVIDER_QUERY_KEYS.containerStatuses, (current) => (
                        mergeContainerStatus(current, eventData)
                    ));
                });

                unsubStats = ws.on(ws.EventTypes.PROVIDER_STATS_UPDATE, (event) => {
                    const eventData = unwrapEventData(event);
                    queryClient.setQueryData(PROVIDER_QUERY_KEYS.loadBalancer, (current) => (
                        mergeProviderStats(current, eventData)
                    ));
                    queryClient.setQueryData(PROVIDER_QUERY_KEYS.statusCards, (current) => (
                        mergeStatusCardStorage(current, eventData)
                    ));
                });

                unsubReconciliationStarted = ws.on(ws.EventTypes.RECONCILIATION_STARTED, (event) => {
                    queryClient.setQueryData(PROVIDER_QUERY_KEYS.statusCards, (current) => (
                        mergeStatusCardReconciliation(current, event)
                    ));
                });

                unsubReconciliationProgress = ws.on(ws.EventTypes.RECONCILIATION_PROGRESS, (event) => {
                    queryClient.setQueryData(PROVIDER_QUERY_KEYS.statusCards, (current) => (
                        mergeStatusCardReconciliation(current, event)
                    ));
                });

                unsubReconciliationCompleted = ws.on(ws.EventTypes.RECONCILIATION_COMPLETED, (event) => {
                    queryClient.setQueryData(PROVIDER_QUERY_KEYS.statusCards, (current) => (
                        mergeStatusCardReconciliation(current, event)
                    ));
                    scheduleStatusCardsRefresh();
                });

                unsubModelStatus = ws.on(ws.EventTypes.MODEL_STATUS_UPDATE, (event) => {
                    const payload = unwrapEventData(event);
                    const status = payload.status;
                    if (status === 'ready' || status === 'failed') {
                        scheduleStatusCardsRefresh();
                    }
                });
            } catch (error) {
                console.error('[useProviderServerData] WebSocket subscription failed:', error);
            }
        };

        init();

        return () => {
            if (unsubContainerStatus) {
                unsubContainerStatus();
            }
            if (unsubProviderStatus) {
                unsubProviderStatus();
            }
            if (unsubStats) {
                unsubStats();
            }
            if (unsubReconciliationStarted) {
                unsubReconciliationStarted();
            }
            if (unsubReconciliationProgress) {
                unsubReconciliationProgress();
            }
            if (unsubReconciliationCompleted) {
                unsubReconciliationCompleted();
            }
            if (unsubModelStatus) {
                unsubModelStatus();
            }
            if (statusCardsRefreshTimeout) {
                clearTimeout(statusCardsRefreshTimeout);
            }
            ws.unsubscribe(['provider', 'reconciliation', 'model']);
        };
    }, [queryClient, realtime]);

    const refreshAll = async () => {
        await Promise.all([
            providersQuery.refetch(),
            containerStatusesQuery.refetch(),
            loadBalancerQuery.refetch(),
            statusCardsQuery.refetch(),
        ]);
    };

    return {
        providers: providersQuery.data || [],
        containerStatuses: containerStatusesQuery.data || {},
        providerStatusCards: statusCardsQuery.data || {},
        lbConfig: loadBalancerQuery.data?.config || null,
        lbStats: loadBalancerQuery.data?.stats || null,
        isLoading: providersQuery.isLoading || containerStatusesQuery.isLoading || loadBalancerQuery.isLoading || statusCardsQuery.isLoading,
        refreshAll,
        queryKeys: PROVIDER_QUERY_KEYS,
    };
}

export default useProviderServerData;
