import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useLorebooks = () => {
    return useQuery({
        queryKey: ['world_vault', 'lorebooks'],
        queryFn: () => api.get('/api/v2/lorebooks')
    });
};

export const useLorebook = (id) => {
    return useQuery({
        queryKey: ['world_vault', 'lorebooks', id],
        queryFn: () => api.get(`/api/v2/lorebooks/${id}`),
        enabled: !!id,
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

export const useLorebookEntries = (lorebookId) => {
    return useQuery({
        queryKey: ['world_vault', 'lorebooks', lorebookId, 'entries'],
        queryFn: () => api.get(`/api/v2/lorebooks/${lorebookId}/entries`),
        enabled: !!lorebookId,
    });
};

export const useCreateEntry = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ lorebookId, ...data }) => api.post(`/api/v2/lorebooks/${lorebookId}/entries`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'lorebooks', variables.lorebookId, 'entries'] });
        }
    });
};

export const useUpdateEntry = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ lorebookId, id, ...data }) => api.put(`/api/v2/lorebooks/${lorebookId}/entries/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'lorebooks', variables.lorebookId, 'entries'] });
        }
    });
};

export const useDeleteEntry = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ lorebookId, id }) => api.delete(`/api/v2/lorebooks/${lorebookId}/entries/${id}`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'lorebooks', variables.lorebookId, 'entries'] });
        }
    });
};

export const useSearchEntries = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ lorebookId, q, limit }) => api.get(`/api/v2/lorebooks/${lorebookId}/search`, { params: { q, limit } }),
        onSuccess: (data, variables) => {
            queryClient.setQueryData(['world_vault', 'lorebooks', variables.lorebookId, 'search', variables.q], data);
        }
    });
};

export const useReindexLorebook = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (lorebookId) => api.post(`/api/v2/lorebooks/${lorebookId}/reindex`),
        onSuccess: (_, lorebookId) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'lorebooks', lorebookId, 'entries'] });
        }
    });
};
