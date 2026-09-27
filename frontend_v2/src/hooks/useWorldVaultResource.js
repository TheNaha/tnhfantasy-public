import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

/**
 * `onDone` is the caller's extra work after the invalidation this helper
 * already does; it is not the mutation's own `onSuccess` (which is the
 * `onSuccess:` key below). Same name, two different things.
 */
export function useCreateResource({ basePath, listQueryKey, onDone }) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post(basePath, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: listQueryKey });
            onDone?.(queryClient);
        }
    });
}

export function useDeleteResource({ basePath, listQueryKey, onDone }) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`${basePath}/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: listQueryKey });
            onDone?.(queryClient);
        }
    });
}

export function useUpdateResource({ basePath, listQueryKey, detailQueryKey, onDone }) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`${basePath}/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: listQueryKey });
            queryClient.invalidateQueries({ queryKey: detailQueryKey(variables.id) });
            onDone?.(queryClient, variables);
        }
    });
}
