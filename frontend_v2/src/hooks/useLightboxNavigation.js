import { useCallback, useMemo } from 'react';
import { assetPath } from '../utils/assetUrl';

/**
 * Stable identity for a gallery item.
 *
 * `name` is only the basename, so two assets in different workspaces can share
 * it. `assetPath` prefers `relative_path`, which the backend builds as
 * `<workspace>/<path>` (e.g. `default_user/chat/2026/09/26/T2I_x.png`) and is
 * therefore unique per file. The collection/favorites filters in
 * `useDashboardItems` already defensively match on both, which is the same
 * divergence this settles.
 */
export function identityOf(item) {
    if (!item) return '';
    return assetPath(item) || item.name || '';
}

/**
 * Flatten the grouped gallery structure into the ordered list of images the
 * user is actually looking at.
 *
 * Order is taken from `sortedGroupedEntries` rather than `displayedItems`
 * because that is the structure the grid/list/feed view renders, and it is the
 * only one that honours `date_asc` (`displayedItems` is hardcoded newest-first
 * in `dashboardItems.js`). Navigation has to follow the eye, not the sort the
 * view throws away.
 *
 * `imageGroup` items are expanded in place and `job` items are dropped, so the
 * list is images only — a batch of 4 images from one job is 4 navigable steps,
 * not one.
 */
export function flattenGalleryImages(sortedGroupedEntries) {
    if (!Array.isArray(sortedGroupedEntries)) return [];
    const out = [];
    for (const [, items] of sortedGroupedEntries) {
        if (!Array.isArray(items)) continue;
        for (const item of items) {
            if (item?.type === 'image') {
                out.push(item);
            } else if (item?.type === 'imageGroup' && Array.isArray(item.images)) {
                for (const img of item.images) {
                    if (img) out.push(img);
                }
            }
        }
    }
    return out;
}

/**
 * Previous/next navigation for the gallery lightbox.
 *
 * The lightbox already knew how to navigate (`onNavigate(index)`, chevrons,
 * arrow keys, swipe) but was handed only one job's `siblingImages`, so every
 * ordinary single-image click got `images.length === 1` and the whole feature
 * was inert. This supplies the real list.
 *
 * The index is derived from the selected image's *identity* on every render
 * rather than held as a number. The gallery is infinitely scrolled, so if the
 * user opens an image, scrolls the grid to pull in another page, and then
 * presses next, a stored index would now point at a different image than it did
 * when the viewer opened. Recomputing keeps the cursor on the picture the user
 * is looking at.
 *
 * When the selected image is not in the list — it can happen if a filter
 * changed while the viewer was open, or the image came from somewhere the
 * grouped view does not carry — it degrades to a one-item list holding just
 * that image, so the viewer shows the right picture instead of silently
 * substituting whatever happens to sit at index 0.
 */
export function useLightboxNavigation({
    sortedGroupedEntries,
    selectedImage,
    hasMore = false,
    onLoadMore = null,
    isLoadingMore = false,
}) {
    const images = useMemo(
        () => flattenGalleryImages(sortedGroupedEntries),
        [sortedGroupedEntries],
    );

    const foundIndex = useMemo(() => {
        if (!selectedImage) return -1;
        const key = identityOf(selectedImage);
        if (!key) return -1;
        return images.findIndex((candidate) => identityOf(candidate) === key);
    }, [images, selectedImage]);

    // Degrade rather than substitute when the selected image isn't listed.
    // Memoised because `resolveTarget` depends on it, and an unmemoised
    // fallback array would give every consumer a new callback each render.
    const isListed = foundIndex >= 0;
    const navImages = useMemo(
        () => (isListed ? images : (selectedImage ? [selectedImage] : [])),
        [isListed, images, selectedImage],
    );
    const currentIndex = isListed ? foundIndex : 0;

    const canGoPrev = currentIndex > 0;
    const canGoNext = currentIndex < navImages.length - 1 || (hasMore && !isLoadingMore && !!onLoadMore);

    const resolveTarget = useCallback(
        (index) => {
            const target = navImages[index];
            if (!target) return null;
            // `siblingImages`/`associatedJob` are attached by the group cards so
            // the viewer can show which job produced the image. Carry them
            // across a navigation step instead of dropping them.
            return selectedImage?.siblingImages || selectedImage?.associatedJob
                ? {
                    ...target,
                    siblingImages: selectedImage.siblingImages,
                    associatedJob: selectedImage.associatedJob,
                }
                : target;
        },
        [navImages, selectedImage],
    );

    return {
        images: navImages,
        currentIndex,
        canGoPrev,
        canGoNext,
        isListed,
        hasMore,
        onLoadMore,
        isLoadingMore,
        resolveTarget,
    };
}
