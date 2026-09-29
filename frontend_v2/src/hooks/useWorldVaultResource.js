import { useMutation, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

/**
 * `onDone` is the caller's extra work after the invalidation this helper
 * already does; it is not the mutation's own `onSuccess` (which is the
 * `onSuccess:` key below). Same name, two different things.
 *
 * Every mutation here surfaces its failure. They did not before: no
 * `onError`, and no optimistic update, so a rejected write produced neither a
 * visible change nor a message. The Story sandbox alone drives roughly twenty
 * of these through its context panel — character/lorebook/location link
 * toggles, the AI model, the agentic-depth slider, the sampling overrides,
 * archive, and the onBlur-saved `genre` / `word_count_goal` / `description` /
 * `memory` fields — and a 4xx on any of them read as "the toggle does nothing".
 */
function reportError(action, error) {
    // `api` raises `ApiError`, whose message is already extracted from the
    // response body, so the raw message is the useful one. The status is
    // appended because "Failed to save story" alone does not distinguish a 400
    // the user caused from a 500 they did not.
    const detail = error?.message || 'Unknown error';
    const status = error?.status ? ` (${error.status})` : '';
    toast.error(`Failed to ${action}${status}: ${detail}`);
}

export function useCreateResource({ basePath, listQueryKey, onDone, entityName = 'item' }) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data) => api.post(basePath, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: listQueryKey });
            onDone?.(queryClient);
        },
        onError: (error) => reportError(`create ${entityName}`, error),
    });
}

export function useDeleteResource({ basePath, listQueryKey, onDone, entityName = 'item' }) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id) => api.delete(`${basePath}/${id}`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: listQueryKey });
            onDone?.(queryClient);
        },
        onError: (error) => reportError(`delete ${entityName}`, error),
    });
}

export function useUpdateResource({ basePath, listQueryKey, detailQueryKey, onDone, entityName = 'item' }) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`${basePath}/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: listQueryKey });
            queryClient.invalidateQueries({ queryKey: detailQueryKey(variables.id) });
            onDone?.(queryClient, variables);
        },
        onError: (error) => reportError(`save ${entityName}`, error),
    });
}
