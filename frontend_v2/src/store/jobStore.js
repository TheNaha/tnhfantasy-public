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
    activeJobs: [],
    lastCompletedJob: null,  // Track the most recently completed job for gallery auto-refresh
    lastFailedJob: null,
    lastCancelledJob: null,
    isConnected: false,
    connectionError: null,
    _wsInitialized: false,
    _unsubscribers: [],

    setJobs: (jobs) => {
        // Only active, websocket-owned jobs belong in this store.
        const jobMap = new Map();
        
        get().jobs.forEach(j => jobMap.set(j.id, j));
        
        jobs.forEach(j => {
            const existing = jobMap.get(j.id);
            jobMap.set(j.id, existing ? { ...existing, ...j } : j);
        });

        const activeJobs = normalizeActiveJobs(Array.from(jobMap.values()));
        set({ jobs: activeJobs, activeJobs });
    },

    updateJob: (jobId, updates) => {
        set((state) => {
            const mergedJobs = state.jobs.map((job) =>
                job.id === jobId ? { ...job, ...updates } : job
            );
            const activeJobs = normalizeActiveJobs(mergedJobs);
            return { jobs: activeJobs, activeJobs };
        });
    },

    // Handle WebSocket message processing (same logic as SSE)
    _processMessage: (data) => {
        const { setJobs, updateJob } = get();

        // V1 style: full job list
        if (data.jobs) {
            setJobs(data.jobs);
        }

        // V2 style: event-based updates
        // Backend sends: { type: "job.progress", data: { job: {...} }, timestamp: "..." }
        if (data.type && data.data?.job) {
            const job = data.data.job;
            const eventType = data.type;

            if (eventType === 'job.created') {
                // Add new job to list, but only if it doesn't already exist
                // This prevents duplicates when fetchJobs also returns the same job
                set((state) => {
                    const exists = state.jobs.some(j => j.id === job.id);
                    if (exists) {
                        const mergedJobs = state.jobs.map(j => j.id === job.id ? { ...j, ...job } : j);
                        const activeJobs = normalizeActiveJobs(mergedJobs);
                        return {
                            jobs: activeJobs,
                            activeJobs,
                        };
                    }
                    const activeJobs = normalizeActiveJobs([job, ...state.jobs]);
                    return {
                        jobs: activeJobs,
                        activeJobs,
                    };
                });
            } else if (eventType === 'job.progress' || eventType === 'job.updated' || eventType === 'job.post_processing') {
                set((state) => {
                    const exists = state.jobs.some(j => j.id === job.id);
                    const mergedJobs = exists
                        ? state.jobs.map(j => j.id === job.id ? { ...j, ...job } : j)
                        : [job, ...state.jobs];
                    const activeJobs = normalizeActiveJobs(mergedJobs);
                    if (exists) {
                        return { jobs: activeJobs, activeJobs };
                    } else {
                        return { jobs: activeJobs, activeJobs };
                    }
                });
            } else if (eventType === 'job.completed' || eventType === 'job.failed' || eventType === 'job.cancelled') {
                set((state) => {
                    const remainingActiveJobs = state.activeJobs.filter(j => j.id !== job.id);
                    return {
                        jobs: remainingActiveJobs,
                        activeJobs: remainingActiveJobs,
                        lastCompletedJob: eventType === 'job.completed' ? job : state.lastCompletedJob,
                        lastFailedJob: eventType === 'job.failed' ? job : state.lastFailedJob,
                        lastCancelledJob: eventType === 'job.cancelled' ? job : state.lastCancelledJob,
                    };
                });
            }
        }

        // Legacy V1 style: individual job updates (keep for backwards compatibility)
        if (data.type === 'job_update' && data.job) {
            updateJob(data.job.id, data.job);
        }
    },

    // Initialize WebSocket connection
    connect: async () => {
        const { _wsInitialized, _unsubscribers } = get();

        // Only initialize once
        if (_wsInitialized) {
            return;
        }

        try {
            // Connect to WebSocket server
            await ws.connect();

            // Subscribe to job events
            await ws.subscribe('job');

            // Listen for connection status changes
            const unsubConnection = ws.on('connection', (data) => {
                set({
                    isConnected: data.connected,
                    connectionError: data.error || null
                });

                if (data.connected) {
                    console.log('[JobStore] WebSocket connected');
                } else {
                    console.log('[JobStore] WebSocket disconnected:', data.reason || data.error);
                }
            });

            // Listen for job events
            const eventTypes = [
                ws.EventTypes.JOB_CREATED,
                ws.EventTypes.JOB_UPDATED,
                ws.EventTypes.JOB_PROGRESS,
                ws.EventTypes.JOB_POST_PROCESSING,
                ws.EventTypes.JOB_COMPLETED,
                ws.EventTypes.JOB_FAILED,
                ws.EventTypes.JOB_CANCELLED,
            ];

            const unsubscribers = eventTypes.map(eventType =>
                ws.on(eventType, (data) => {
                    get()._processMessage(data);
                })
            );

            // Track all unsubscribers for cleanup
            set({
                _wsInitialized: true,
                isConnected: ws.getConnectionStatus(),
                _unsubscribers: [unsubConnection, ...unsubscribers]
            });

        } catch (error) {
            console.error('[JobStore] WebSocket connection failed:', error);
            set({ connectionError: error.message });
        }
    },

    // Force reconnect WebSocket (useful after page visibility change)
    reconnect: async () => {
        console.log('[JobStore] Force reconnecting WebSocket...');
        ws.disconnect();
        set({ isConnected: false, _wsInitialized: false });

        // Small delay to ensure clean disconnect
        await new Promise(resolve => setTimeout(resolve, 100));
        await get().connect();
    },

    disconnect: () => {
        const { _unsubscribers } = get();

        // Clean up listeners
        _unsubscribers.forEach(unsub => unsub && unsub());

        ws.unsubscribe('job');
        ws.disconnect();
        set({ isConnected: false, _wsInitialized: false, _unsubscribers: [] });
    },

    // API methods
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

    // Cancel a running or pending job
    cancelJob: async (jobId) => {
        try {
            const result = await ws.cancelJob(jobId);
            console.log('[JobStore] Cancel job result:', result);

            // Optimistically update the job status
            if (result.status === 'cancelled' || result.status === 'cancellation_requested') {
                set((state) => ({
                    jobs: state.jobs.filter(j => j.id !== jobId),
                    activeJobs: state.activeJobs.filter(j => j.id !== jobId)
                }));
            }

            return result;
        } catch (error) {
            console.error('Failed to cancel job:', error);
            throw error;
        }
    },

    // Optimistic clear - clears immediately, rollback on error
    clearJobs: async () => {
        // Save current state for rollback
        const previousJobs = get().jobs;
        const previousActiveJobs = get().activeJobs;

        // Optimistic update - clear immediately
        set({ jobs: [], activeJobs: [] });

        try {
            await jobsApi.clear();
            // Success - state already updated
        } catch (error) {
            console.error('Failed to clear jobs:', error);
            // Rollback on failure
            set({ jobs: previousJobs, activeJobs: previousActiveJobs });
            throw error;
        }
    },

    // Optimistic delete - removes immediately, rollback on error
    deleteJob: async (jobId) => {
        // Save current state for rollback
        const previousJobs = get().jobs;
        const previousActiveJobs = get().activeJobs;

        // Optimistic update - remove immediately
        set((state) => ({
            jobs: state.jobs.filter(j => j.id !== jobId),
            activeJobs: state.activeJobs.filter(j => j.id !== jobId),
        }));

        try {
            await jobsApi.delete(jobId);
            // Success - state already updated
        } catch (error) {
            console.error('Failed to delete job:', error);
            // Rollback on failure
            set({ jobs: previousJobs, activeJobs: previousActiveJobs });
            throw error;
        }
    },

    // Retry a failed job - creates new job with same workflow
    retryJob: async (jobId) => {
        try {
            const result = await jobsApi.retry(jobId);
            // Fetch jobs to get the new job in the list
            await get().fetchJobs();
            return result;
        } catch (error) {
            console.error('Failed to retry job:', error);
            throw error;
        }
    },

    // Optimistic job creation - shows immediately, replaces with real job on success
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

        // Add immediately for instant feedback
        set((state) => ({
            jobs: [tempJob, ...state.jobs],
            activeJobs: [tempJob, ...state.activeJobs]
        }));

        try {
            // Use the provided generate function or default API
            const response = await generateFn();
            const realJob = response?.job || response;

            if (realJob && realJob.id) {
                // Check if the real job already exists (from WebSocket race)
                set((state) => {
                    const existsInActive = state.activeJobs.some(j => j.id === realJob.id);

                    // If it exists, we should remove the temp job and update the existing one if needed
                    // If it doesn't exist, we replace the temp job with the real one
                    
                    let newActiveJobs;
                    if (existsInActive) {
                        newActiveJobs = state.activeJobs.map(j => j.id === realJob.id ? { ...j, ...realJob, isOptimistic: false } : j)
                                                      .filter(j => j.id !== tempId);
                    } else {
                        newActiveJobs = state.activeJobs.map(j => j.id === tempId ? { ...realJob, isOptimistic: false } : j);
                    }

                    const normalizedActiveJobs = normalizeActiveJobs(newActiveJobs);

                    return {
                        jobs: normalizedActiveJobs,
                        activeJobs: normalizedActiveJobs
                    };
                });
                return realJob;
            } else {
                throw new Error('Invalid response from server');
            }
        } catch (error) {
            console.error('Failed to create job:', error);
            // Rollback on failure - remove temp job
            set((state) => ({
                jobs: state.jobs.filter(j => j.id !== tempId),
                activeJobs: state.activeJobs.filter(j => j.id !== tempId)
            }));
            throw error;
        }
    }
}));

