import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { providersApi } from '../api';
import * as ws from '../api/websocket';

export const PROVIDERS_PAGE_QUERY_KEYS = {
    providers: ['providers-page', 'providers'],
    loadBalancer: ['providers-page', 'load-balancer'],
};

const PROVIDER_REALTIME_TOPICS = ['provider', 'reconciliation', 'model'];

let providersRealtimeConsumers = 0;
let providersRealtimeCleanup = null;
let providersRealtimeQueryClient = null;
let providersRealtimeInitPromise = null;

function unwrapEventData(data) {
    return data?.data ?? data ?? {};
}

function extractProviderId(data) {
    const payload = unwrapEventData(data);
    return payload.provider_id ?? payload.providerId ?? payload.id ?? null;
}

function normalizeProvidersPayload(payload) {
    if (Array.isArray(payload)) {
        return payload;
    }
    if (Array.isArray(payload?.providers)) {
        return payload.providers;
    }
    return [];
}

function patchProviders(currentProviders, providerId, patcher) {
    if (!Array.isArray(currentProviders)) {
        return currentProviders;
    }
    return currentProviders.map((provider) => (
        provider.id === providerId ? patcher(provider) : provider
    ));
}

function mergeRuntimeState(currentProviders, event) {
    const payload = unwrapEventData(event);
    const providerId = extractProviderId(payload);
    if (!providerId || !payload.status) {
        return currentProviders;
    }

    return patchProviders(currentProviders, providerId, (provider) => ({
        ...provider,
        runtime_state: {
            ...(provider.runtime_state || {}),
            status: payload.status,
            running: payload.running ?? ['running', 'starting'].includes(payload.status),
            healthy: payload.healthy ?? provider.runtime_state?.healthy,
        },
    }));
}

function normalizeReconciliationStatus(status) {
    if (['started', 'queued'].includes(status)) {
        return 'queued';
    }
    if (['running', 'progress', 'reconciling'].includes(status)) {
        return 'reconciling';
    }
    return status || 'idle';
}

function mergeReconciliationState(currentProviders, event) {
    const payload = unwrapEventData(event);
    const providerId = extractProviderId(payload);
    if (!providerId) {
        return currentProviders;
    }

    return patchProviders(currentProviders, providerId, (provider) => ({
        ...provider,
        reconciliation_state: {
            ...(provider.reconciliation_state || {}),
            provider_id: providerId,
            status: normalizeReconciliationStatus(payload.status),
            phase: payload.phase ?? provider.reconciliation_state?.phase ?? null,
            message: payload.message ?? provider.reconciliation_state?.message ?? '',
            stats: payload.stats ?? provider.reconciliation_state?.stats ?? {},
            active_downloads: payload.active_downloads ?? provider.reconciliation_state?.active_downloads ?? [],
            errors: payload.errors ?? provider.reconciliation_state?.errors ?? [],
            current_download: payload.current_download ?? provider.reconciliation_state?.current_download ?? null,
            updated_at: payload.updated_at ?? provider.reconciliation_state?.updated_at ?? null,
        },
    }));
}

function mergeStorageState(currentProviders, event) {
    const payload = unwrapEventData(event);
    const providerId = extractProviderId(payload);
    if (!providerId) {
        return currentProviders;
    }

    const stats = payload.stats ?? payload.storage ?? payload.modal_stats ?? {};
    return patchProviders(currentProviders, providerId, (provider) => ({
        ...provider,
        storage: {
            ...(provider.storage || {}),
            provider_id: providerId,
            total: Number(
                stats.total
                ?? stats.total_models
                ?? stats.total_models_in_storage
                ?? provider.storage?.total
                ?? 0
            ),
            by_directory: {
                ...(provider.storage?.by_directory || {}),
                ...(stats.by_directory || stats.byDirectory || {}),
            },
            ...(stats.error !== undefined ? { error: stats.error } : {}),
        },
    }));
}

async function ensureProvidersRealtime(queryClient) {
    if (providersRealtimeCleanup && providersRealtimeQueryClient === queryClient) {
        return;
    }

    if (providersRealtimeInitPromise) {
        return providersRealtimeInitPromise;
    }

    providersRealtimeInitPromise = (async () => {
        if (providersRealtimeCleanup && providersRealtimeQueryClient !== queryClient) {
            providersRealtimeCleanup();
            providersRealtimeCleanup = null;
        }

        await ws.connect();
        await ws.subscribe(PROVIDER_REALTIME_TOPICS);

        const unsubs = [];

        unsubs.push(ws.on(ws.EventTypes.PROVIDER_STATUS, () => {
            queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers });
        }));

        unsubs.push(ws.on(ws.EventTypes.PROVIDER_CONTAINER_STATUS, (event) => {
            queryClient.setQueryData(
                PROVIDERS_PAGE_QUERY_KEYS.providers,
                (current) => mergeRuntimeState(current, event),
            );
        }));

        unsubs.push(ws.on(ws.EventTypes.PROVIDER_STATS_UPDATE, (event) => {
            queryClient.setQueryData(
                PROVIDERS_PAGE_QUERY_KEYS.providers,
                (current) => mergeStorageState(current, event),
            );
            queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.loadBalancer });
        }));

        const patchReconciliation = (event) => {
            queryClient.setQueryData(
                PROVIDERS_PAGE_QUERY_KEYS.providers,
                (current) => mergeReconciliationState(current, event),
            );
        };

        unsubs.push(ws.on(ws.EventTypes.RECONCILIATION_STARTED, patchReconciliation));
        unsubs.push(ws.on(ws.EventTypes.RECONCILIATION_PROGRESS, patchReconciliation));
        unsubs.push(ws.on(ws.EventTypes.RECONCILIATION_COMPLETED, (event) => {
            patchReconciliation(event);
            queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers });
        }));

        unsubs.push(ws.on(ws.EventTypes.MODEL_STATUS_UPDATE, (event) => {
            const payload = unwrapEventData(event);
            if (payload.status === 'ready' || payload.status === 'failed') {
                queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers });
            }
        }));

        providersRealtimeQueryClient = queryClient;
        providersRealtimeCleanup = () => {
            unsubs.forEach((unsub) => unsub?.());
            ws.unsubscribe(PROVIDER_REALTIME_TOPICS);
            providersRealtimeCleanup = null;
            providersRealtimeQueryClient = null;
        };
    })().finally(() => {
        providersRealtimeInitPromise = null;
    });

    return providersRealtimeInitPromise;
}

