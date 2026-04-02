import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { providersApi } from '../api';
import * as ws from '../api/websocket';

export const PROVIDER_QUERY_KEYS = {
    providers: ['providers'],
    containerStatuses: ['providerContainerStatuses'],
    loadBalancer: ['providerLoadBalancer'],
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

    useEffect(() => {
        if (!realtime) {
            return undefined;
        }

        let unsubContainerStatus;
        let unsubStats;

        const init = async () => {
            try {
                await ws.connect();
                await ws.subscribe('provider');

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
            if (unsubStats) {
                unsubStats();
            }
            ws.unsubscribe('provider');
        };
    }, [queryClient, realtime]);

    const refreshAll = async () => {
        await Promise.all([
            providersQuery.refetch(),
            containerStatusesQuery.refetch(),
            loadBalancerQuery.refetch(),
        ]);
    };

    return {
        providers: providersQuery.data || [],
        containerStatuses: containerStatusesQuery.data || {},
        lbConfig: loadBalancerQuery.data?.config || null,
        lbStats: loadBalancerQuery.data?.stats || null,
        isLoading: providersQuery.isLoading || containerStatusesQuery.isLoading || loadBalancerQuery.isLoading,
        refreshAll,
        queryKeys: PROVIDER_QUERY_KEYS,
    };
}

export default useProviderServerData;
