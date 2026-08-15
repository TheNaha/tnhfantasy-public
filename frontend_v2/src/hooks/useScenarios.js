import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useScenarios = () => {
    return useQuery({
        queryKey: ['world_vault', 'scenarios'],
        queryFn: () => api.get('/api/v2/scenarios')
    });
};

export const useCreateScenario = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post('/api/v2/scenarios', data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'scenarios'] });
        }
    });
};

export const useUpdateScenario = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`/api/v2/scenarios/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'scenarios'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'scenarios', variables.id] });
        }
    });
};



export const useDeleteScenario = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`/api/v2/scenarios/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'scenarios'] });
        }
    });
};

export const useApplyScenario = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ scenarioId, targetType, targetId }) => api.post(
            `/api/v2/scenarios/${scenarioId}/apply`,
            { target_type: targetType, target_id: targetId }
        ),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'scenarios'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories'] });
        }
    });
};
