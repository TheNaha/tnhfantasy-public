import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';

export const useExpressions = (characterId) => {
    return useQuery({
        queryKey: ['world_vault', 'characters', characterId, 'expressions'],
        queryFn: () => api.get(`/api/v2/characters/${characterId}/expressions`),
        enabled: !!characterId,
    });
};

export const useUpdateExpressions = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ characterId, expressions, expressions_lora }) =>
            api.patch(`/api/v2/characters/${characterId}`, { expressions, expressions_lora }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', variables.characterId, 'expressions'] });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'characters', variables.characterId] });
        }
    });
};
