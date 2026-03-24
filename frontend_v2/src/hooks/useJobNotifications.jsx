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
            if (prevState.activeJobs.length > 0 && state.activeJobs.length === 0) {
                toast.success('All jobs completed! Queue is empty.', {
                    duration: 3000,
                    icon: '🎉',
                });
            }
            
            // ⚡ Bolt: Prevent O(N²) array lookups by pre-computing a Set of previously failed job IDs
            // This transforms the newFailedJobs check from O(N * M) to O(N + M) complexity.
            const prevFailedJobIds = new Set(
                prevState.jobs.filter(j => j.status === 'failed').map(j => j.id)
            );

            // Detect job failure
            const newFailedJobs = state.jobs.filter(job => 
                job.status === 'failed' && !prevFailedJobIds.has(job.id)
            );
            
            if (newFailedJobs.length > 0) {
                newFailedJobs.forEach(job => {
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
                });
            }
        });
        
        return unsubscribe;
    }, []);
}
