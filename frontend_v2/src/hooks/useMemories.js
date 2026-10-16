import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { invalidateVaultAggregates } from './useWorldVaultResource';

// List memories for a character, sorted by importance/accessed_at
export const useCharacterMemories = (characterId) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.MEMORIES, characterId),
        queryFn: ({ signal }) => api.get(`/api/v2/memories/character/${characterId}`, { signal }),
        enabled: !!characterId,
    });
};

export const useCreateMemory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post('/api/v2/memories', data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({
                queryKey: buildQueryKey(QUERY_KEYS.MEMORIES, variables.character_id),
            });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useUpdateMemory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        // `characterId` is deliberately stripped from the payload: the endpoint
        // updates by memory id, so it must never be able to re-assign a memory
        // to another character. It is kept on the variables only to target the
        // cache invalidation — which is why the panel must never hold a memory
        // id from a different character than the one it is editing.
        mutationFn: ({ id, characterId: _characterId, ...data }) => api.put(`/api/v2/memories/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({
                queryKey: buildQueryKey(QUERY_KEYS.MEMORIES, variables.characterId),
            });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useDeleteMemory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id }) => api.delete(`/api/v2/memories/${id}`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({
                queryKey: buildQueryKey(QUERY_KEYS.MEMORIES, variables.characterId),
            });
            invalidateVaultAggregates(queryClient);
        },
    });
};

export const useSearchMemories = (characterId, query) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.MEMORIES, 'search', characterId, query),
        // `query` is the debounced term (see MemoriesPanel), so a search is sent
        // once the typing settles rather than on every keystroke.
        queryFn: ({ signal }) =>
            api.get('/api/v2/memories/search/semantic', {
                params: { character_id: characterId, query, limit: 20 },
                signal,
            }),
        enabled: !!characterId && !!query && query.length >= 2,
    });
};

export const useReindexMemories = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (params = {}) => api.post('/api/v2/memories/reindex', null, { params }),
        onSuccess: () => {
            queryClient.invalidateQueries({
                queryKey: [QUERY_KEYS.MEMORIES],
            });
            invalidateVaultAggregates(queryClient);
        },
    });
};

