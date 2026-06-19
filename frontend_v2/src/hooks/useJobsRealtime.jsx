import { useEffect, useRef, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import * as ws from '../api/websocket';
import { jobsApi } from '../api';
import toast from 'react-hot-toast';

const isMobile = () => typeof navigator !== 'undefined' && ('ontouchstart' in window || navigator.maxTouchPoints > 0);

export function useJobsRealtime() {
    const queryClient = useQueryClient();

    const lastEventTimeRef = useRef(0);
    const consecutiveFailuresRef = useRef(0);
    const mobilePollingIntervalRef = useRef(null);
    const connectionToastIdRef = useRef(null);
    const initializedRef = useRef(false);

    const markEventReceived = useCallback(() => {
        lastEventTimeRef.current = Date.now();
        consecutiveFailuresRef.current = 0;
    }, []);

    const dismissConnectionToast = useCallback(async () => {
        if (!connectionToastIdRef.current) return;
        toast.dismiss('mobile-connection-error');
        connectionToastIdRef.current = null;
    }, []);

    const stopMobilePolling = useCallback(() => {
        if (mobilePollingIntervalRef.current) {
            clearInterval(mobilePollingIntervalRef.current);
            mobilePollingIntervalRef.current = null;
            consecutiveFailuresRef.current = 0;
            console.log('[useJobsRealtime] Mobile polling stopped');
        }
    }, []);

    const startMobilePolling = useCallback(() => {
        if (mobilePollingIntervalRef.current) return;

        console.log('[useJobsRealtime] Starting mobile polling fallback...');
        consecutiveFailuresRef.current = 0;

        mobilePollingIntervalRef.current = setInterval(async () => {
            const activeJobs = queryClient.getQueryData(['jobs', 'active']) || [];
            const hasActiveJobs = activeJobs.length > 0;
            const wsEventsFlowing = Date.now() - lastEventTimeRef.current < 5000;

            if (!hasActiveJobs) {
                console.log('[useJobsRealtime] No active jobs, stopping mobile polling');
                stopMobilePolling();
                return;
            }

            if (wsEventsFlowing && ws.getConnectionStatus()) {
                console.log('[useJobsRealtime] WebSocket events flowing, stopping mobile polling');
                stopMobilePolling();
                return;
            }

            console.log('[useJobsRealtime] Mobile polling: fetching jobs...');
            try {
                const data = await jobsApi.getActive();
                const fetchedJobs = data?.jobs || [];
                queryClient.setQueryData(['jobs', 'active'], fetchedJobs);
                consecutiveFailuresRef.current = 0;
            } catch (e) {
                console.error('[useJobsRealtime] Mobile polling fetch failed:', e);
                consecutiveFailuresRef.current += 1;

                if (consecutiveFailuresRef.current >= 3) {
                    connectionToastIdRef.current = toast.error('Connection issues - trying to reconnect...', {
                        id: 'mobile-connection-error',
                        duration: 4000,
                    });
                    consecutiveFailuresRef.current = 0;
                }
            }
        }, 2000);
    }, [queryClient, stopMobilePolling]);

    const connectAndSubscribe = useCallback(async () => {
        try {
            await ws.connect();
            await ws.subscribe('job');
            initializedRef.current = true;
        } catch (error) {
            console.error('[useJobsRealtime] WebSocket connect/subscribe failed:', error);
        }
    }, []);

    const reconnect = useCallback(async () => {
        console.log('[useJobsRealtime] Force reconnecting WebSocket...');
        ws.disconnect();
        initializedRef.current = false;
        await new Promise(resolve => setTimeout(resolve, 100));
        await connectAndSubscribe();
    }, [connectAndSubscribe]);

    useEffect(() => {
        // Initial setup
        lastEventTimeRef.current = Date.now();
        void connectAndSubscribe();

        const unsubs = [];

        // 1. Job Created -> Prepend to active jobs list
        unsubs.push(ws.on(ws.EventTypes.JOB_CREATED, (event) => {
            const job = event.data?.job || event;
            markEventReceived();
            queryClient.setQueryData(['jobs', 'active'], (old = []) => {
                if (old.some(j => j.id === job.id)) return old;
                return [job, ...old];
            });
        }));

        // 2. Job Progress/Updated -> Update in active list & specific query
        const handleUpdate = (event) => {
            const job = event.data?.job || event;
            markEventReceived();
            queryClient.setQueryData(['jobs', 'active'], (old = []) =>
                old.map(j => j.id === job.id ? { ...j, ...job } : j)
            );
            queryClient.setQueryData(['jobs', job.id], (old) =>
                old ? { ...old, ...job } : job
            );
        };

        unsubs.push(ws.on(ws.EventTypes.JOB_PROGRESS, handleUpdate));
        unsubs.push(ws.on(ws.EventTypes.JOB_UPDATED, handleUpdate));
        unsubs.push(ws.on(ws.EventTypes.JOB_POST_PROCESSING, handleUpdate));

        // 3. Job Terminated -> Remove from active, update detail, invalidate gallery, show toast
        const handleTermination = (event, type) => {
            const job = event.data?.job || event;
            markEventReceived();

            queryClient.setQueryData(['jobs', 'active'], (old = []) => {
                const remaining = old.filter(j => j.id !== job.id);
                if (old.length > 0 && remaining.length === 0) {
                    toast.success('All jobs completed! Queue is empty.', { icon: '🎉' });
                }
                return remaining;
            });

            queryClient.setQueryData(['jobs', job.id], (old) =>
                old ? { ...old, ...job } : job
            );
            queryClient.invalidateQueries({ queryKey: ['gallery'] });

            if (type === 'completed') {
                toast.success(
                    <div>
                        <strong>Image generated!</strong>
                        <br />
                        <span className="text-sm opacity-80">
                            {job.metadata_?.prompt?.substring(0, 50) || 'Job completed'}
                            {job.metadata_?.prompt?.length > 50 ? '...' : ''}
                        </span>
                    </div>,
                    { icon: '✨' }
                );
            } else if (type === 'failed') {
                toast.error(
                    <div>
                        <strong>Job failed</strong>
                        <br />
                        <span className="text-sm opacity-80">{job.error || 'Unknown error'}</span>
                    </div>
                );
            } else if (type === 'cancelled') {
                toast('Job cancelled', { icon: '🛑' });
            }
        };

        unsubs.push(ws.on(ws.EventTypes.JOB_COMPLETED, (e) => handleTermination(e, 'completed')));
        unsubs.push(ws.on(ws.EventTypes.JOB_FAILED, (e) => handleTermination(e, 'failed')));
        unsubs.push(ws.on(ws.EventTypes.JOB_CANCELLED, (e) => handleTermination(e, 'cancelled')));

        // Connection events
        unsubs.push(ws.on('connection', (data) => {
            if (data.connected) {
                console.log('[useJobsRealtime] WebSocket connected');
                dismissConnectionToast();
            } else {
                console.log('[useJobsRealtime] WebSocket disconnected:', data.reason || data.error);
            }
        }));

        // Document visibility and network listeners
        const onVisibilityChange = () => {
            if (document.visibilityState === 'visible') {
                dismissConnectionToast();
                console.log('[useJobsRealtime] Page became visible, checking WebSocket connection...');

                if (isMobile()) {
                    console.log('[useJobsRealtime] Mobile detected, forcing WebSocket reconnect...');
                    reconnect();
                    const activeJobs = queryClient.getQueryData(['jobs', 'active']) || [];
                    if (activeJobs.length > 0) startMobilePolling();
                } else if (!ws.getConnectionStatus()) {
                    void connectAndSubscribe();
                }

                queryClient.invalidateQueries({ queryKey: ['jobs', 'active'] });
            } else {
                stopMobilePolling();
            }
        };

        const onOnline = () => {
            console.log('[useJobsRealtime] Network online, reconnecting WebSocket...');
            dismissConnectionToast();
            reconnect();
            queryClient.invalidateQueries({ queryKey: ['jobs', 'active'] });
            const activeJobs = queryClient.getQueryData(['jobs', 'active']) || [];
            if (isMobile() && activeJobs.length > 0) startMobilePolling();
        };

        const onOffline = () => {
            console.log('[useJobsRealtime] Network offline, stopping mobile polling');
            stopMobilePolling();
        };

        document.addEventListener('visibilitychange', onVisibilityChange);
        window.addEventListener('online', onOnline);
        window.addEventListener('offline', onOffline);

        return () => {
            unsubs.forEach(unsub => unsub?.());
            ws.unsubscribe('job');
            ws.disconnect();
            stopMobilePolling();
            dismissConnectionToast();
            document.removeEventListener('visibilitychange', onVisibilityChange);
            window.removeEventListener('online', onOnline);
            window.removeEventListener('offline', onOffline);
        };
    }, [queryClient, connectAndSubscribe, reconnect, startMobilePolling, stopMobilePolling, dismissConnectionToast, markEventReceived]);
}

export default useJobsRealtime;
