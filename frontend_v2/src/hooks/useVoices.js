import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useVoices = (characterId = null) => {
    return useQuery({
        queryKey: ['world_vault', 'voices', characterId],
        queryFn: () => {
            const url = characterId ? `/api/v2/voices?character_id=${characterId}` : '/api/v2/voices';
            return api.get(url);
        },
        enabled: characterId === null || !!characterId,
    });
};



export const useCreateVoice = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post('/api/v2/voices', data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'voices'] });
        }
    });
};

export const useUpdateVoice = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/voices/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'voices'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'voices', variables.id] });
        }
    });
};

export const useDeleteVoice = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v2/voices/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'voices'] });
        }
    });
};

export const useVoicePreview = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (voiceId) => api.post(`/api/v2/voices/${voiceId}/preview`),
        onSuccess: (_, voiceId) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'voices', voiceId] });
        }
    });
};
