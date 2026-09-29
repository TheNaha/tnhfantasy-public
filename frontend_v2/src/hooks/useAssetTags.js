import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { assetsApi } from '../api';

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
 * The distinct tag vocabulary, for the editor's typeahead.
 *
 * `prefix` is the anchored mode (what the user has typed so far) and `q` the
 * looser substring search; the backend returns entries in use-count order, which
 * is what makes the dropdown usable. This hook had no query behind the
 * `['gallery', 'tags']` key that `useInvalidateAssetTags` was already
 * invalidating — the invalidation was aimed at nothing.
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

function useInvalidateAssetTags(assetId) {
    const queryClient = useQueryClient();
    return () => {
        queryClient.invalidateQueries({ queryKey: ['gallery', 'asset', assetId, 'tags'] });
        // The vocabulary is keyed per-prefix, so the two-element key is a prefix
        // match and reaches every mounted variant. The comment that used to sit
        // here claimed `['gallery']` was exact; it is not, and the whole gallery
        // refetch is intended — a tag's facet count lives inside the facet page
        // data, not in a separate query.
        queryClient.invalidateQueries({ queryKey: ['gallery', 'tags'] });
        queryClient.invalidateQueries({ queryKey: ['gallery'] });
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
