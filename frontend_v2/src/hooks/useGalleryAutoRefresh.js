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

        queryClient.invalidateQueries({ queryKey: galleryQueryKey });
    }, [
        lastCompletedJob,
        autoRefreshOnJobComplete,
        galleryQueryKey,
        queryClient,
    ]);
}

export default useGalleryAutoRefresh;
