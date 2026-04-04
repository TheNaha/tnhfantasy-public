import { useEffect, useRef } from 'react';
import toast from 'react-hot-toast';

export function useGalleryAutoRefresh({
    lastCompletedJob,
    autoRefreshOnJobComplete,
    queryClient,
    toastSuccessDuration,
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
        toast.success('🎉 Generation complete! Gallery updated.', {
            duration: toastSuccessDuration,
        });
    }, [
        lastCompletedJob,
        autoRefreshOnJobComplete,
        galleryQueryKey,
        queryClient,
        toastSuccessDuration,
    ]);
}

export default useGalleryAutoRefresh;
