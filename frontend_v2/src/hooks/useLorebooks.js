import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { useCreateResource, useDeleteResource, useUpdateResource } from './useWorldVaultResource';

const LOREBOOKS_KEY = buildQueryKey(QUERY_KEYS.LOREBOOKS);
const LOREBOOK_DETAIL_KEY = (id) => buildQueryKey(QUERY_KEYS.LOREBOOKS, id);
const LOREBOOK_ENTRIES_KEY = (lorebookId) => LOREBOOK_ENTRIES_KEY(lorebookId);

export const useLorebooks = () => {
    return useQuery({
        queryKey: LOREBOOKS_KEY,
        queryFn: () => api.get('/api/v2/lorebooks')
    });
};

export const useCreateLorebook = () => useCreateResource({ basePath: '/api/v2/lorebooks', listQueryKey: LOREBOOKS_KEY });

export const useUpdateLorebook = () => useUpdateResource({
    basePath: '/api/v2/lorebooks',
    listQueryKey: LOREBOOKS_KEY,
    detailQueryKey: LOREBOOK_DETAIL_KEY,
});

export const useDeleteLorebook = () => useDeleteResource({
    basePath: '/api/v2/lorebooks',
    listQueryKey: LOREBOOKS_KEY,
    onDone: (queryClient) => {
        queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES) });
        // Every chat's system-prompt assembly embeds the active lorebook, and a
        // delete can change which one is active — so this one keeps the
        // whole-chat invalidation on purpose.
        queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.CHATS) });
    },
});

export const useLorebookEntries = (lorebookId) => {
    return useQuery({
        queryKey: LOREBOOK_ENTRIES_KEY(lorebookId),
        queryFn: () => api.get(`/api/v2/lorebooks/${lorebookId}/entries`),
        enabled: !!lorebookId,
    });
};

export const useCreateEntry = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ lorebookId, ...data }) => api.post(`/api/v2/lorebooks/${lorebookId}/entries`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: LOREBOOK_ENTRIES_KEY(variables.lorebookId) });
        }
    });
};

export const useUpdateEntry = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ lorebookId, id, ...data }) => api.put(`/api/v2/lorebooks/${lorebookId}/entries/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: LOREBOOK_ENTRIES_KEY(variables.lorebookId) });
        }
    });
};

export const useDeleteEntry = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ lorebookId, id }) => api.delete(`/api/v2/lorebooks/${lorebookId}/entries/${id}`),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: LOREBOOK_ENTRIES_KEY(variables.lorebookId) });
        }
    });
};

/**
 * Server-side entry search, fired by the Lorebooks page's explicit Search
 * button — a mutation is the right shape for that, a query would fire on every
 * keystroke. It used to `setQueryData` under a key nothing ever read, so the
 * page only ever saw `mutate.data`.
 */
export const useSearchEntries = () => {
    return useMutation({
        mutationFn: ({ lorebookId, q, limit }) => api.get(`/api/v2/lorebooks/${lorebookId}/search`, { params: { q, limit } })
    });
};

export const useReindexLorebook = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (lorebookId) => api.post(`/api/v2/lorebooks/${lorebookId}/reindex`),
        onSuccess: (_, lorebookId) => {
            queryClient.invalidateQueries({ queryKey: LOREBOOK_ENTRIES_KEY(lorebookId) });
        }
    });
};

export const useImportLorebookEntries = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ lorebookId, payload }) => api.post(`/api/v2/lorebooks/${lorebookId}/import`, payload),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: LOREBOOK_ENTRIES_KEY(variables.lorebookId) });
            queryClient.invalidateQueries({ queryKey: LOREBOOKS_KEY });
        }
    });
};

export const useBulkDeleteEntries = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ lorebookId, entryIds }) => api.post(`/api/v2/lorebooks/${lorebookId}/entries/bulk-delete`, { entry_ids: entryIds }),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: LOREBOOK_ENTRIES_KEY(variables.lorebookId) });
        }
    });
};
