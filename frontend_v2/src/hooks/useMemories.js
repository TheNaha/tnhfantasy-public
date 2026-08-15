import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useMemories = (characterId = null) => {
    return useQuery({
        queryKey: ['world_vault', 'memories', characterId],
        queryFn: () => {
            const url = characterId
                ? `/api/v2/memories?character_id=${characterId}`
                : '/api/v2/memories';
            return api.get(url);
        },
        enabled: characterId === null || !!characterId,
    });
};

export const useCharacterMemories = (characterId) => {
    return useQuery({
        queryKey: ['world_vault', 'characters', characterId, 'memories'],
        queryFn: () => api.get(`/api/v2/memories/character/${characterId}`),
        enabled: !!characterId,
    });
};

export const useCreateMemory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post('/api/v2/memories', data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'memories'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', variables.character_id, 'memories'] });
        }
    });
};

export const useUpdateMemory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/memories/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'memories'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'memories', variables.id] });
        }
    });
};

export const useDeleteMemory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v2/memories/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'memories'] });
        }
    });
};

export const useSearchMemories = () => {
    return useMutation({
        mutationFn: ({ characterId, query, limit = 5 }) =>
            api.get(`/api/v2/memories/search/semantic?character_id=${characterId}&query=${encodeURIComponent(query)}&limit=${limit}`),
    });
};
