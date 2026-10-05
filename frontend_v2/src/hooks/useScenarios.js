import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { useCreateResource, useDeleteResource, useUpdateResource } from './useWorldVaultResource';

const SCENARIOS_KEY = buildQueryKey(QUERY_KEYS.SCENARIOS);

export const useScenarios = () => {
    return useQuery({
        queryKey: SCENARIOS_KEY,
        queryFn: ({ signal }) => api.get('/api/v2/scenarios', { signal })
    });
};

export const useCreateScenario = () => useCreateResource({ basePath: '/api/v2/scenarios', listQueryKey: SCENARIOS_KEY });

// No `detailQueryKey`: `useScenarios` declares only the list, so a key of
// `['world_vault','scenarios',id]` prefix-matched nothing.
export const useUpdateScenario = () => useUpdateResource({
    basePath: '/api/v2/scenarios',
    listQueryKey: SCENARIOS_KEY,
});

export const useDeleteScenario = () => useDeleteResource({ basePath: '/api/v2/scenarios', listQueryKey: SCENARIOS_KEY });

export const useApplyScenario = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ scenarioId, targetType, targetId }) => api.post(
            `/api/v2/scenarios/${scenarioId}/apply`,
            { target_type: targetType, target_id: targetId }
        ),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.SCENARIOS) });
            if (variables?.targetType === 'chat') {
                // Applying rewrites one chat's system-prompt override, so only
                // that chat's detail query has to be rebuilt.
                queryClient.invalidateQueries({
                    queryKey: buildQueryKey(QUERY_KEYS.CHATS, variables.targetId),
                    exact: true,
                });
            }
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES) });
        }
    });
};
