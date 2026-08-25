import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

/**
 * Unified search across all World Vault entities.
 * Returns characters, chats, stories, lorebooks, scenarios, voices, and memories
 * that match the query string.
 */
export const useWorldVaultSearch = (query, type = null) => {
    return useQuery({
        queryKey: ['world_vault', 'search', query, type],
        queryFn: () => {
            const params = new URLSearchParams({ q: query });
            if (type) params.set('type', type);
            return api.get(`/api/v2/world-vault/search?${params.toString()}`);
        },
        enabled: !!query,
        staleTime: 30000,
    });
};

/**
 * Get entity counts and recent activity for the World Vault Hub.
 */
export const useWorldVaultDashboard = () => {
    return useQuery({
        queryKey: ['world_vault', 'dashboard'],
        queryFn: () => api.get('/api/v2/world-vault/entities'),
        staleTime: 60000,
    });
};

/**
 * Get entity relationship graph for the World Vault Hub.
 */
export const useWorldVaultRelationships = () => {
    return useQuery({
        queryKey: ['world_vault', 'relationships'],
        queryFn: () => api.get('/api/v2/world-vault/relationships'),
        staleTime: 60000,
    });
};

export const useGraphLayout = (name = 'default') => {
    return useQuery({
        queryKey: ['world_vault', 'graph-layout', name],
        queryFn: () => api.get(`/api/v2/world-vault/graph-layout?name=${encodeURIComponent(name)}`),
        staleTime: 30000,
    });
};

export const useSaveGraphLayout = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ name = 'default', nodes }) =>
            api.put(`/api/v2/world-vault/graph-layout?name=${encodeURIComponent(name)}`, { nodes }),
        onSuccess: (_, { name = 'default' }) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'graph-layout', name] });
        },
    });
};
