import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { QUERY_KEYS } from '../constants/queryKeys';
import { installedVersionsKey } from './useCivitaiSearch';

/**
 * `POST /api/v2/models/{id}/autopopulate` — one mutation, one invalidation.
 *
 * Four files wrote this mutation out by hand, and they had drifted into three
 * different behaviours over the same endpoint:
 *
 *   - `ModelMetadataModal.jsx` and `ModelDetailsModal.jsx` each built their own
 *     `useMutation`, and each had to remember the same two invalidations. That
 *     they arrived at the right ones at all is luck: a third call site following
 *     the same shape would have been a copy of the same reasoning, and the
 *     invalidation that keeps the Discover tab's "already installed" ticks
 *     honest is the easiest of the two to forget.
 *   - `AutopopulateSelector.jsx` invalidated *nothing*. After it applied a
 *     match, the installed-model list kept the pre-write name, tags and stats —
 *     and since `refetchOnWindowFocus` is globally off, nothing corrected it
 *     later.
 *   - `BatchAutopopulateModal.jsx` also invalidated nothing; it only removed the
 *     model from the pending list optimistically.
 *
 * Two notes on the invalidation itself, both of which the call sites had
 * re-derived independently:
 *
 *   - `{ queryKey: [QUERY_KEYS.MODELS] }` is the OBJECT form. The react-query v4
 *     positional form `invalidateQueries(['models'])` spreads the array into the
 *     filters object in v5, leaving `queryKey` undefined, which matches every
 *     query in the cache — one autopopulate refetching the whole app.
 *   - `installedVersionsKey` is `['model', 'installed', <civitai id>]`, the only
 *     query in that namespace. It was `{ queryKey: ['model', file.model_id] }`
 *     at one call site — two elements under a three-element key, and a *local*
 *     id where the query is keyed by a *civitai* id, so it missed on both counts.
 *     It is only invalidated when a `civitaiId` is known, which is exactly when
 *     the match was explicit; an auto-discovery run matched nothing by hand.
 *
 * `mutateAsync` resolves with the response's `data`, as
 * `ModelMetadataModal`'s hand-written version did.
 */
export function useAutopopulateModel() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ modelId, civitaiId = null }) => {
            if (!modelId) throw new Error('A model id is required to autopopulate');
            const payload = civitaiId ? { civitai_id: civitaiId } : {};
            const res = await api.post(`/api/v2/models/${modelId}/autopopulate`, payload);
            return res?.data ?? res;
        },
        onSuccess: (_result, variables) => {
            queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.MODELS] });
            // The id the write matched against is the id space this key uses.
            if (variables?.civitaiId) {
                queryClient.invalidateQueries({ queryKey: installedVersionsKey(variables.civitaiId) });
            }
        },
    });
}

export function useAutopopulateStatus(options = {}) {
    return useQuery({
        queryKey: ['models', 'autopopulate-status'],
        queryFn: async ({ signal }) => {
            const res = await api.get('/api/v2/models/autopopulate-status', { signal });
            return res?.data ?? res;
        },
        ...options,
    });
}