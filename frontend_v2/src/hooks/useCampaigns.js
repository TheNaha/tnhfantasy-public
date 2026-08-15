import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey } from '../constants/queryKeys';

export const useCampaigns = () => {
    return useQuery({
        queryKey: buildQueryKey('campaigns'),
        queryFn: () => api.get('/api/v2/campaigns'),
    });
};



export const useCampaignDashboard = (campaignId) => {
    return useQuery({
        queryKey: buildQueryKey('campaigns', campaignId, 'dashboard'),
        queryFn: () => api.get(`/api/v2/campaigns/${campaignId}/dashboard`),
        enabled: !!campaignId,
    });
};

export const useCreateCampaign = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post('/api/v2/campaigns', data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey('campaigns') });
        },
    });
};

export const useUpdateCampaign = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/campaigns/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey('campaigns') });
            queryClient.invalidateQueries({ queryKey: buildQueryKey('campaigns', variables.id) });
        },
    });
};

export const useDeleteCampaign = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v2/campaigns/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey('campaigns') });
        },
    });
};
