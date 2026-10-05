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
        // effect on the next render instead of the next refetch.
        queryKey: galleryListingKey(filters, limit),
        queryFn: ({ pageParam = null, signal }) =>
            fetchGalleryPage({ filters, limit, groupBy, pageParam, signal }),
        getNextPageParam: (lastPage) => lastPage.nextPage,
        initialPageParam: null,
        staleTime: 1 * 60 * 1000, // 1 minute
    });
}

/** The cache key of one gallery listing. Shape is part of the contract. */
export function galleryListingKey(filters, limit) {
    return ['gallery', filters, limit];
}

/**
 * One page of the gallery listing.
 *
 * Factored out of `useGallery`'s `queryFn` so that
 * `refetchNewestGalleryPage` below fetches byte-identical parameters for the
 * page it replaces. Two copies of this parameter list is how a "refresh the
 * first page" path ends up quietly dropping a filter.
 */
async function fetchGalleryPage({ filters = {}, limit, groupBy, pageParam = null, signal } = {}) {
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
        assetsApi.facet(params, { signal }),
        isFirstPage
            ? jobsApi.list({ limit, sort: 'created_at_desc' }, { signal }).catch(() => ({ jobs: [] }))
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
}

/** In-flight refreshes, keyed by query-key hash, so two handlers on one event cost one request. */
const newestPageRefreshes = new WeakMap();

/**
 * Refetch ONLY the newest page of every cached gallery listing, in place.
 *
 * ## Why not `invalidateQueries({ queryKey: ['gallery'] })`
 *
 * `useGallery` is a `useInfiniteQuery`, and an invalidation of it refetches
 * *every* page already loaded, sequentially — with fifteen pages loaded that is
 * fifteen requests for one finished job, and each one changes the list height as
 * it lands, which moves the infinite-scroll sentinel. So the obvious thing to
 * reach for is `refetchPage`, which is what three call sites pass
 * (`useGalleryAutoRefresh.js`, `useJobsRealtime.jsx` ×2).
 *
 * **`refetchPage` does not exist in react-query v5.** `RefetchQueryFilters` and
 * `InvalidateQueryFilters` in `@tanstack/query-core@5.90.11` are
 * `QueryFilters` and nothing else — no such member, and the built package
 * contains no reference to it at all. It was a query-core v3 option, dropped in
 * v4. Those three call sites were silently doing a full-library invalidation:
 * the extra object property was carried, and then ignored. `src/test/`
 * `galleryNewestPageRefresh.test.js` pins the absence, because the way this
 * defect survived is that a test asserting the option was *passed* passes just
 * as happily when the option does nothing.
 *
 * ## Why not "mark stale and refetch page 0 through the query"
 *
 * There is no page-scoped entry point either. `fetchNextPage` *appends*; a
 * plain refetch calls `infiniteQueryBehavior()` with no page count, which walks
 * `oldPages.length` pages from scratch, and constructing the behaviour with a
 * count of one would truncate `pages` to a single entry rather than refresh it.
 * So the newest page is fetched here and written back with `setQueryData`,
 * which is the one operation react-query will not second-guess.
 *
 * ## Scope
 *
 * `mountedOnly` is what `useJobsRealtime` wants: an unobserved listing is stale
 * anyway, so its next mount refetches it and a background request would buy
 * nothing. `pageParams[0]` is left alone — page 0's cursor is `initialPageParam`
 * (`null`) and cannot change.
 *
 * The query is left marked FRESH afterwards, deliberately. Marking it
 * invalidated would make the observer refetch the whole thing on its next tick,
 * which is the behaviour being removed.
 */
export async function refetchNewestGalleryPage(queryClient, { mountedOnly = false } = {}) {
    const listings = queryClient.getQueryCache()
        .findAll({ queryKey: ['gallery'] })
        .filter((query) => (
            Array.isArray(query.state.data?.pages)
            // Mid-flight: a full page walk is already paying for itself.
            && query.state.fetchStatus === 'idle'
            && (!mountedOnly || query.getObserversCount() > 0)
        ));
    if (listings.length === 0) return 0;

    const inFlight = newestPageRefreshes.get(queryClient) || new Map();
    newestPageRefreshes.set(queryClient, inFlight);

    await Promise.all(listings.map(async (query) => {
        const [, filters, limit] = query.queryKey;
        const groupBy = filters?.group_by || FACET_DIMENSIONS.join(',');

        // Two handlers can fire on one event (the job card updates and the
        // gallery auto-refresh both react to `job.completed`); one request is
        // the right answer for both.
        const hash = JSON.stringify(query.queryKey);
        if (inFlight.has(hash)) return inFlight.get(hash);
        const run = (async () => {
            const page = await fetchGalleryPage({ filters, limit, groupBy, pageParam: null });
            queryClient.setQueryData(query.queryKey, (old) => (
                old?.pages?.length ? { ...old, pages: [page, ...old.pages.slice(1)] } : old
            ));
        })().finally(() => inFlight.delete(hash));
        inFlight.set(hash, run);
        return run;
    }));

    return listings.length;
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
        queryFn: ({ signal }) => assetsApi.dates(params, { ...options, signal }),
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

// The tag vocabulary used to be exported from here as well as from
// `useAssetTags.js`. Two exports, one name, two signatures —
// `(prefix = '', options)` against `({prefix, q, limit}, options)` — and both
// import sites read `import { useTagVocabulary }`, so the object-signature
// version handed a bare string to destructuring and silently produced the
// *unfiltered* vocabulary (`prefix`, `q` and `limit` all `undefined`) with no
// error at all. Two cache keys over one endpoint is what made that survivable.
// The single implementation is `useTagVocabulary` in `./useAssetTags`; the panel
// that used the deleted copy imports it from there.
