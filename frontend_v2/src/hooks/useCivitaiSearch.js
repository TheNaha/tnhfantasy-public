import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { api } from '../api';

/** Default page size for the CivitAI search, and the only one the UI has used. */
const DEFAULT_LIMIT = 20;

export function useCivitaiEnums() {
    return useQuery({
        queryKey: ['civitai', 'enums'],
        queryFn: async ({ signal }) => {
            try {
                const data = await api.get('/api/v2/models/external/civitai/enums', { signal });
                return {
                    ModelType: data.ModelType || [],
                    BaseModel: data.BaseModel || []
                };
            } catch (err) {
                // An abort is not a failure to report: the component that asked
                // is gone. `console.warn` on a cancelled keystroke is noise.
                if (err?.name === 'AbortError') throw err;
                console.warn("Failed to fetch CivitAI enums:", err);
                return {
                    ModelType: ['Checkpoint', 'LORA', 'VAE', 'Controlnet', 'Upscaler', 'TextualInversion', 'Hypernetwork', 'MotionModule'],
                    BaseModel: ['SD 1.5', 'SDXL 1.0', 'SD 3', 'SD 3.5', 'Flux.1 D', 'Pony', 'Illustrious']
                };
            }
        },
        staleTime: 1000 * 60 * 60, // 1 hour
    });
}

export function useCivitaiTags() {
    return useQuery({
        queryKey: ['civitai', 'tags'],
        queryFn: async ({ signal }) => {
            const data = await api.get('/api/v2/models/external/civitai/tags?limit=20', { signal });
            return data.items || [];
        },
        staleTime: 1000 * 60 * 60,
    });
}

/**
 * CivitAI (and HuggingFace) model search. The single implementation.
 *
 * `filters` is the whole query key, so every field that changes the request
 * belongs in it: `query`, `source`, `types`, `sort`, `baseModels`, `nsfw`,
 * `period`, `username`, `tag`, and `limit`.
 *
 * This used to have two rivals, both over the same endpoint:
 *
 *   - `CivitaiSearchModal.jsx` ran a hand-rolled `useQuery` under the key
 *     `['civitaiSearch', query, type, sort, baseModel, nsfw]` — a second cache
 *     for one search, so a result fetched in the Discover tab and the same
 *     result fetched from the generator's model picker were fetched twice and
 *     could disagree. It is reachable from `ModelMetadataModal`, so the
 *     divergence was user-visible.
 *   - `AutopopulateSelector.jsx` did a raw `api.get` inside a `useState`, with
 *     `limit: 12` hardcoded and no cache at all: every manual search re-hit the
 *     network even for a query it had just run, and nothing it learned was
 *     visible to any other caller.
 *
 * `useCivitaiSearchPage` below is the one-line adapter for callers that want a
 * single page rather than an infinite list. It is the *same* query — same key,
 * same fetcher — so it is a shape change, not a second cache.
 */
export function useCivitaiSearch(filters, options = {}) {
    const { limit = DEFAULT_LIMIT, ...rest } = filters || {};
    return useInfiniteQuery({
        queryKey: ['civitai', 'search', { ...rest, limit }],
        queryFn: async ({ pageParam, signal }) => {
            const params = new URLSearchParams({ limit: String(limit) });

            if (rest.query) params.append('query', rest.query);

            // Deliberately a strict comparison, unchanged: a `source` that is
            // absent is NOT the civitai branch, so no filter vocabulary is sent.
            if (rest.source === 'civitai') {
                if (rest.types?.length > 0) params.append('types', rest.types.join(','));
                if (rest.sort) params.append('sort', rest.sort);
                if (rest.baseModels?.length > 0) params.append('baseModels', rest.baseModels.join(','));
                if (rest.nsfw) params.append('nsfw', rest.nsfw);
                if (rest.period) params.append('period', rest.period);
                if (rest.username) params.append('username', rest.username);
                if (rest.tag) params.append('tag', rest.tag);

                if (pageParam?.cursor) {
                    params.append('cursor', pageParam.cursor);
                } else if (pageParam?.page) {
                    // The two branches this collapsed were byte-identical: one
                    // guarded on `!filters.query` and the next was unguarded, so
                    // between them every `page` was sent.
                    params.append('page', pageParam.page);
                }
            } else if (pageParam?.page) {
                params.append('page', pageParam.page);
            }

            const source = rest.source || 'civitai';
            const endpoint = `/api/v2/models/external/${source}`;
            const url = `${endpoint}?${params.toString()}`;

            return await api.get(url, { signal });
        },
        initialPageParam: { page: 1, cursor: null },
        getNextPageParam: (lastPage, allPages) => {
            if (lastPage.metadata?.nextCursor) {
                return { cursor: lastPage.metadata.nextCursor, page: allPages.length + 1 };
            }
            if (lastPage.metadata?.nextPage) {
                return { page: allPages.length + 1, cursor: null };
            }
            return null;
        },
        enabled: options.enabled !== false,
    });
}

