import { create } from 'zustand';
import * as ws from '../api/websocket';
import { providersApi } from '../api';

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
        const eventData = data.data || data;
        
        if (eventData.statuses) {
            // Batch update (all providers)
            set({ containerStatuses: eventData.statuses });
        } else if (eventData.provider_id && eventData.status) {
            // Single provider update
            set(state => ({
                containerStatuses: {
                    ...state.containerStatuses,
                    [eventData.provider_id]: {
                        ...(state.containerStatuses[eventData.provider_id] || {}),
                        status: eventData.status,
                        running: ['running', 'starting'].includes(eventData.status)
                    }
                }
            }));
        }
    },

    _processProviderStats: (data) => {
        const eventData = data.data || data;
        if (eventData.stats) {
            set({ lbStats: eventData.stats });
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
