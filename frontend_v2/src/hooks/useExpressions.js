import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

export const useExpressions = (characterId) => {
    return useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, characterId, 'expressions'),
        queryFn: ({ signal }) => api.get(`/api/v2/characters/${characterId}/expressions`, { signal }),
        enabled: !!characterId,
    });
};

export const useUpdateExpressions = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ characterId, expressions, expressions_lora }) =>
            api.patch(`/api/v2/characters/${characterId}`, { expressions, expressions_lora }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS) });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, variables.characterId, 'expressions') });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHARACTERS, variables.characterId) });
        }
    });
};
