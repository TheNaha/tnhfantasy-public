import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useLorebooks = () => {
    return useQuery({
        queryKey: ['world_vault', 'lorebooks'],
        queryFn: () => api.get('/api/v2/lorebooks')
    });
};

export const useCreateLorebook = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post('/api/v2/lorebooks', data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'lorebooks'] });
        }
    });
};

export const useUpdateLorebook = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/lorebooks/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'lorebooks'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'lorebooks', variables.id] });
        }
    });
};

export const useDeleteLorebook = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v2/lorebooks/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'lorebooks'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
        }
    });
};
