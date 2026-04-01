import { create } from 'zustand';
import * as ws from '../api/websocket';
import { providersApi } from '../api';

function unwrapEventData(data) {
    return data?.data ?? data ?? {};
}

function normalizeObject(value) {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function extractProviderId(data) {
    const eventData = unwrapEventData(data);
    return eventData.provider_id ?? eventData.providerId ?? eventData.id ?? null;
}

/**
 * Provider Store
 * Centralized WebSocket-based provider status tracking.
 * Tracks container statuses, provider list, and load balancer state globally.
 */
export const useProviderStore = create((set, get) => ({
    // Provider data
    providers: [],
    containerStatuses: {},  // { providerId: { status, running, healthy } }
    lbConfig: null,
    lbStats: null,
    
    // Connection state
    isConnected: false,
    _wsInitialized: false,
    _unsubscribers: [],
    
    // Loading states
    isLoading: false,
    containerLoading: {},  // { providerId: 'starting' | 'stopping' | etc }

    // Process WebSocket events
    _processContainerStatus: (data) => {
        const eventData = unwrapEventData(data);
        
        if (eventData.statuses) {
            // Batch update (all providers)
            set({ containerStatuses: eventData.statuses });
        } else if (extractProviderId(eventData) && eventData.status) {
            // Single provider update
            const providerId = extractProviderId(eventData);
            set(state => ({
                containerStatuses: {
                    ...state.containerStatuses,
                    [providerId]: {
                        ...(state.containerStatuses[providerId] || {}),
                        status: eventData.status,
                        running: eventData.running ?? ['running', 'starting'].includes(eventData.status),
                        healthy: eventData.healthy ?? state.containerStatuses[providerId]?.healthy
                    }
                }
            }));
        }
    },

    _processProviderStats: (data) => {
        const eventData = unwrapEventData(data);
        const stats = normalizeObject(eventData.stats ?? eventData.provider_stats ?? eventData.lb_stats ?? eventData);
        if (Object.keys(stats).length > 0) {
            set({ lbStats: stats });
        }
    },

    // Initialize WebSocket connection (call at app startup)
    connect: async () => {
        const { _wsInitialized } = get();
        if (_wsInitialized) return;

        try {
            await ws.connect();
            await ws.subscribe('provider');

            // Subscribe to provider events
            const unsubContainerStatus = ws.on(
                ws.EventTypes.PROVIDER_CONTAINER_STATUS,
                get()._processContainerStatus
            );
            const unsubStats = ws.on(
                ws.EventTypes.PROVIDER_STATS_UPDATE,
                get()._processProviderStats
            );

            set({
                _wsInitialized: true,
                _unsubscribers: [unsubContainerStatus, unsubStats]
            });

            // Initial fetch
            get().fetchProviders();
            get().fetchContainerStatuses();
            get().fetchLoadBalancerInfo();

            console.log('[ProviderStore] WebSocket connected');
        } catch (error) {
            console.error('[ProviderStore] WebSocket connection failed:', error);
        }
    },

    disconnect: () => {
        const { _unsubscribers } = get();
        _unsubscribers.forEach(unsub => unsub && unsub());
        ws.unsubscribe('provider');
        set({ _wsInitialized: false, _unsubscribers: [] });
    },

    // API methods
    fetchProviders: async () => {
        set({ isLoading: true });
        try {
            const data = await providersApi.list();
            set({ providers: data || [], isLoading: false });
            return data;
        } catch (error) {
            console.error('[ProviderStore] Failed to fetch providers:', error);
            set({ isLoading: false });
            throw error;
        }
    },

    fetchContainerStatuses: async () => {
        try {
            const data = await providersApi.getAllContainerStatuses();
            set({ containerStatuses: data.statuses || {} });
        } catch (error) {
            console.error('[ProviderStore] Failed to fetch container statuses:', error);
        }
    },

    fetchLoadBalancerInfo: async () => {
        try {
            const data = await providersApi.getLoadBalancerConfig();
            set({ lbConfig: data.config, lbStats: data.stats });
            return data;
        } catch (error) {
            console.error('[ProviderStore] Failed to fetch load balancer info:', error);
            throw error;
        }
    },

    refreshAll: async () => {
        const [providers, containerStatuses, loadBalancer] = await Promise.all([
            get().fetchProviders(),
            get().fetchContainerStatuses(),
            get().fetchLoadBalancerInfo(),
        ]);

        return { providers, containerStatuses, loadBalancer };
    },

    // Container actions with loading state
    setContainerLoading: (providerId, status) => {
        set(state => ({
            containerLoading: { ...state.containerLoading, [providerId]: status }
        }));
    },

    clearContainerLoading: (providerId) => {
        set(state => ({
            containerLoading: { ...state.containerLoading, [providerId]: null }
        }));
    },

    startContainer: async (providerId) => {
        get().setContainerLoading(providerId, 'starting');
        try {
            const result = await providersApi.startContainer(providerId);
            await get().fetchContainerStatuses();
            return result;
        } finally {
            get().clearContainerLoading(providerId);
        }
    },

    stopContainer: async (providerId) => {
        get().setContainerLoading(providerId, 'stopping');
        try {
            const result = await providersApi.stopContainer(providerId);
            await get().fetchContainerStatuses();
            return result;
        } finally {
            get().clearContainerLoading(providerId);
        }
    },

    restartContainer: async (providerId) => {
        get().setContainerLoading(providerId, 'restarting');
        try {
            const result = await providersApi.restartContainer(providerId);
            await get().fetchContainerStatuses();
            return result;
        } finally {
            get().clearContainerLoading(providerId);
        }
    },

    deployProvider: async (providerId) => {
        get().setContainerLoading(providerId, 'deploying');
        try {
            const result = await providersApi.deploy(providerId);
            await get().fetchContainerStatuses();
            return result;
        } finally {
            get().clearContainerLoading(providerId);
        }
    },

    reconcileProvider: async (providerId) => {
        get().setContainerLoading(providerId, 'reconciling');
        try {
            return await providersApi.reconcile(providerId);
        } finally {
            get().clearContainerLoading(providerId);
        }
    },

    setupProvider: async (providerId) => {
        get().setContainerLoading(providerId, 'setting up');
        try {
            return await providersApi.setup(providerId);
        } finally {
            get().clearContainerLoading(providerId);
        }
    },

    resetProviderModelStatus: async (providerId) => {
        get().setContainerLoading(providerId, 'resetting');
        try {
            return await providersApi.resetModelStatus(providerId);
        } finally {
            get().clearContainerLoading(providerId);
        }
    },

    toggleProviderEnabled: async (providerId, currentlyEnabled) => {
        const result = await providersApi.update(providerId, { enabled: !currentlyEnabled });
        await Promise.all([get().fetchProviders(), get().fetchLoadBalancerInfo()]);
        return result;
    },

    deleteProvider: async (providerId) => {
        const result = await providersApi.delete(providerId);
        await Promise.all([get().fetchProviders(), get().fetchLoadBalancerInfo(), get().fetchContainerStatuses()]);
        return result;
    },

    updateLoadBalancerStrategy: async (strategy) => {
        const { lbConfig } = get();
        const result = await providersApi.updateLoadBalancerConfig({ ...lbConfig, strategy });
        await get().fetchLoadBalancerInfo();
        return result;
    },

    saveProvider: async (provider, updates) => {
        const result = provider
            ? await providersApi.update(provider.id, updates)
            : await providersApi.create(updates);
        await Promise.all([get().fetchProviders(), get().fetchLoadBalancerInfo(), get().fetchContainerStatuses()]);
        return result;
    },

    // Enriched providers getter
    getEnrichedProviders: () => {
        const { providers, containerStatuses } = get();
        return providers.map(provider => ({
            ...provider,
            container_status: containerStatuses[provider.id]?.status || 'stopped',
            enabled: provider.enabled !== undefined ? provider.enabled : true
        }));
    },

    // Get active provider count
    getActiveCount: () => {
        const { containerStatuses } = get();
        return Object.values(containerStatuses).filter(s => s.running).length;
    }
}));

export default useProviderStore;
