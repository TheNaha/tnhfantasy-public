import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useCharacters = () => {
    return useQuery({
        queryKey: ['world_vault', 'characters'],
        queryFn: () => api.get('/api/v2/characters')
    });
};

export const useCreateCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (characterData) => api.post('/api/v2/characters', characterData),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
        }
    });
};

export const useUpdateCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/characters/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', variables.id] });
        }
    });
};

export const usePatchCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.patch(`/api/v2/characters/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', variables.id] });
        }
    });
};

export const getAvatarUrl = (characterId) =>
    characterId ? `/api/v2/characters/${characterId}/avatar` : null;

export const useUploadAvatar = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ characterId, file }) => {
            const formData = new FormData();
            formData.append('file', file);
            return api.post(`/api/v2/characters/${characterId}/avatar`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
        },
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', variables.characterId] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
        }
    });
};

export const useReorderCharacters = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (characterIds) => api.post('/api/v2/characters/reorder', { character_ids: characterIds }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
        }
    });
};

export const useDeleteCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v2/characters/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
        }
    });
};

export const useImportCharacterCard = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (formData) => api.post('/api/v2/characters/import', formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
        }
    });
};

export const useCloneCharacter = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.post(`/api/v2/characters/${id}/clone`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
        }
    });
};

export const useCharacterCollection = (characterId) => {
    return useQuery({
        queryKey: ['world_vault', 'characters', characterId, 'collection'],
        queryFn: () => api.get(`/api/v2/collections/by-character/${characterId}`),
        enabled: !!characterId
    });
};

export const useAnimateCharacterAvatar = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ characterId, prompt, checkpoint }) => {
            const response = await api.post(`/api/v2/characters/${characterId}/avatar/animate`, {
                prompt,
                checkpoint
            });
            return response.data;
        },
        onSuccess: (data, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', variables.characterId] });
        }
    });
};
