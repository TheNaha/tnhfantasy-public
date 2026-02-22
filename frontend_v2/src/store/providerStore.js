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
        } catch (error) {
            console.error('[ProviderStore] Failed to fetch load balancer info:', error);
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
