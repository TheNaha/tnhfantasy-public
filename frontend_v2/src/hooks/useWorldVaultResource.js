import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export function useCreateResource({ basePath, listQueryKey, onSuccess }) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post(basePath, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: listQueryKey });
            onSuccess?.(queryClient);
        }
    });
}

export function useDeleteResource({ basePath, listQueryKey, onSuccess }) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`${basePath}/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: listQueryKey });
            onSuccess?.(queryClient);
        }
    });
}

export function useUpdateResource({ basePath, listQueryKey, detailQueryKey, onSuccess }) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`${basePath}/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: listQueryKey });
            queryClient.invalidateQueries({ queryKey: detailQueryKey(variables.id) });
            onSuccess?.(queryClient, variables);
        }
    });
}
