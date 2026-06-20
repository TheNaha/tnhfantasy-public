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

        lastCompletedJobRef.current = lastCompletedJob.id;

        if (!autoRefreshOnJobComplete) {
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