/**
 * The first page of the same search, for callers that render a plain result
 * list and never paginate.
 *
 * Shares `useCivitaiSearch`'s key exactly, so mounting both against the same
 * filters is one request and one cache entry — which is the point of the
 * consolidation. Returns the page object (`{ items, metadata }`), not the items
 * array, because the previous hand-rolled callers read `results.items`.
 */
export function useCivitaiSearchPage(filters, options = {}) {
    const query = useCivitaiSearch(filters, options);
    return {
        ...query,
        data: query.data?.pages?.[0],
    };
}

export function useBatchAutopopulateCandidates(modelIds, options = {}) {
    return useQuery({
        queryKey: ['autopopulate', 'candidates', 'batch', modelIds],
        queryFn: async ({ signal }) => {
            if (!modelIds || modelIds.length === 0) return [];
            const data = await api.post('/api/v2/models/autopopulate-candidates/batch', { model_ids: modelIds }, { signal });
            return data.results || [];
        },
        enabled: options.enabled !== false && modelIds?.length > 0,
        staleTime: 1000 * 60 * 5,
    });
}

export function useAutopopulatePending() {
    return useQuery({
        queryKey: ['autopopulate', 'pending'],
        queryFn: async ({ signal }) => {
            const data = await api.get('/api/v2/models/autopopulate-pending', { signal });
            return data.pending || [];
        }
    });
}

export function useAutopopulateCandidates(modelId) {
    return useQuery({
        queryKey: ['autopopulate', 'candidates', modelId],
        queryFn: async ({ signal }) => {
            if (!modelId) return null;
            const res = await api.get(`/api/v2/models/${modelId}/autopopulate-candidates`, { signal });
            return res;
        },
        enabled: !!modelId,
    });
}

/**
 * The one query in the `['model', …]` namespace, and the only consumer of the
 * endpoint it hits (`GET /api/v2/models/check-installed/{civitai_model_id}`).
 *
 * Three mutation sites tried to invalidate it as `{ queryKey: ['model',
 * modelId] }` — a two-element key under a namespace whose only query is
 * three-element, so it matched nothing at all and the Discover tab's
 * "already installed" ticks stayed whatever they were before the write. Note
 * the id spaces differ and are not interchangeable: this key is keyed by
 * *CivitAI* model id (`ModelImportCard` passes the search result's `model.id`),
 * while the mutating components mostly have a *local* model id. Invalidating is
 * still correct for the autopopulate path, which is handed the civitai id it
 * just matched — see `useAutopopulateModel`, which now owns that invalidation
 * for all four call sites.
 */
export const installedVersionsKey = (civitaiModelId) => ['model', 'installed', civitaiModelId];

export function useCheckInstalledVersions(modelId) {
    return useQuery({
        queryKey: installedVersionsKey(modelId),
        queryFn: async ({ signal }) => {
            if (!modelId) return [];
            const data = await api.get(`/api/v2/models/check-installed/${modelId}`, { signal });
            return data.installed_versions || [];
        },
        enabled: !!modelId,
    });
}