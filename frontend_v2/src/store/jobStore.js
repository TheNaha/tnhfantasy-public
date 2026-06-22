import { create } from 'zustand';

const MAX_JOBS = 500;

const useJobStore = create((set, get) => ({
    jobs: {},

    updateJob: (jobId, data) => set((state) => {
        const jobs = { ...state.jobs };
        const hasExisting = jobId in jobs;
        // Extract only volatile delta state
        const volatileData = {
            progress: data.progress,
            overall_progress: data.overall_progress,
            status: data.status,
            message: data.message,
            queue_position: data.queue_position,
            provider_id: data.provider_id,
            metadata_: data.metadata_
        };
        
        jobs[jobId] = { ...(jobs[jobId] || {}), ...volatileData };
        if (!hasExisting && Object.keys(jobs).length > MAX_JOBS) {
            const keys = Object.keys(jobs);
            const toDelete = keys.slice(0, keys.length - MAX_JOBS);
            for (const key of toDelete) {
                delete jobs[key];
            }
        }
        return { jobs };
    }),

    removeJob: (jobId) => set((state) => {
        const newJobs = { ...state.jobs };
        delete newJobs[jobId];
        return { jobs: newJobs };
    }),

    getJob: (jobId) => {
        const job = get().jobs[jobId];
        return job ? { ...job } : undefined;
    },
}));

export default useJobStore;
