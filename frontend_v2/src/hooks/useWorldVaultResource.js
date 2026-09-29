import { useMutation, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { api } from '../api';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

/**
 * The two vault-wide read models that no entity-scoped invalidation reaches.
 *
 * `useTimeline` (the Activity feed) unions messages, chapters, memories and
 * images, and `useWorldVaultDashboard` counts every entity type. Both are
 * derived aggregates, so an entity mutation cannot invalidate them by its own id
 * — and nothing did, at all. The consequence was that sending a message left
 * the Activity feed missing it for the full 5-minute global `staleTime`
 * (`refetchOnWindowFocus` is off globally, so nothing bounded it), and the
 * roleplay front door's count cards read stale numbers.
 *
 * There is no websocket subscription for either: `api/websocket.js`'s
 * `EventTypes` has no timeline or dashboard topic, and no provider pushes one.
 * Invalidation is the only mechanism available, so every mutation that moves one
 * of these aggregates calls this.
 *
 * `TIMELINE_KEY` is imported lazily-by-value here rather than from
 * `useTimeline` to keep this module free of a query hook import; the string is
 * `buildQueryKey('timeline')` on both sides and
 * `useVaultAggregateInvalidation.test.js` asserts they are the same key.
 */
export function invalidateVaultAggregates(queryClient) {
    queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.TIMELINE) });
    queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.DASHBOARD) });
}

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
            invalidateVaultAggregates(queryClient);
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
            invalidateVaultAggregates(queryClient);
            onDone?.(queryClient);
        },
        onError: (error) => reportError(`delete ${entityName}`, error),
    });
}

/**
 * `detailQueryKey` is OPTIONAL and was load-bearing by accident.
 *
 * It had no default and was called unconditionally in `onSuccess`, and
 * `useUpdatePersona` — the only one of six call sites that omitted it — raised a
 * `TypeError` there. react-query awaits `onSuccess` inside its own `try`, so the
 * TypeError was swallowed and dispatched as an *error*: the PATCH had already
 * succeeded, and the user got two red toasts, an edit form that never closed,
 * and a success callback that never ran. A missing optional argument became a
 * silent data-corruption-shaped failure in every future caller, so the guard
 * lives here rather than at the one call site that happened to trip it.
 *
 * Passing `detailQueryKey` is still correct and worth doing where a detail query
 * really exists (see `useUpdateLocation`), but it is no longer required.
 */
export function useUpdateResource({ basePath, listQueryKey, detailQueryKey, onDone, entityName = 'item' }) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, ...data }) => api.put(`${basePath}/${id}`, data),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: listQueryKey });
            if (detailQueryKey) {
                queryClient.invalidateQueries({ queryKey: detailQueryKey(variables.id) });
            }
            invalidateVaultAggregates(queryClient);
            onDone?.(queryClient, variables);
        },
        onError: (error) => reportError(`save ${entityName}`, error),
    });
}
