import { create } from 'zustand';
import { providersApi } from '../api';

/**
 * Provider Store
 * Action-only Zustand store for provider mutations and local loading state.
 * Server state (provider lists, container statuses, load-balancer data) lives
 * in React Query via useProviderServerData.
 */
export const useProviderStore = create((set, get) => ({
    containerLoading: {},

    setContainerLoading: (providerId, status) => {
        set((state) => ({
            containerLoading: { ...state.containerLoading, [providerId]: status },
        }));
    },

    clearContainerLoading: (providerId) => {
        set((state) => ({
            containerLoading: { ...state.containerLoading, [providerId]: null },
        }));
    },

    startContainer: async (providerId) => {
        get().setContainerLoading(providerId, 'starting');
        try {
            return await providersApi.startContainer(providerId);
        } finally {
            get().clearContainerLoading(providerId);
        }
    },

    stopContainer: async (providerId) => {
        get().setContainerLoading(providerId, 'stopping');
        try {
            return await providersApi.stopContainer(providerId);
        } finally {
            get().clearContainerLoading(providerId);
        }
    },

    restartContainer: async (providerId) => {
        get().setContainerLoading(providerId, 'restarting');
        try {
            return await providersApi.restartContainer(providerId);
        } finally {
            get().clearContainerLoading(providerId);
        }
    },

    deployProvider: async (providerId) => {
        get().setContainerLoading(providerId, 'deploying');
        try {
            return await providersApi.deploy(providerId);
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
        return providersApi.update(providerId, { enabled: !currentlyEnabled });
    },

    deleteProvider: async (providerId) => {
        return providersApi.delete(providerId);
    },

    updateLoadBalancerStrategy: async (strategy, currentConfig = null) => {
        const config = currentConfig || (await providersApi.getLoadBalancerConfig()).config || {};
        return providersApi.updateLoadBalancerConfig({ ...config, strategy });
    },

    saveProvider: async (provider, updates) => {
        if (provider) {
            return providersApi.update(provider.id, updates);
        }
        return providersApi.create(updates);
    },
}));

export default useProviderStore;
