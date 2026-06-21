import { useEffect, useRef, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import * as ws from '../api/websocket';
import { jobsApi } from '../api';
import useJobStore from '../store/jobStore';
import toast from 'react-hot-toast';

const isMobile = () => typeof navigator !== 'undefined' && ('ontouchstart' in window || navigator.maxTouchPoints > 0);

export function useJobsRealtime() {
    const queryClient = useQueryClient();

    const lastEventTimeRef = useRef(0);
    const consecutiveFailuresRef = useRef(0);
    const connectionToastIdRef = useRef(null);
    const initializedRef = useRef(false);
    const lastSequenceNumberRef = useRef(0);

    const markEventReceived = useCallback(() => {
        lastEventTimeRef.current = Date.now();
        consecutiveFailuresRef.current = 0;
    }, []);

    const dismissConnectionToast = useCallback(async () => {
        if (!connectionToastIdRef.current) return;
        toast.dismiss('mobile-connection-error');
        connectionToastIdRef.current = null;
    }, []);

    const connectAndSubscribe = useCallback(async () => {
        try {
            await ws.connect();
            await ws.subscribe('job');
            initializedRef.current = true;

            // Request replay of any events missed during disconnection
            if (lastSequenceNumberRef.current > 0) {
                const missedEvents = await ws.requestReplay(lastSequenceNumberRef.current);
                if (missedEvents.length > 0) {
                    ws.dispatchReplayEvents(missedEvents);
                }
                // After replay, invalidate active jobs to ensure consistency
                queryClient.invalidateQueries({ queryKey: ['jobs', 'active'] });
            }
        } catch (error) {
            console.error('[useJobsRealtime] WebSocket connect/subscribe failed:', error);
        }
    }, [queryClient]);

    useEffect(() => {
        // Initial setup
        lastEventTimeRef.current = Date.now();
        void connectAndSubscribe();

        const unsubs = [];

        // 1. Job Created -> Prepend to active jobs list
        unsubs.push(ws.on(ws.EventTypes.JOB_CREATED, (event) => {
            const job = event.data?.job || event;
            markEventReceived();
            if (event.sequence_number) lastSequenceNumberRef.current = event.sequence_number;
            queryClient.setQueryData(['jobs', 'active'], (old = []) => {
                if (old.some(j => j.id === job.id)) return old;
                return [job, ...old];
            });
        }));

        // 2. Job Progress/Updated -> Update in Zustand store to prevent expensive re-renders
        const handleUpdate = (event) => {
            const job = event.data?.job || event;
            markEventReceived();
            if (event.sequence_number) lastSequenceNumberRef.current = event.sequence_number;
            
            // Push high-frequency updates to the lightweight Zustand store
            useJobStore.getState().updateJob(job.id, job);
        };

        unsubs.push(ws.on(ws.EventTypes.JOB_PROGRESS, handleUpdate));
        unsubs.push(ws.on(ws.EventTypes.JOB_UPDATED, handleUpdate));
        unsubs.push(ws.on(ws.EventTypes.JOB_POST_PROCESSING, handleUpdate));

        // 3. Job Terminated -> Remove from active, update detail, invalidate gallery, show toast
        const handleTermination = (event, type) => {
            const job = event.data?.job || event;
            markEventReceived();
            if (event.sequence_number) lastSequenceNumberRef.current = event.sequence_number;

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
            
            // CLEANUP ZUSTAND TO PREVENT MEMORY LEAKS
            useJobStore.getState().removeJob(job.id);

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
                dismissConnectionToast();
            }
        }));

        // Document visibility and network listeners
        const onVisibilityChange = () => {
            if (document.visibilityState === 'visible') {
                dismissConnectionToast();

                if (!ws.getConnectionStatus()) {
                    void connectAndSubscribe();
                }

                queryClient.invalidateQueries({ queryKey: ['jobs', 'active'] });
            }
        };

        const onOnline = () => {
            dismissConnectionToast();
            // Only reconnect if actually disconnected — don't destroy a working socket
            if (!ws.getConnectionStatus()) {
                void connectAndSubscribe();
            }
            queryClient.invalidateQueries({ queryKey: ['jobs', 'active'] });
        };

        document.addEventListener('visibilitychange', onVisibilityChange);
        window.addEventListener('online', onOnline);

        return () => {
            unsubs.forEach(unsub => unsub?.());
            ws.unsubscribe('job');
            // Do NOT call ws.disconnect() — the socket is a module-level singleton
            // that should persist for the lifetime of the page. Destroying it here
            // causes events to be lost during the reconnection window.
            dismissConnectionToast();
            document.removeEventListener('visibilitychange', onVisibilityChange);
            window.removeEventListener('online', onOnline);
        };
    }, [queryClient, connectAndSubscribe, dismissConnectionToast, markEventReceived]);
}

export default useJobsRealtime;
