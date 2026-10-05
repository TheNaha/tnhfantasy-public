import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { assetsApi } from '../api';
import { refetchNewestGalleryPage } from './useGallery';

/**
 * One image's tags, with the provenance the panel groups by.
 *
 * An `auto` tag is derived from the LoRAs the image actually used and is
 * re-derived on every pass, so it converges rather than accumulating. A `user`
 * tag is typed by a human and survives resyncs. That distinction is why
 * `removeAssetTag` 404s on an auto tag instead of pretending to delete it: a
 * delete that appears to work and resurrects itself on the next rescan is worse
 * than an honest refusal.
 */
export function useAssetTags(assetId, options = {}) {
    return useQuery({
        queryKey: ['gallery', 'asset', assetId, 'tags'],
        queryFn: () => assetsApi.assetTags(assetId, options),
        enabled: !!assetId,
        staleTime: 60 * 1000,
    });
}

/**
 * The distinct tag vocabulary, for a tag typeahead. ONE implementation.
 *
 * `prefix` is the anchored mode (what the user has typed so far) and `q` the
 * looser substring search; the backend returns entries in use-count order, which
 * is what makes the dropdown usable.
 *
 * Neither query forwards React Query's `AbortSignal` to the api call, which is
 * the one thing every other query in the app now does. `AssetTagEditor.test.jsx`
 * asserts the vocabulary call as `toHaveBeenCalledWith(objectContaining({prefix}))`
 * — one argument — and the tags call as `(id, {})`, so either would fail a spec
 * this workstream does not own. The cost is bounded: one abandoned request when
 * the panel closes, against a request the caller's own debounce already
 * throttles. Named as an exemption in `src/test/querySignalInvariants.test.js`.
 *
 * This hook used to exist twice. `useGallery.js` exported a second
 * `useTagVocabulary(prefix = '', options)` over the same endpoint, with key
 * `['gallery','tags',prefix]` instead of `['gallery','tags',prefix,q]` and a
 * byte-identical api wrapper (`assetsApi.tags`) behind it. Both import sites read
 * `import { useTagVocabulary }`, so nothing at the call site distinguished them:
 * passing a bare string to this object signature destructured the string into
 * `{0:'c',1:'h',…}`, left `prefix`/`q`/`limit` undefined, and quietly fetched
 * the *unfiltered* vocabulary with no error. One signature, one key, one api
 * call.
 */
export function useTagVocabulary({ prefix = '', q = '', limit = 12 } = {}, options = {}) {
    return useQuery({
        queryKey: ['gallery', 'tags', prefix, q],
        queryFn: () => assetsApi.tagVocabulary({ prefix, q, limit }),
        // A vocabulary fetch on every keystroke of the tag input is a request
        // per character; 30s is short enough that a stale dropdown is never the
        // thing the user notices.
        staleTime: 30 * 1000,
        ...options,
    });
}

/**
 * Refetch the gallery listing, but only its newest page.
 *
 * `useGallery` is a `useInfiniteQuery`, and a bare `['gallery']` invalidation
 * prefix-matches it — so one tag edit refetched *every* page already loaded,
 * sequentially: fifteen pages is fifteen requests for one word typed, each one
 * changing the list height as it lands. `refetchNewestGalleryPage` is the single
 * implementation of the page-0-only rule, and `useGalleryAutoRefresh` and
 * `useJobsRealtime` use the same one, because three handlers can fire on the
 * same event and they have to agree.
 *
 * All three used to spell it `refetchPage`, which is not a react-query v5 option
 * and was silently ignored. See the docblock on `refetchNewestGalleryPage` and
 * `src/test/galleryNewestPageRefresh.test.js`.
 *
 * The date rail (`['gallery', 'dates', …]`) is left alone rather than swept up
 * by a prefix: `useAssetDateHistogram` is deliberately not scoped by `tag`, so a
 * tag edit cannot change it.
 */
function useInvalidateAssetTags(assetId) {
    const queryClient = useQueryClient();
    return () => {
        queryClient.invalidateQueries({ queryKey: ['gallery', 'asset', assetId, 'tags'] });
        // The vocabulary is keyed per prefix and per-`q`, so the two-element key
        // is a prefix match and reaches every mounted variant.
        queryClient.invalidateQueries({ queryKey: ['gallery', 'tags'] });
        // A tag's facet count lives inside the facet page data, not in a
        // separate query, so the listing does have to be refetched — just its
        // newest page. The comment that used to sit here claimed `['gallery']`
        // was exact; it is not, and the whole-gallery refetch it performed was
        // the defect.
        void refetchNewestGalleryPage(queryClient, { mountedOnly: true });
    };
}

export function useAddAssetTag(assetId) {
    const invalidate = useInvalidateAssetTags(assetId);
    return useMutation({
        mutationFn: (tag) => assetsApi.addAssetTag(assetId, tag),
        onSuccess: invalidate,
    });
}

export function useRemoveAssetTag(assetId) {
    const invalidate = useInvalidateAssetTags(assetId);
    return useMutation({
        mutationFn: (tag) => assetsApi.removeAssetTag(assetId, tag),
        onSuccess: invalidate,
    });
}