import { create } from 'zustand';
import * as ws from '../api/websocket';
import { jobsApi } from '../api';
import { filterActiveJobs } from '../utils/jobStatus';

function sortJobsByCreatedAt(jobs) {
    return [...jobs].sort((a, b) => {
        const dateA = new Date(a.created_at || 0);
        const dateB = new Date(b.created_at || 0);
        return dateB - dateA;
    });
}

function normalizeActiveJobs(jobs) {
    return sortJobsByCreatedAt(filterActiveJobs(jobs));
}

export const useJobStore = create((set, get) => ({
    jobs: [],
    
    lastCompletedJob: null,
    lastFailedJob: null,
    lastCancelledJob: null,
    isConnected: false,
    connectionError: null,

    setConnectionStatus: (isConnected, connectionError) => set({ isConnected, connectionError }),

    setJobs: (jobs) => {
        const jobMap = new Map();
        
        get().jobs.forEach(j => jobMap.set(j.id, j));
        
        jobs.forEach(j => {
            const existing = jobMap.get(j.id);
            jobMap.set(j.id, existing ? { ...existing, ...j } : j);
        });

        const activeJobs = normalizeActiveJobs(Array.from(jobMap.values()));
        set({ jobs: activeJobs });
    },

    updateJob: (jobId, updates) => {
        set((state) => {
            const mergedJobs = state.jobs.map((job) =>
                job.id === jobId ? { ...job, ...updates } : job
            );
            const activeJobs = normalizeActiveJobs(mergedJobs);
            return { jobs: activeJobs };
        });
    },

    processMessage: (data) => {
        const { setJobs, updateJob } = get();

        if (data.jobs) {
            setJobs(data.jobs);
        }

        if (data.type && data.data?.job) {
            const job = data.data.job;
            const eventType = data.type;

            if (eventType === 'job.created') {
                set((state) => {
                    const exists = state.jobs.some(j => j.id === job.id);
                    if (exists) {
                        const mergedJobs = state.jobs.map(j => j.id === job.id ? { ...j, ...job } : j);
                        const activeJobs = normalizeActiveJobs(mergedJobs);
                        return { jobs: activeJobs };
                    }
                    const activeJobs = normalizeActiveJobs([job, ...state.jobs]);
                    return { jobs: activeJobs };
                });
            } else if (eventType === 'job.progress' || eventType === 'job.updated' || eventType === 'job.post_processing') {
                set((state) => {
                    const exists = state.jobs.some(j => j.id === job.id);
                    const mergedJobs = exists
                        ? state.jobs.map(j => j.id === job.id ? { ...j, ...job } : j)
                        : [job, ...state.jobs];
                    const activeJobs = normalizeActiveJobs(mergedJobs);
                    return { jobs: activeJobs };
                });
            } else if (eventType === 'job.completed' || eventType === 'job.failed' || eventType === 'job.cancelled') {
                set((state) => {
                    const remainingActiveJobs = state.jobs.filter(j => j.id !== job.id);
                    return {
                        jobs: remainingActiveJobs,
                        lastCompletedJob: eventType === 'job.completed' ? job : state.lastCompletedJob,
                        lastFailedJob: eventType === 'job.failed' ? job : state.lastFailedJob,
                        lastCancelledJob: eventType === 'job.cancelled' ? job : state.lastCancelledJob,
                    };
                });
            }
        }

        if (data.type === 'job_update' && data.job) {
            updateJob(data.job.id, data.job);
        }
    },

    fetchJobs: async () => {
        try {
            const data = await jobsApi.list();
            get().setJobs(filterActiveJobs(data.jobs || []));
            return data;
        } catch (error) {
            console.error('Failed to fetch jobs:', error);
            throw error;
        }
    },

    cancelJob: async (jobId) => {
        try {
            const result = await ws.cancelJob(jobId);
            console.log('[JobStore] Cancel job result:', result);

            if (result.status === 'cancelled' || result.status === 'cancellation_requested') {
                set((state) => ({
                    jobs: state.jobs.filter(j => j.id !== jobId)
                }));
            }

            return result;
        } catch (error) {
            console.error('Failed to cancel job:', error);
            throw error;
        }
    },

    clearJobs: async () => {
        const previousJobs = get().jobs;
        set({ jobs: [] });

        try {
            await jobsApi.clear();
        } catch (error) {
            console.error('Failed to clear jobs:', error);
            set({ jobs: previousJobs });
            throw error;
        }
    },

    deleteJob: async (jobId) => {
        const previousJobs = get().jobs;
        set((state) => ({
            jobs: state.jobs.filter(j => j.id !== jobId),
        }));

        try {
            await jobsApi.delete(jobId);
        } catch (error) {
            console.error('Failed to delete job:', error);
            set({ jobs: previousJobs });
            throw error;
        }
    },

    retryJob: async (jobId) => {
        try {
            const result = await jobsApi.retry(jobId);
            await get().fetchJobs();
            return result;
        } catch (error) {
            console.error('Failed to retry job:', error);
            throw error;
        }
    },

    createJobOptimistic: async (workflow, metadata, generateFn) => {
        const tempId = `temp-${Date.now()}`;
        const tempJob = {
            id: tempId,
            status: 'submitting',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            metadata: metadata,
            workflow: workflow,
            isOptimistic: true,
            progress: 0,
            overall_progress: 0,
            message: 'Submitting to queue...',
            error: null,
            outputs: []
        };

        set((state) => ({
            jobs: [tempJob, ...state.jobs]
        }));

        try {
            const response = await generateFn();
            const realJob = response?.job || response;

            if (realJob && realJob.id) {
                set((state) => {
                    const existsInActive = state.jobs.some(j => j.id === realJob.id);
                    
                    let newActiveJobs;
                    if (existsInActive) {
                        newActiveJobs = state.jobs.map(j => j.id === realJob.id ? { ...j, ...realJob, isOptimistic: false } : j)
                                                      .filter(j => j.id !== tempId);
                    } else {
                        newActiveJobs = state.jobs.map(j => j.id === tempId ? { ...realJob, isOptimistic: false } : j);
                    }

                    return {
                        jobs: normalizeActiveJobs(newActiveJobs)
                    };
                });
                return realJob;
            } else {
                throw new Error('Invalid response from server');
            }
        } catch (error) {
            console.error('Failed to create job:', error);
            set((state) => ({
                jobs: state.jobs.filter(j => j.id !== tempId)
            }));
            throw error;
        }
    }
}));
