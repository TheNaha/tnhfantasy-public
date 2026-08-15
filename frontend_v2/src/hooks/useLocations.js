import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey } from '../constants/queryKeys';

export const useLocations = () => {
    return useQuery({
        queryKey: buildQueryKey('locations'),
        queryFn: () => api.get('/api/v2/locations'),
    });
};

export const useLocation = (locationId) => {
    return useQuery({
        queryKey: buildQueryKey('locations', locationId),
        queryFn: () => api.get(`/api/v2/locations/${locationId}`),
        enabled: !!locationId,
    });
};

export const useCreateLocation = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post('/api/v2/locations', data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey('locations') });
        },
    });
};

export const useUpdateLocation = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/locations/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey('locations') });
            queryClient.invalidateQueries({ queryKey: buildQueryKey('locations', variables.id) });
        },
    });
};

export const useDeleteLocation = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v2/locations/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey('locations') });
        },
    });
};

export const useSearchLocations = (query) => {
    return useQuery({
        queryKey: buildQueryKey('locations', 'search', query),
        queryFn: () => api.get(`/api/v2/locations/search?q=${encodeURIComponent(query)}`),
        enabled: !!query && query.length > 0,
    });
};