export function useProvidersPageData({ realtime = true } = {}) {
    const queryClient = useQueryClient();

    const providersQuery = useQuery({
        queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers,
        queryFn: async () => normalizeProvidersPayload(await providersApi.list()),
        staleTime: 15 * 1000,
        refetchOnWindowFocus: true,
    });

    const loadBalancerQuery = useQuery({
        queryKey: PROVIDERS_PAGE_QUERY_KEYS.loadBalancer,
        queryFn: () => providersApi.getLoadBalancerConfig(),
        staleTime: 30 * 1000,
        refetchOnWindowFocus: true,
    });

    useEffect(() => {
        if (!realtime) {
            return undefined;
        }
        providersRealtimeConsumers += 1;
        ensureProvidersRealtime(queryClient).catch((error) => {
            console.error('[useProvidersPageData] WebSocket subscription failed:', error);
        });

        return () => {
            providersRealtimeConsumers = Math.max(0, providersRealtimeConsumers - 1);
            if (providersRealtimeConsumers === 0) {
                providersRealtimeCleanup?.();
            }
        };
    }, [queryClient, realtime]);

    const refreshAll = async () => {
        await Promise.all([
            providersQuery.refetch(),
            loadBalancerQuery.refetch(),
        ]);
    };

    return {
        providers: providersQuery.data || [],
        lbConfig: loadBalancerQuery.data?.config || null,
        lbStats: loadBalancerQuery.data?.stats || null,
        isLoading: providersQuery.isLoading || loadBalancerQuery.isLoading,
        refreshAll,
    };
}

export function useProviderMutations() {
    const queryClient = useQueryClient();
    const [actionLoading, setActionLoading] = useState({});

    const setLoading = (providerId, action) => {
        setActionLoading((current) => ({ ...current, [providerId]: action }));
    };

    const clearLoading = (providerId) => {
        setActionLoading((current) => ({ ...current, [providerId]: null }));
    };

    const invalidateProviders = async () => {
        await Promise.all([
            queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers }),
            queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.loadBalancer }),
        ]);
    };

    const runAction = async (providerId, action, callback) => {
        setLoading(providerId, action);
        try {
            return await callback();
        } finally {
            clearLoading(providerId);
        }
    };

    const mutate = useMutation({
        mutationFn: async ({ providerId, action, callback }) => runAction(providerId, action, callback),
        onSuccess: async () => {
            await invalidateProviders();
        },
    });

    return {
        actionLoading,
        async startContainer(providerId) {
            return mutate.mutateAsync({
                providerId,
                action: 'starting',
                callback: () => providersApi.startContainer(providerId),
            });
        },
        async stopContainer(providerId) {
            return mutate.mutateAsync({
                providerId,
                action: 'stopping',
                callback: () => providersApi.stopContainer(providerId),
            });
        },
        async restartContainer(providerId) {
            return mutate.mutateAsync({
                providerId,
                action: 'restarting',
                callback: () => providersApi.restartContainer(providerId),
            });
        },
        async deployProvider(providerId) {
            return mutate.mutateAsync({
                providerId,
                action: 'deploying',
                callback: () => providersApi.deploy(providerId),
            });
        },
        async reconcileProvider(providerId) {
            return mutate.mutateAsync({
                providerId,
                action: 'reconciling',
                callback: () => providersApi.reconcile(providerId),
            });
        },
        async setupProvider(providerId) {
            return mutate.mutateAsync({
                providerId,
                action: 'setting up',
                callback: () => providersApi.setup(providerId),
            });
        },
        async resetProviderModelStatus(providerId) {
            return mutate.mutateAsync({
                providerId,
                action: 'resetting',
                callback: () => providersApi.resetModelStatus(providerId),
            });
        },
        async toggleProviderEnabled(providerId, currentlyEnabled) {
            return mutate.mutateAsync({
                providerId,
                action: 'updating',
                callback: () => providersApi.update(providerId, { enabled: !currentlyEnabled }),
            });
        },
        async deleteProvider(providerId) {
            return mutate.mutateAsync({
                providerId,
                action: 'deleting',
                callback: () => providersApi.delete(providerId),
            });
        },
        async updateLoadBalancerStrategy(strategy, currentConfig = null) {
            const config = currentConfig || (await providersApi.getLoadBalancerConfig()).config || {};
            const result = await providersApi.updateLoadBalancerConfig({ ...config, strategy });
            await invalidateProviders();
            return result;
        },
        async saveProvider(provider, updates) {
            const result = provider
                ? await providersApi.update(provider.id, updates)
                : await providersApi.create(updates);
            await invalidateProviders();
            return result;
        },
    };
}

export default useProvidersPageData;