// Handle page visibility changes (mobile tab switching, app backgrounding)
if (typeof document !== 'undefined') {
    // Detect mobile via touch support
    const isMobile = () => 'ontouchstart' in window || navigator.maxTouchPoints > 0;

    // Mobile polling fallback - polls when WebSocket may be unreliable
    let mobilePollingInterval = null;
    let lastEventTime = Date.now();
    let consecutiveFailures = 0;
    const MAX_FAILURES_BEFORE_NOTIFY = 3;
    let connectionToastId = null;  // Track toast ID for dismissal

    // Track when we receive WebSocket events to detect stale connections
    const markEventReceived = () => {
        lastEventTime = Date.now();
        consecutiveFailures = 0;  // Reset on successful event
    };

    // Start mobile polling fallback
    const startMobilePolling = () => {
        if (mobilePollingInterval) return; // Already polling

        console.log('[JobStore] Starting mobile polling fallback...');
        consecutiveFailures = 0;  // Reset failures when starting
        
        mobilePollingInterval = setInterval(async () => {
            const store = useJobStore.getState();

            // Check if we have active jobs that need updates
            const hasActiveJobs = store.activeJobs.length > 0;

            // Check if WebSocket events are flowing (received in last 5 seconds)
            const timeSinceLastEvent = Date.now() - lastEventTime;
            const wsEventsFlowing = timeSinceLastEvent < 5000;

            if (!hasActiveJobs) {
                // No active jobs, stop polling
                console.log('[JobStore] No active jobs, stopping mobile polling');
                stopMobilePolling();
                return;
            }

            if (wsEventsFlowing && store.isConnected) {
                // WebSocket is working, we can stop polling
                console.log('[JobStore] WebSocket events flowing, stopping mobile polling');
                stopMobilePolling();
                return;
            }

            // Poll for job updates
            console.log('[JobStore] Mobile polling: fetching jobs...');
            try {
                await store.fetchJobs();
                consecutiveFailures = 0;  // Reset on success
            } catch (e) {
                console.error('[JobStore] Mobile polling fetch failed:', e);
                consecutiveFailures++;
                
                if (consecutiveFailures >= MAX_FAILURES_BEFORE_NOTIFY) {
                    // Show toast notification for connection issues
                    import('react-hot-toast').then(({ default: toast }) => {
                        connectionToastId = toast.error('Connection issues - trying to reconnect...', {
                            id: 'mobile-connection-error',  // Prevent duplicate toasts
                            duration: 4000,
                        });
                    });
                    consecutiveFailures = 0;  // Reset after notification
                }
            }
        }, 2000); // Poll every 2 seconds
    };

    // Stop mobile polling
    const stopMobilePolling = () => {
        if (mobilePollingInterval) {
            clearInterval(mobilePollingInterval);
            mobilePollingInterval = null;
            consecutiveFailures = 0;
            console.log('[JobStore] Mobile polling stopped');
        }
    };
    
    // Dismiss connection toast on navigation (fixes toast persistence bug)
    const dismissConnectionToast = () => {
        if (connectionToastId) {
            import('react-hot-toast').then(({ default: toast }) => {
                toast.dismiss('mobile-connection-error');
            });
            connectionToastId = null;
        }
    };

    // Hook into jobStore to track WebSocket event reception
    useJobStore.subscribe((state, prevState) => {
        // If jobs changed, mark event received (indicates WebSocket is working)
        if (state.jobs !== prevState.jobs) {
            markEventReceived();
        }
    });

    document.addEventListener('visibilitychange', () => {
        const store = useJobStore.getState();
        if (document.visibilityState === 'visible') {
            dismissConnectionToast();
            // Page became visible - ensure WebSocket is connected and fetch fresh data
            console.log('[JobStore] Page became visible, checking WebSocket connection...');

            // On mobile, always force reconnect because mobile browsers may kill connections
            if (isMobile()) {
                console.log('[JobStore] Mobile detected, forcing WebSocket reconnect...');
                store.reconnect();

                // Start polling fallback for mobile - will auto-stop when WS works
                if (store.activeJobs.length > 0) {
                    startMobilePolling();
                }
            } else if (!store.isConnected) {
                store.connect();
            }

            // Always fetch fresh jobs when page becomes visible
            store.fetchJobs().catch(console.error);
        } else {
            // Page hidden - stop polling to save battery
            stopMobilePolling();
        }
    });

    // Also handle online/offline events for network recovery
    window.addEventListener('online', () => {
        console.log('[JobStore] Network online, reconnecting WebSocket...');
        const store = useJobStore.getState();
        dismissConnectionToast();
        store.reconnect();
        store.fetchJobs().catch(console.error);

        // Start polling if on mobile with active jobs
        if (isMobile() && store.activeJobs.length > 0) {
            startMobilePolling();
        }
    });
}
