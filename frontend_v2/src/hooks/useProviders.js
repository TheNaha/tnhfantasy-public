import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

// Fetch all providers
export function useProviders() {
    return useQuery({
        queryKey: ['providers'],
        queryFn: () => api.get('/api/providers'),
    });
}

// Start a provider container
export function useStartProvider() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (providerId) => api.post(`/api/providers/${providerId}/container/start`),
        onSuccess: () => {
            queryClient.invalidateQueries(['providers']);
        },
    });
}

// Stop a provider container
export function useStopProvider() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (providerId) => api.post(`/api/providers/${providerId}/container/stop`),
        onSuccess: () => {
            queryClient.invalidateQueries(['providers']);
        },
    });
}

// Deploy Modal application
export function useDeployProvider() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (providerId) => api.post(`/api/providers/${providerId}/deploy`),
        onSuccess: () => {
            queryClient.invalidateQueries(['providers']);
        },
    });
}
