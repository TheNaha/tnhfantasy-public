import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

export function createCRUDHooks({ entity, endpoint, searchEndpoint }) {
    const basePath = `/api/v2/${endpoint}`;
    const queryKey = () => buildQueryKey(entity);

    const useList = () => {
        return useQuery({
            queryKey: queryKey(),
            queryFn: () => api.get(basePath),
        });
    };

    const useItem = (id) => {
        return useQuery({
            queryKey: buildQueryKey(entity, id),
            queryFn: () => api.get(`${basePath}/${id}`),
            enabled: !!id,
        });
    };

    const useCreate = () => {
        const queryClient = useQueryClient();
        return useMutation({
            mutationFn: (data) => api.post(basePath, data),
            onSuccess: () => {
                queryClient.invalidateQueries({ queryKey: queryKey() });
            },
        });
    };

    const useUpdate = () => {
        const queryClient = useQueryClient();
        return useMutation({
            mutationFn: ({ id, ...data }) => api.put(`${basePath}/${id}`, data),
            onSuccess: (_, variables) => {
                queryClient.invalidateQueries({ queryKey: queryKey() });
                queryClient.invalidateQueries({ queryKey: buildQueryKey(entity, variables.id) });
            },
        });
    };

    const usePatch = () => {
        const queryClient = useQueryClient();
        return useMutation({
            mutationFn: ({ id, ...data }) => api.patch(`${basePath}/${id}`, data),
            onSuccess: (_, variables) => {
                queryClient.invalidateQueries({ queryKey: queryKey() });
                queryClient.invalidateQueries({ queryKey: buildQueryKey(entity, variables.id) });
            },
        });
    };

    const useDelete = () => {
        const queryClient = useQueryClient();
        return useMutation({
            mutationFn: (id) => api.delete(`${basePath}/${id}`),
            onSuccess: () => {
                queryClient.invalidateQueries({ queryKey: queryKey() });
            },
        });
    };

    const useSearch = (query) => {
        return useQuery({
            queryKey: buildQueryKey(entity, QUERY_KEYS.SEARCH, query),
            queryFn: () => api.get(searchEndpoint || `${basePath}/search`, { params: { q: query } }),
            enabled: !!query && query.length >= 2,
        });
    };

    return {
        useList,
        useItem,
        useCreate,
        useUpdate,
        usePatch,
        useDelete,
        useSearch,
    };
}
