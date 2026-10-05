import { useCallback, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { providersApi } from '../api';
import * as ws from '../api/websocket';
import toast from 'react-hot-toast';
import { QUERY_KEYS } from '../constants/queryKeys';
import { extractProviderId, unwrapPayload as unwrapEventData } from '../utils/providerUtils';
import { mergeProviderSyncStatus, normalizeProviderSyncStatus } from './useProviderModels';

export const PROVIDERS_PAGE_QUERY_KEYS = {
    providers: ['providers-page', 'providers'],
    loadBalancer: ['providers-page', 'load-balancer'],
};

const PROVIDERS_STALE_TIME = 15 * 1000;

/**
 * The "no providers yet" value, allocated once.
 *
 * A literal `|| []` inside the returned object is a fresh array per render, and
 * eight call sites destructure `providers` out of this hook — one of them feeds
 * it into a `useMemo` dependency, so a fresh empty array means that memo
 * recomputes on every render for the whole time the request is outstanding. See
 * `useFavorites.js`, which does the same thing with the same two moves.
 */
const EMPTY_PROVIDERS = [];

const PROVIDER_REALTIME_TOPICS = ['provider', 'reconciliation', 'model'];
const providersRealtimeByClient = new WeakMap();

/**
 * `signal` is forwarded so an unmounted providers panel does not leave its
 * request running; this fetcher is shared by two queries, so it takes the whole
 * context rather than a bare signal.
 */
async function fetchProvidersList({ signal } = {}) {
    return normalizeProvidersPayload(await providersApi.list({ signal }));
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
        reconciliation_state: mergeProviderSyncStatus(provider.reconciliation_state || {}, payload),
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
        unsubs.push(ws.on(ws.EventTypes.RECONCILIATION_FAILED, () => {
            // A worker failure has no progress payload to patch in, so
            // `patchReconciliation` would be a no-op. Refetch instead: the card
            // must not keep reading "reconciling" while the database already
            // holds the failed status. The sibling `provider.deploy_failed` was
            // already handled, so this was an oversight rather than a policy.
            // There is no separate `reconciliation` query — the state rides on
            // the providers list (`reconciliation_state` per provider), so
            // invalidating `providers` is the whole refetch.
            queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers });
            toast.error('Provider reconciliation failed. Check the provider logs.');
        }));

        unsubs.push(ws.on(ws.EventTypes.MODEL_STATUS_UPDATE, (event) => {
            const payload = unwrapEventData(event);
            const providerId = extractProviderId(payload);
            const hasExpectedSchema = Boolean(providerId && payload.status);
            const isBatchUpdate = payload.status === 'batch_updated';

            let providersPatched = false;
            queryClient.setQueryData(
                PROVIDERS_PAGE_QUERY_KEYS.providers,
                (current) => {
                    const merged = mergeModelStatusState(current, event);
                    providersPatched = merged.patched;
                    return merged.providers;
                },
            );

            if (isBatchUpdate) {
                // `['installed-models']` matched no query — the installed-model
                // list is `modelListKey(...)` = `['models', 'list', …]`. A batch
                // status update changed it, and nothing refetched it.
                queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.MODELS] });
                queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers });
            }

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

        // The refcount can drop to zero *while* the awaits above are in flight.
        // The unmounting consumer's cleanup runs `realtimeState.cleanup?.()`,
        // which is still null at that point, so nothing is unsubscribed — and by
        // the time this line runs the listeners are installed with zero
        // consumers and `cleanup` is set with nobody left to call it. The state
        // is a WeakMap keyed by queryClient, so the leak outlives every
        // navigation for the life of the tab.
        if (realtimeState.consumers === 0) {
            realtimeState.cleanup();
        }
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
        queryFn: ({ signal }) => providersApi.getLoadBalancing({ signal }),
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

    /*
     * Memoised, because eight call sites destructure this.
     *
     * `providersQuery.data || []` allocated a NEW empty array on every render
     * while the query was in flight, inside an object literal that was itself
     * rebuilt on every render. `useGeneratorCore` feeds the array straight into
     * a `useMemo` dependency, so that memo — which filters the provider list for
     * the generator's provider picker — recomputed on every single render for
     * as long as the providers request was outstanding, which on a cold start is
     * seconds of every frame. `useFavorites.js` solves the same problem with the
     * same two moves: one module-level constant for the empty case, and a
     * `useMemo` so the returned object is stable between real changes.
     *
     * `refreshAll` is a `useCallback` rather than an inline async function so it
     * can be a dependency here without rebuilding the object it closes over.
     */
    const refetchProviders = providersQuery.refetch;
    const refetchLoadBalancer = loadBalancerQuery.refetch;
    const stableRefreshAll = useCallback(async () => {
        await Promise.all([refetchProviders(), refetchLoadBalancer()]);
    }, [refetchProviders, refetchLoadBalancer]);

    return useMemo(() => ({
        providers: providersQuery.data || EMPTY_PROVIDERS,
        lbConfig: loadBalancerQuery.data?.config || null,
        lbStats: loadBalancerQuery.data?.stats || null,
        isLoading: providersQuery.isLoading || loadBalancerQuery.isLoading,
        refreshAll: stableRefreshAll,
    }), [
        providersQuery.data,
        loadBalancerQuery.data,
        providersQuery.isLoading,
        loadBalancerQuery.isLoading,
        stableRefreshAll,
    ]);
}

export function useProviderReconciliationState(providerId, { realtime = true } = {}) {
    const queryClient = useQueryClient();

    const providersQuery = useQuery({
        queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers,
        queryFn: fetchProvidersList,
        staleTime: PROVIDERS_STALE_TIME,
        enabled: Boolean(providerId),
        select: (providers) => {
            const provider = providers.find((entry) => entry.id === providerId);
            if (!provider) {
                return null;
            }
            return normalizeProviderSyncStatus(provider.reconciliation_state || {});
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
            // `['installed-models']` here matched no query, so after any provider
            // action (deploy, wake, sync, delete) the installed-model list stayed
            // stale. The list's real key is `modelListKey(...)` under `['models']`.
            queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.MODELS] }),
            // `objectInfo`, keyed `['objectInfo', providerId]`. Repo-wide before
            // this there were 5 references to `objectInfo` and ZERO
            // `invalidateQueries` matching it, so `/advanced`'s node palette was
            // never refreshed by anything — not by a deploy, not by a reconcile,
            // not by a wake. A provider that just gained a custom-node pack, or
            // finished booting from cold, left the palette describing the
            // provider as it was hours or days ago. Now that `useObjectInfo`
            // refetches on mount, an invalidation here is what makes that
            // refetch happen at the moment the provider's capabilities changed
            // rather than on the user's next visit.
            queryClient.invalidateQueries({ queryKey: ['objectInfo'] }),
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
        async quickSyncProvider(providerId) {
            return mutate.mutateAsync({
                providerId,
                action: 'quick syncing',
                callback: () => providersApi.quickSync(providerId),
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
