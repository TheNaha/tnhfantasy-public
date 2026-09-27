import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { assetsApi, jobsApi } from '../api';
import useSettingsStore from '../store/settingsStore';

/**
 * The dimensions the filter panel can group by, in the order it shows them.
 *
 * The server caps `group_by` at three dimensions per request, so the panel sends
 * only what it is displaying — a fourth is a 400, not a silently ignored
 * parameter. `session` is deliberately absent: session membership is not a
 * column on `assets` (it lives in `session_assets`), so it is reached through
 * `session_id` on the listing and through `include_sessions`, not as a facet.
 */
export const FACET_DIMENSIONS = ['lora', 'tag', 'checkpoint'];

/** The filter keys that narrow the LISTING, as opposed to the panel's own state. */
const LISTING_PARAMS = [
    'search', 'workspace', 'character_id', 'story_id', 'sort',
    'lora', 'tag', 'checkpoint', 'session_id',
    'date_from', 'date_to', 'date_column',
];

/**
 * The gallery.
 *
 * Calls `/api/v2/assets/facet` rather than `/api/v2/assets`. That is a
 * deliberate consolidation, not an addition: the facet endpoint accepts the same
 * filter vocabulary, the same sort names and the same keyset cursor, and
 * returns the same item shape — but it also returns the facet counts and the
 * matching sessions *in the same round trip*. Fetching `/api/v2/assets` for the
 * page and then a second request for the counts would mean two query paths
 * over the same data, and the two can disagree about which images matched.
 *
 * The return shape is unchanged, so nothing downstream of this hook knows.
 */
export function useGallery(filters = {}) {
    // Settings > Gallery > "Items Per Page" writes this; it used to be a
    // hardcoded 20, which left the control dead.
    const limit = useSettingsStore((s) => s.settings?.gallery?.itemsPerPage) || 20;
    const groupBy = filters.group_by || FACET_DIMENSIONS.join(',');

    return useInfiniteQuery({
        // The limit is in the key so changing "Items Per Page" in Settings takes
        // effect on the next render instead of the next refetch. Everything that
        // invalidates the gallery uses `['gallery', filters]` as a prefix.
        queryKey: ['gallery', filters, limit],
        queryFn: async ({ pageParam = null }) => {
            const params = { limit, cursor: pageParam || undefined, group_by: groupBy };
            for (const key of LISTING_PARAMS) params[key] = filters[key];

            // Drop unset filters. A key sent as the empty string filters on the
            // literal text `""`, which is how "clear the search box" used to
            // return nothing.
            Object.keys(params).forEach(key => {
                if (params[key] === undefined || params[key] === null || params[key] === '') {
                    delete params[key];
                }
            });

            // Page 1 carries the facet counts and the jobs; later pages carry
            // neither, and asking again would cost a round trip per scroll for
            // numbers that cannot have changed.
            const isFirstPage = !pageParam;
            const [assetsData, jobsData] = await Promise.all([
                assetsApi.facet(params),
                isFirstPage
                    ? jobsApi.list({ limit, sort: 'created_at_desc' }).catch(() => ({ jobs: [] }))
                    : Promise.resolve({ jobs: [] }),
            ]);

            return {
                files: assetsData.items || [],
                jobs: jobsData.jobs || [],
                nextPage: assetsData.has_more ? assetsData.next_cursor : undefined,
                // Read off page 1 only. `Dashboard` flattens `data.pages` for the
                // grid and these are for the panel, which sits outside it.
                facets: isFirstPage ? (assetsData.facets || {}) : {},
                // `sessions` is deliberately NOT surfaced. The endpoint returns it
                // only when `include_sessions` is set, which is off by default and
                // gates a real join; nothing renders it yet, so requesting it would
                // buy an unrendered query on every gallery load. It is the obvious
                // next facet dimension — "which sessions used this LoRA" — and
                // `session` is one of the six the backend supports.
                totalMatched: isFirstPage ? assetsData.total_matched : undefined,
            };
        },
        getNextPageParam: (lastPage) => lastPage.nextPage,
        initialPageParam: null,
        staleTime: 1 * 60 * 1000, // 1 minute
    });
}

/**
 * Per-day counts for the date rail.
 *
 * Scoped by exactly the filters the LISTING takes, and deliberately NOT by the
 * facet filters: a rail scoped to the current selection tells you how much you
 * have selected, which is not a navigation aid. The panel shows the whole
 * library's shape and the list narrows beneath it.
 */
export function useAssetDateHistogram(filters = {}, options = {}) {
    const params = {
        workspace: filters.workspace,
        character_id: filters.character_id,
        story_id: filters.story_id,
        search: filters.search,
    };

    return useQuery({
        queryKey: ['gallery', 'dates', params],
        queryFn: () => assetsApi.dates(params, options),
        // Day boundaries move only when images are added, and this is a
        // whole-table aggregate. An hour beats re-scanning on every keystroke.
        staleTime: 60 * 60 * 1000,
        select: (data) => ({
            days: data?.days || [],
            total: data?.total ?? 0,
            firstDay: data?.first_day ?? null,
            lastDay: data?.last_day ?? null,
        }),
    });
}

/** The tag vocabulary, for the tag dimension's typeahead. `prefix` is anchored. */
export function useTagVocabulary(prefix = '', options = {}) {
    return useQuery({
        queryKey: ['gallery', 'tags', prefix],
        // The key is omitted rather than sent as `undefined`, so an empty input
        // is "no prefix" on the wire instead of a parameter the client has to
        // strip.
        queryFn: () => assetsApi.tags({ ...(prefix ? { prefix } : {}), limit: 24 }, options),
        enabled: true,
        staleTime: 5 * 60 * 1000,
        select: (data) => data?.tags || [],
    });
}
