import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

// List memories for a character, sorted by importance/accessed_at
export const useCharacterMemories = (characterId) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.MEMORIES, characterId),
        queryFn: () => api.get(`/api/v2/memories/character/${characterId}`),
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
        },
    });
};

export const useUpdateMemory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, characterId: _characterId, ...data }) => api.put(`/api/v2/memories/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({
                queryKey: buildQueryKey(QUERY_KEYS.MEMORIES, variables.characterId),
            });
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
        },
    });
};

export const useSearchMemories = (characterId, query) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.MEMORIES, 'search', characterId, query),
        queryFn: () =>
            api.get('/api/v2/memories/search/semantic', {
                params: { character_id: characterId, query, limit: 20 },
            }),
        enabled: !!characterId && !!query && query.length >= 2,
    });
};
