import { useEffect } from 'react';
import toast from 'react-hot-toast';
import { useJobStore } from '../store/jobStore';

/**
 * Global job notifications hook
 * Shows toast notifications for job completion across all pages
 */
export function useJobNotifications() {
    useEffect(() => {
        // Subscribe to job store changes
        const unsubscribe = useJobStore.subscribe((state, prevState) => {
            // Detect job completion
            if (state.lastCompletedJob !== prevState.lastCompletedJob && state.lastCompletedJob) {
                const job = state.lastCompletedJob;
                
                // Show success toast with job details
                toast.success(
                    <div>
                        <strong>Image generated!</strong>
                        <br />
                        <span className="text-sm opacity-80">
                            {job.metadata_?.prompt?.substring(0, 50) || 'Job completed'}
                            {job.metadata_?.prompt?.length > 50 ? '...' : ''}
                        </span>
                    </div>,
                    {
                        duration: 4000,
                        icon: '✨',
                    }
                );
            }
            
            // Detect queue empty (all active jobs done)
            if (prevState.activeJobs.length > 0 && state.jobs.length === 0) {
                toast.success('All jobs completed! Queue is empty.', {
                    duration: 3000,
                    icon: '🎉',
                });
            }

            // Detect job failure from explicit store marker.
            if (state.lastFailedJob !== prevState.lastFailedJob && state.lastFailedJob) {
                const job = state.lastFailedJob;
                toast.error(
                    <div>
                        <strong>Job failed</strong>
                        <br />
                        <span className="text-sm opacity-80">
                            {job.error || 'Unknown error'}
                        </span>
                    </div>,
                    {
                        duration: 5000,
                    }
                );
            }

            if (state.lastCancelledJob !== prevState.lastCancelledJob && state.lastCancelledJob) {
                toast('Job cancelled', {
                    icon: '🛑',
                    duration: 3000,
                });
            }
        });
        
        return unsubscribe;
    }, []);
}
