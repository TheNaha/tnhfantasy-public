import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useCallback } from 'react';
import { api } from '../api';
import * as ws from '../api/websocket';

/**
 * Hook for provider sync status with WebSocket updates
 * Replaces polling with WebSocket event subscription
 */
export function useProviderSyncStatus(providerId) {
    const queryClient = useQueryClient();

    // Set up WebSocket listener for real-time updates
    useEffect(() => {
        if (!providerId) return;

        // Subscribe to model topic for status updates
        ws.subscribe('model');

        // Listen for model status updates
        const unsubscribe = ws.on(ws.EventTypes.MODEL_STATUS_UPDATE, (event) => {
            // Only react to updates for our provider
            if (event.data?.provider_id === providerId) {
                // Invalidate the cache to trigger a refetch
                queryClient.invalidateQueries(['providerSyncStatus', providerId]);
            }
        });

        return () => {
            unsubscribe();
            ws.unsubscribe('model');
        };
    }, [providerId, queryClient]);

    return useQuery({
        queryKey: ['providerSyncStatus', providerId],
        queryFn: () => api.get(`/api/models/sync-status?provider=${providerId}`),
        enabled: !!providerId,
        // No refetchInterval - we rely on WebSocket events now
        // But keep staleTime short so invalidation refetches quickly
        staleTime: 5000,
        // Refetch on window focus as fallback
        refetchOnWindowFocus: true,
    });
}

/**
 * Hook for Modal stats with reduced polling (backend caches this)
 * WebSocket events can trigger invalidation when stats change
 */
export function useModalStats(providerId) {
    const queryClient = useQueryClient();

    // Set up WebSocket listener for provider stats
    useEffect(() => {
        if (!providerId) return;

        ws.subscribe('provider');

        const unsubscribe = ws.on(ws.EventTypes.PROVIDER_STATS_UPDATE, (event) => {
            if (event.data?.provider_id === providerId) {
                // Update cache directly with the new stats
                queryClient.setQueryData(['modalStats', providerId], event.data.stats);
            }
        });

        return () => {
            unsubscribe();
        };
    }, [providerId, queryClient]);

    return useQuery({
        queryKey: ['modalStats', providerId],
        queryFn: () => api.get(`/api/providers/${providerId}/modal-stats`),
        enabled: !!providerId,
        // Longer stale time since modal-stats is expensive
        staleTime: 60000,
        // Refresh every 60s as fallback (was 30s)
        refetchInterval: 60000,
        refetchOnWindowFocus: true,
    });
}

// Fetch models for a provider
export function useProviderModels(providerId, status = null) {
    return useQuery({
        queryKey: ['providerModels', providerId, status],
        queryFn: () => {
            let url = `/api/models?provider=${providerId}`;
            if (status) {
                url += `&status=${status}`;
            }
            return api.get(url);
        },
        enabled: !!providerId,
    });
}

// Remove model from provider
export function useRemoveModelFromProvider() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({ directory, modelName, providerId }) => {
            const encodedDirectory = directory.replace(/\//g, '%2F');
            return api.delete(`/api/models/${encodedDirectory}/${modelName}/providers/${providerId}`);
        },
        onSuccess: (_, { providerId }) => {
            queryClient.invalidateQueries(['providerModels', providerId]);
            queryClient.invalidateQueries(['providerSyncStatus', providerId]);
        },
    });
}

// Add model to providers
export function useAddModelToProviders() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: ({ directory, modelData, providerIds }) => {
            return api.post('/api/models', {
                directory,
                model_data: modelData,
                provider_ids: providerIds
            });
        },
        onSuccess: (_, { providerIds }) => {
            providerIds.forEach(providerId => {
                queryClient.invalidateQueries(['providerModels', providerId]);
                queryClient.invalidateQueries(['providerSyncStatus', providerId]);
            });
        },
    });
}
