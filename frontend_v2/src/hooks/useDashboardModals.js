import { useState, useCallback } from 'react';
import { jobsApi } from '../api/jobs';
import { refetchNewestGalleryPage } from './useGallery';

export function useDashboardModals({ queryClient }) {
    const [selectedJobId, setSelectedJobId] = useState(null);
    const [showCollectionsPanel, setShowCollectionsPanel] = useState(false);
    const [showSelectCollection, setShowSelectCollection] = useState(false);
    const [showComparison, setShowComparison] = useState(false);

    const deleteJob = useCallback(async (jobId) => {
        try {
            await jobsApi.delete(jobId);
            queryClient.invalidateQueries({ queryKey: ['jobs'] });
            // A DELETION, not an addition: the item is gone, so the whole
            // listing has to be re-read. But a full invalidation of an
            // infinite query refetches EVERY loaded page, one after the
            // other - and a deletion removes one item, usually from the
            // first page.
            await refetchNewestGalleryPage(queryClient);
        } catch (error) {
            console.error('Failed to delete job:', error);
            throw error;
        }
    }, [queryClient]);

    const retryJob = useCallback(async (jobId) => {
        try {
            const result = await jobsApi.retry(jobId);
            // A retried job is re-enqueued — refresh the job cache, the active
            // list and the queue panel, not just the gallery.
            queryClient.invalidateQueries({ queryKey: ['jobs'] });
            // A DELETION, not an addition: the item is gone, so the whole
            // listing has to be re-read. But a full invalidation of an
            // infinite query refetches EVERY loaded page, one after the
            // other - and a deletion removes one item, usually from the
            // first page.
            await refetchNewestGalleryPage(queryClient);
            return result;
        } catch (error) {
            console.error('Failed to retry job:', error);
            throw error;
        }
    }, [queryClient]);

    const handleJobClick = useCallback((job) => {
        const jobId = typeof job === 'string' ? job : job?.id;
        if (jobId) setSelectedJobId(jobId);
    }, []);

    const handleJobDetailsClose = useCallback(() => setSelectedJobId(null), []);

    return {
        selectedJobId,
        setSelectedJobId,
        showCollectionsPanel,
        setShowCollectionsPanel,
        showSelectCollection,
        setShowSelectCollection,
        showComparison,
        setShowComparison,
        deleteJob,
        retryJob,
        handleJobClick,
        handleJobDetailsClose,
    };
}
