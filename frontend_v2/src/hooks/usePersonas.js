import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { useCreateResource, useDeleteResource, useUpdateResource } from './useWorldVaultResource';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

export const PERSONAS_KEY = buildQueryKey(QUERY_KEYS.PERSONAS);

export const usePersonas = () => {
    return useQuery({
        queryKey: PERSONAS_KEY,
        queryFn: () => api.get('/api/v2/personas')
    });
};

export const useCreatePersona = () => useCreateResource({ basePath: '/api/v2/personas', listQueryKey: PERSONAS_KEY });

export const useUpdatePersona = () => useUpdateResource({ basePath: '/api/v2/personas', listQueryKey: PERSONAS_KEY });

export const useDeletePersona = () => useDeleteResource({
    basePath: '/api/v2/personas',
    listQueryKey: PERSONAS_KEY,
    onDone: (queryClient) => {
        // A deleted persona can be the one an open chat is speaking as, and that
        // is only knowable server-side, so all chats are rebuilt.
        queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHATS) });
    },
});
