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

const browserLifecycleState = {
    initialized: false,
    mobilePollingInterval: null,
    lastEventTime: Date.now(),
    lastPollingFetchStarted: 0,
    consecutiveFailures: 0,
    connectionToastId: null,
    unsubscribeStore: null,
    onVisibilityChange: null,
    onOnline: null,
    onOffline: null,
    stopMobilePolling: null,
    dismissConnectionToast: null,
};

export const useJobStore = create((set, get) => ({
    jobs: [],
    activeJobs: [],
    lastCompletedJob: null,  // Track the most recently completed job for gallery auto-refresh
    lastFailedJob: null,
    lastCancelledJob: null,
    isConnected: false,
    connectionError: null,
    _wsInitialized: false,
    _connectPromise: null,
    _unsubscribers: [],
    _browserLifecycleInitialized: false,

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
        const { _wsInitialized, _connectPromise } = get();

        // Only initialize once
        if (_wsInitialized) {
            return;
        }

        if (_connectPromise) {
            return _connectPromise;
        }

        let connectPromise;
        connectPromise = (async () => {
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
            } finally {
                set((state) => (
                    state._connectPromise === connectPromise
                        ? { _connectPromise: null }
                        : {}
                ));
            }
        })();

        set({ _connectPromise: connectPromise });
        return connectPromise;
    },

    // Force reconnect WebSocket (useful after page visibility change)
    reconnect: async () => {
        console.log('[JobStore] Force reconnecting WebSocket...');
        ws.disconnect();
        set({ isConnected: false, _wsInitialized: false, _connectPromise: null });

        // Small delay to ensure clean disconnect
        await new Promise(resolve => setTimeout(resolve, 100));
        await get().connect();
    },

    disconnect: () => {
        get().teardownBrowserLifecycle();
        const { _unsubscribers } = get();

        // Clean up listeners
        _unsubscribers.forEach(unsub => unsub && unsub());

        ws.unsubscribe('job');
        ws.disconnect();
        set({ isConnected: false, _wsInitialized: false, _connectPromise: null, _unsubscribers: [] });
    },

    setupBrowserLifecycle: () => {
        if (browserLifecycleState.initialized) {
            return;
        }
        if (typeof window === 'undefined' || typeof document === 'undefined') {
            return;
        }

        const isMobile = () => 'ontouchstart' in window || navigator.maxTouchPoints > 0;

        const markEventReceived = () => {
            browserLifecycleState.lastEventTime = Date.now();
            browserLifecycleState.consecutiveFailures = 0;
        };

        const dismissConnectionToast = () => {
            if (!browserLifecycleState.connectionToastId) {
                return;
            }

            import('react-hot-toast').then(({ default: toast }) => {
                toast.dismiss('mobile-connection-error');
            });
            browserLifecycleState.connectionToastId = null;
        };

        const stopMobilePolling = () => {
            if (browserLifecycleState.mobilePollingInterval) {
                clearInterval(browserLifecycleState.mobilePollingInterval);
                browserLifecycleState.mobilePollingInterval = null;
                browserLifecycleState.consecutiveFailures = 0;
                console.log('[JobStore] Mobile polling stopped');
            }
        };

        const startMobilePolling = () => {
            if (browserLifecycleState.mobilePollingInterval) {
                return;
            }

            console.log('[JobStore] Starting mobile polling fallback...');
            browserLifecycleState.consecutiveFailures = 0;

            browserLifecycleState.mobilePollingInterval = setInterval(async () => {
                const store = useJobStore.getState();
                const hasActiveJobs = store.activeJobs.length > 0;
                const wsEventsFlowing = Date.now() - browserLifecycleState.lastEventTime < 5000;

                if (!hasActiveJobs) {
                    console.log('[JobStore] No active jobs, stopping mobile polling');
                    stopMobilePolling();
                    return;
                }

                if (wsEventsFlowing && store.isConnected) {
                    console.log('[JobStore] WebSocket events flowing, stopping mobile polling');
                    stopMobilePolling();
                    return;
                }

                console.log('[JobStore] Mobile polling: fetching jobs...');
                try {
                    const fetchStartedAt = Date.now();
                    browserLifecycleState.lastPollingFetchStarted = fetchStartedAt;
                    await store.fetchJobs({ skipIfEventAfter: fetchStartedAt });
                    browserLifecycleState.consecutiveFailures = 0;
                } catch (e) {
                    console.error('[JobStore] Mobile polling fetch failed:', e);
                    browserLifecycleState.consecutiveFailures += 1;

                    if (browserLifecycleState.consecutiveFailures >= 3) {
                        import('react-hot-toast').then(({ default: toast }) => {
                            browserLifecycleState.connectionToastId = toast.error('Connection issues - trying to reconnect...', {
                                id: 'mobile-connection-error',
                                duration: 4000,
                            });
                        });
                        browserLifecycleState.consecutiveFailures = 0;
                    }
                }
            }, 2000);
        };

        browserLifecycleState.unsubscribeStore = useJobStore.subscribe((state, prevState) => {
            if (state.jobs !== prevState.jobs) {
                markEventReceived();
            }
        });

        browserLifecycleState.onVisibilityChange = () => {
            const store = useJobStore.getState();

            if (document.visibilityState === 'visible') {
                dismissConnectionToast();
                console.log('[JobStore] Page became visible, checking WebSocket connection...');

                if (isMobile()) {
                    console.log('[JobStore] Mobile detected, forcing WebSocket reconnect...');
                    store.reconnect();

                    if (store.activeJobs.length > 0) {
                        startMobilePolling();
                    }
                } else if (!store.isConnected) {
                    store.connect();
                }

                const fetchStartedAt = Date.now();
                store.fetchJobs({ skipIfEventAfter: fetchStartedAt }).catch(console.error);
            } else {
                stopMobilePolling();
            }
        };

        browserLifecycleState.onOnline = () => {
            console.log('[JobStore] Network online, reconnecting WebSocket...');
            const store = useJobStore.getState();
            dismissConnectionToast();
            store.reconnect();
            const fetchStartedAt = Date.now();
            store.fetchJobs({ skipIfEventAfter: fetchStartedAt }).catch(console.error);

            if (isMobile() && store.activeJobs.length > 0) {
                startMobilePolling();
            }
        };

        browserLifecycleState.onOffline = () => {
            console.log('[JobStore] Network offline, stopping mobile polling');
            stopMobilePolling();
        };

        document.addEventListener('visibilitychange', browserLifecycleState.onVisibilityChange);
        window.addEventListener('online', browserLifecycleState.onOnline);
        window.addEventListener('offline', browserLifecycleState.onOffline);

        browserLifecycleState.stopMobilePolling = stopMobilePolling;
        browserLifecycleState.dismissConnectionToast = dismissConnectionToast;
        browserLifecycleState.lastEventTime = Date.now();
        browserLifecycleState.consecutiveFailures = 0;
        browserLifecycleState.initialized = true;

        set({ _browserLifecycleInitialized: true });
    },

    teardownBrowserLifecycle: () => {
        if (!browserLifecycleState.initialized) {
            return;
        }

        if (typeof document !== 'undefined' && browserLifecycleState.onVisibilityChange) {
            document.removeEventListener('visibilitychange', browserLifecycleState.onVisibilityChange);
        }
        if (typeof window !== 'undefined' && browserLifecycleState.onOnline) {
            window.removeEventListener('online', browserLifecycleState.onOnline);
        }
        if (typeof window !== 'undefined' && browserLifecycleState.onOffline) {
            window.removeEventListener('offline', browserLifecycleState.onOffline);
        }

        if (browserLifecycleState.unsubscribeStore) {
            browserLifecycleState.unsubscribeStore();
            browserLifecycleState.unsubscribeStore = null;
        }

        if (browserLifecycleState.stopMobilePolling) {
            browserLifecycleState.stopMobilePolling();
        }
        if (browserLifecycleState.dismissConnectionToast) {
            browserLifecycleState.dismissConnectionToast();
        }

        browserLifecycleState.onVisibilityChange = null;
        browserLifecycleState.onOnline = null;
        browserLifecycleState.onOffline = null;
        browserLifecycleState.stopMobilePolling = null;
        browserLifecycleState.dismissConnectionToast = null;
        browserLifecycleState.mobilePollingInterval = null;
        browserLifecycleState.connectionToastId = null;
        browserLifecycleState.consecutiveFailures = 0;
        browserLifecycleState.lastEventTime = Date.now();
        browserLifecycleState.initialized = false;

        set({ _browserLifecycleInitialized: false });
    },

    // API methods
    fetchJobs: async ({ skipIfEventAfter } = {}) => {
        try {
            const data = await jobsApi.list();

            if (
                typeof skipIfEventAfter === 'number'
                && browserLifecycleState.lastEventTime > skipIfEventAfter
            ) {
                console.log('[JobStore] Skipping stale fetch result; newer WebSocket event already applied');
                return data;
            }

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
