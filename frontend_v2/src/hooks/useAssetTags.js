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

function useInvalidateAssetTags(assetId) {
    const queryClient = useQueryClient();
    return () => {
        queryClient.invalidateQueries({ queryKey: ['gallery', 'asset', assetId, 'tags'] });
        // The tag counts and the vocabulary both move when a tag is added or
        // removed, and the vocabulary is shared by every image picker, so it is
        // invalidated in full rather than by prefix.
        queryClient.invalidateQueries({ queryKey: ['gallery', 'tags'] });
        // `exact: true` on purpose: the gallery key is a PREFIX of this one, and
        // the key this panel sits inside. The facet counts for `tag` are inside
        // the gallery page data, not a separate query.
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
