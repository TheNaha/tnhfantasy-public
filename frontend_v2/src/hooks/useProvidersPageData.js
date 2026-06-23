import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { providersApi } from '../api';
import * as ws from '../api/websocket';
import {
    extractProviderId,
    normalizeReconciliationState,
    unwrapEventData,
} from './providerRealtimeTransforms';
import { mergeProviderSyncStatus } from './useProviderModels';

export const PROVIDERS_PAGE_QUERY_KEYS = {
    providers: ['providers-page', 'providers'],
    loadBalancer: ['providers-page', 'load-balancer'],
};

const PROVIDERS_STALE_TIME = 15 * 1000;

const PROVIDER_REALTIME_TOPICS = ['provider', 'reconciliation', 'model'];
const providersRealtimeByClient = new WeakMap();

async function fetchProvidersList() {
    return normalizeProvidersPayload(await providersApi.list());
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

function mergeReconciliationState(currentProviders, event) {
    const payload = unwrapEventData(event);
    const providerId = extractProviderId(payload);
    if (!providerId) {
        return currentProviders;
    }

    return patchProviders(currentProviders, providerId, (provider) => ({
        ...provider,
        reconciliation_state: normalizeReconciliationState(payload, provider.reconciliation_state || {}),
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

function mergeModelStatusState(currentProviders, event) {
    const payload = unwrapEventData(event);
    const providerId = extractProviderId(payload);
    if (!providerId || !payload.status) {
        return { providers: currentProviders, patched: false };
    }

    let didPatch = false;
    const providers = patchProviders(currentProviders, providerId, (provider) => {
        didPatch = true;
        return {
            ...provider,
            model_sync: mergeProviderSyncStatus(provider.model_sync || {}, payload),
        };
    });

    return { providers, patched: didPatch };
}

function getProvidersRealtimeState(queryClient) {
    let realtimeState = providersRealtimeByClient.get(queryClient);
    if (!realtimeState) {
        realtimeState = {
            consumers: 0,
            cleanup: null,
            initPromise: null,
        };
        providersRealtimeByClient.set(queryClient, realtimeState);
    }
    return realtimeState;
}

async function ensureProvidersRealtime(queryClient) {
    const realtimeState = getProvidersRealtimeState(queryClient);

    if (realtimeState.cleanup) {
        return;
    }

    if (realtimeState.initPromise) {
        return realtimeState.initPromise;
    }

    realtimeState.initPromise = (async () => {
        await ws.connect();
        await ws.subscribe(PROVIDER_REALTIME_TOPICS);

        const unsubs = [];

        unsubs.push(ws.on(ws.EventTypes.PROVIDER_STATUS, () => {
            queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers });
        }));

        unsubs.push(ws.on('connection', (state) => {
            if (state.connected) {
                queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers });
            }
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
        unsubs.push(ws.on(ws.EventTypes.RECONCILIATION_COMPLETED, patchReconciliation));

        unsubs.push(ws.on(ws.EventTypes.MODEL_STATUS_UPDATE, (event) => {
            const payload = unwrapEventData(event);
            const providerId = extractProviderId(payload);
            const hasExpectedSchema = Boolean(providerId && payload.status);

            let providersPatched = false;
            queryClient.setQueryData(
                PROVIDERS_PAGE_QUERY_KEYS.providers,
                (current) => {
                    const merged = mergeModelStatusState(current, event);
                    providersPatched = merged.patched;
                    return merged.providers;
                },
            );



            if (!hasExpectedSchema || !providersPatched) {
                queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers });
            }
        }));

        const patchDeployState = (event) => {
            const payload = unwrapEventData(event);
            const providerId = extractProviderId(payload);
            if (!providerId) return;

            queryClient.setQueryData(
                PROVIDERS_PAGE_QUERY_KEYS.providers,
                (current) => patchProviders(current, providerId, (provider) => ({
                    ...provider,
                    deploy_state: {
                        ...(provider.deploy_state || {}),
                        ...payload,
                    },
                }))
            );
        };

        unsubs.push(ws.on(ws.EventTypes.PROVIDER_DEPLOY_STARTED, patchDeployState));
        unsubs.push(ws.on(ws.EventTypes.PROVIDER_DEPLOY_PROGRESS, patchDeployState));
        unsubs.push(ws.on(ws.EventTypes.PROVIDER_DEPLOY_COMPLETED, patchDeployState));
        unsubs.push(ws.on(ws.EventTypes.PROVIDER_DEPLOY_FAILED, patchDeployState));

        realtimeState.cleanup = () => {
            unsubs.forEach((unsub) => unsub?.());
            ws.unsubscribe(PROVIDER_REALTIME_TOPICS);
            realtimeState.cleanup = null;
        };
    })().finally(() => {
        realtimeState.initPromise = null;
    });

    return realtimeState.initPromise;
}

export function useProvidersPageData({ realtime = true } = {}) {
    const queryClient = useQueryClient();

    const providersQuery = useQuery({
        queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers,
        queryFn: fetchProvidersList,
        staleTime: PROVIDERS_STALE_TIME,
        refetchOnWindowFocus: false,
    });

    const loadBalancerQuery = useQuery({
        queryKey: PROVIDERS_PAGE_QUERY_KEYS.loadBalancer,
        queryFn: () => providersApi.getLoadBalancing(),
        staleTime: 30 * 1000,
        refetchOnWindowFocus: false,
    });

    useEffect(() => {
        if (!realtime) {
            return undefined;
        }

        const realtimeState = getProvidersRealtimeState(queryClient);
        realtimeState.consumers += 1;

        ensureProvidersRealtime(queryClient).catch((error) => {
            console.error('[useProvidersPageData] WebSocket subscription failed:', error);
        });

        return () => {
            realtimeState.consumers = Math.max(0, realtimeState.consumers - 1);
            if (realtimeState.consumers === 0) {
                realtimeState.cleanup?.();
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

export function useProviderReconciliationState(providerId, { realtime = true } = {}) {
    const queryClient = useQueryClient();

    const providersQuery = useQuery({
        queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers,
        queryFn: fetchProvidersList,
        staleTime: PROVIDERS_STALE_TIME,
        refetchOnWindowFocus: true,
        enabled: Boolean(providerId),
        select: (providers) => {
            const provider = providers.find((entry) => entry.id === providerId);
            if (!provider) {
                return null;
            }
            return normalizeReconciliationState({}, provider.reconciliation_state || {});
        },
    });

    useEffect(() => {
        if (!realtime) {
            return undefined;
        }

        const realtimeState = getProvidersRealtimeState(queryClient);
        realtimeState.consumers += 1;

        ensureProvidersRealtime(queryClient).catch((error) => {
            console.error('[useProviderReconciliationState] WebSocket subscription failed:', error);
        });

        return () => {
            realtimeState.consumers = Math.max(0, realtimeState.consumers - 1);
            if (realtimeState.consumers === 0) {
                realtimeState.cleanup?.();
            }
        };
    }, [queryClient, realtime]);

    return {
        reconciliationState: providersQuery.data,
        isLoading: providersQuery.isLoading,
        isFetching: providersQuery.isFetching,
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
            const config = currentConfig || (await providersApi.getLoadBalancing()).config || {};
            const result = await providersApi.updateLoadBalancing({ ...config, strategy });
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
