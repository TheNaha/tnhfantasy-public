import { useEffect, useRef } from 'react';

import { refetchNewestGalleryPage } from './useGallery';

export function useGalleryAutoRefresh({
    lastCompletedJob,
    autoRefreshOnJobComplete,
    queryClient,
    galleryQueryKey = ['gallery'],
}) {
    const lastCompletedJobRef = useRef(null);

    useEffect(() => {
        if (!lastCompletedJob || !Array.isArray(lastCompletedJob.outputs) || lastCompletedJob.outputs.length === 0) {
            return;
        }

        if (lastCompletedJobRef.current === lastCompletedJob.id) {
            return;
        }

        // Checked before the ref is spent: the old order burned the id even
        // with the setting off, so turning auto-refresh on later could never
        // refresh for a job that had already completed.
        if (!autoRefreshOnJobComplete) {
            return;
        }

        lastCompletedJobRef.current = lastCompletedJob.id;

        /* Refetch ONLY the newest page.

           `useGallery` is a `useInfiniteQuery`, so a bare
           `invalidateQueries({ queryKey: ['gallery'] })` refetches *every* page
           already loaded, sequentially. With fifteen pages loaded that is fifteen
           requests for one finished job — and each one changes the list height as
           it lands, which moves the sentinel, which is most of what people mean
           by "a job update sets off the infinite scroll". On a phone, where pages
           accumulate fastest, it is fifteen round trips before the new image is
           even visible.

           The cursor runs newest-first, so the new image is on page 0. Scoping to
           it keeps the behaviour this hook exists for — the grid shows the new
           image — without the tail churn.

           This used to be `invalidateQueries({ queryKey, refetchPage: (page, all)
           => page === all[0] })`, and `refetchPage` is not a react-query v5 option:
           `InvalidateQueryFilters` is `QueryFilters` and nothing else in
           `@tanstack/query-core@5.90.11`, so the filter was carried and ignored
           and the full-library refetch it claimed to prevent was what actually
           happened. `refetchNewestGalleryPage` does the work for real; see its
           docblock. `useJobsRealtime.jsx` used to make the same call with the same
           no-op, and now shares this one rule. */
        // Only the bare root is the whole library, which is the case worth
        // scoping. A caller that narrowed the key to one listing is asking about
        // that listing alone, and a plain invalidation is the right answer.
        if (galleryQueryKey?.length === 1 && galleryQueryKey[0] === 'gallery') {
            void refetchNewestGalleryPage(queryClient);
            return;
        }
        queryClient.invalidateQueries({ queryKey: galleryQueryKey });
    }, [
        lastCompletedJob,
        autoRefreshOnJobComplete,
        galleryQueryKey,
        queryClient,
    ]);
}

export default useGalleryAutoRefresh;