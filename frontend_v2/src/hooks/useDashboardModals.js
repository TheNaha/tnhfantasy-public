import { useState, useCallback } from 'react';
import toast from 'react-hot-toast';
import { jobsApi } from '../api/jobs';
import { useJobStore } from '../store/jobStore';

export function useDashboardModals({ queryClient, filters }) {
    const [confirmModal, setConfirmModal] = useState({
        isOpen: false,
        title: '',
        message: '',
        isDangerous: false,
        confirmText: 'Confirm',
        onConfirm: () => { }
    });

    const [selectedJobId, setSelectedJobId] = useState(null);
    const [showCollectionsPanel, setShowCollectionsPanel] = useState(false);
    const [showSelectCollection, setShowSelectCollection] = useState(false);
    const [showStatsPanel, setShowStatsPanel] = useState(false);
    const [showComparison, setShowComparison] = useState(false);

    const deleteJob = useCallback(async (jobId) => {
        try {
            await jobsApi.delete(jobId);
            useJobStore.setState(state => ({
                jobs: state.jobs.filter(j => j.id !== jobId)
            }));
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

    const handleJobDelete = useCallback((jobId) => {
        setConfirmModal({
            isOpen: true,
            title: 'Remove Job',
            message: 'Are you sure you want to remove this job from history? The generated images will remain in your gallery.',
            isDangerous: true,
            confirmText: 'Remove',
            onConfirm: async () => {
                try {
                    await deleteJob(jobId);
                    toast.success('Job removed from history');
                } catch (e) {
                    toast.error(e.message || 'Failed to remove job');
                }
            }
        });
    }, [deleteJob]);

    const handleJobClick = useCallback((job) => {
        const jobId = typeof job === 'string' ? job : job?.id;
        if (jobId) setSelectedJobId(jobId);
    }, []);

    const handleJobDetailsClose = useCallback(() => setSelectedJobId(null), []);

    return {
        confirmModal,
        setConfirmModal,
        selectedJobId,
        setSelectedJobId,
        showCollectionsPanel,
        setShowCollectionsPanel,
        showSelectCollection,
        setShowSelectCollection,
        showStatsPanel,
        setShowStatsPanel,
        showComparison,
        setShowComparison,
        deleteJob,
        retryJob,
        handleJobDelete,
        handleJobClick,
        handleJobDetailsClose,
    };
}
