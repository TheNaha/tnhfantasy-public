import { useEffect, useRef } from 'react';

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
           `invalidateQueries({ queryKey: ['gallery', filters] })` refetches *every
           page already loaded*, sequentially. With fifteen pages loaded that is
           fifteen requests for one finished job — and each one changes the list
           height as it lands, which moves the sentinel, which is most of what
           people mean by "a job update sets off the infinite scroll". On a phone,
           where pages accumulate fastest, it is fifteen round trips before the new
           image is even visible.

           The cursor runs newest-first, so the new image is on page 0. Scoping to
           it keeps the behaviour this hook exists for — the grid shows the new
           image — without the tail churn.

           `useJobsRealtime` already scopes its own completion invalidation the same
           way (`refetchPage: (_page, allPages) => _page === allPages[0]`). Two
           handlers fire on the same event, so the narrower rule has to be the one
           both use. */
        queryClient.invalidateQueries({
            queryKey: galleryQueryKey,
            refetchPage: (_page, allPages) => _page === allPages[0],
        });
    }, [
        lastCompletedJob,
        autoRefreshOnJobComplete,
        galleryQueryKey,
        queryClient,
    ]);
}

export default useGalleryAutoRefresh;
