import { create } from 'zustand';

const useJobStore = create((set, get) => ({
    jobs: {},
    
    updateJob: (jobId, data) => set((state) => ({
        jobs: {
            ...state.jobs,
            [jobId]: {
                ...(state.jobs[jobId] || {}),
                ...data
            }
        }
    })),
    
    removeJob: (jobId) => set((state) => {
        const newJobs = { ...state.jobs };
        delete newJobs[jobId];
        return { jobs: newJobs };
    }),
    
    getJob: (jobId) => get().jobs[jobId],
}));

export default useJobStore;
