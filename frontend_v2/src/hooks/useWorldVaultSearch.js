import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

/**
 * Backend bound, mirrored here: `search_entities` declares
 * `q: str = Query(..., min_length=2)` in
 * backend_v2/api/routes/world_vault/world_hub.py. That argument is a bare
 * FastAPI Query default, not an exported constant, so there is nothing to
 * import. A one-character query is a guaranteed 422, not a zero-result
 * search, so the hook stays disabled until the minimum is met.
 */
export const WORLD_VAULT_SEARCH_MIN_LENGTH = 2;

/**
 * The exact set of deep-link parameter names a story @mention can carry.
 * `StoryEditor` writes `/world-vault?${item._type}=${item.id}` where `_type`
 * comes from `MentionPicker` (character, lorebook), and `StorySandbox`
 * re-parses character|lorebook|location. Nothing else writes these params.
 */
export const WORLD_VAULT_MENTION_TYPES = ['character', 'lorebook', 'location'];

const ENTITY_PATHS = {
    character: '/api/v2/characters',
    lorebook: '/api/v2/lorebooks',
    location: '/api/v2/locations',
};

/**
 * Unified search across all World Vault entities.
 * Returns characters, chats, stories, lorebooks, locations, scenarios, voices,
 * and memories that match the query string.
 */
export const useWorldVaultSearch = (query, type = null) => {
    const q = (query ?? '').trim();
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.SEARCH, q, type),
        queryFn: () => {
            const params = new URLSearchParams({ q });
            if (type) params.set('type', type);
            return api.get(`/api/v2/world-vault/search?${params.toString()}`);
        },
        enabled: q.length >= WORLD_VAULT_SEARCH_MIN_LENGTH,
        staleTime: 30000,
    });
};

/**
 * Fetch one vault entity by id. Search matches on name/description, so a
 * mention's id cannot be resolved through `useWorldVaultSearch`; this is what
 * turns `/world-vault?character=<id>` into a real, clickable result.
 */
export const useWorldVaultEntity = (type, id) => {
    const base = ENTITY_PATHS[type];
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.ENTITY, type, id),
        queryFn: () => api.get(`${base}/${id}`),
        enabled: !!base && !!id,
        staleTime: 60000,
        // A deleted or cross-instance id is a dead link, not a transient
        // failure worth retrying.
        retry: false,
    });
};

/**
 * Get entity counts and recent activity for the World Vault Hub.
 */
export const useWorldVaultDashboard = () => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.DASHBOARD),
        queryFn: () => api.get('/api/v2/world-vault/entities'),
        staleTime: 60000,
    });
};

/**
 * Get entity relationship graph for the World Vault Hub.
 */
export const useWorldVaultRelationships = () => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.RELATIONSHIPS),
        queryFn: () => api.get('/api/v2/world-vault/relationships'),
        staleTime: 60000,
    });
};

export const useGraphLayout = (name = 'default') => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.GRAPH_LAYOUT, name),
        queryFn: () => api.get(`/api/v2/world-vault/graph-layout?name=${encodeURIComponent(name)}`),
        enabled: !!name,
        staleTime: 30000,
    });
};

export const useSaveGraphLayout = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ name = 'default', nodes }) =>
            api.put(`/api/v2/world-vault/graph-layout?name=${encodeURIComponent(name)}`, { nodes }),
        onSuccess: (_, { name = 'default' }) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.GRAPH_LAYOUT, name) });
        },
    });
};
