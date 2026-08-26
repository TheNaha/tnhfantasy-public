import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const PERSONAS_KEY = ['world_vault', 'personas'];

export const usePersonas = () => {
    return useQuery({
        queryKey: PERSONAS_KEY,
        queryFn: () => api.get('/api/v2/personas')
    });
};

export const useCreatePersona = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post('/api/v2/personas', data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: PERSONAS_KEY });
        }
    });
};

export const useUpdatePersona = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/personas/${id}`, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: PERSONAS_KEY });
        }
    });
};

export const useDeletePersona = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v2/personas/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: PERSONAS_KEY });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
        }
    });
};
