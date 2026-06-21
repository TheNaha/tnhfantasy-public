import { useState, useCallback } from 'react';
import { jobsApi } from '../api/jobs';

export function useDashboardModals({ queryClient, filters }) {
    const [selectedJobId, setSelectedJobId] = useState(null);
    const [showCollectionsPanel, setShowCollectionsPanel] = useState(false);
    const [showSelectCollection, setShowSelectCollection] = useState(false);
    const [showComparison, setShowComparison] = useState(false);

    const deleteJob = useCallback(async (jobId) => {
        try {
            await jobsApi.delete(jobId);
            queryClient.invalidateQueries({ queryKey: ['jobs'] });
            queryClient.invalidateQueries({ queryKey: ['gallery', filters], exact: false });
        } catch (error) {
            console.error('Failed to delete job:', error);
            throw error;
        }
    }, [queryClient, filters]);

    const retryJob = useCallback(async (jobId) => {
        try {
            const result = await jobsApi.retry(jobId);
            queryClient.invalidateQueries({ queryKey: ['gallery', filters], exact: false });
            return result;
        } catch (error) {
            console.error('Failed to retry job:', error);
            throw error;
        }
    }, [queryClient, filters]);

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
