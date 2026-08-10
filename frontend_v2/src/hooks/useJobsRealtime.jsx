import { useEffect, useRef, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import * as ws from '../api/websocket';
import toast from 'react-hot-toast';
import useSettingsStore from '../store/settingsStore';

export function useJobsRealtime() {
    const queryClient = useQueryClient();

    const lastEventTimeRef = useRef(0);
    const connectionToastIdRef = useRef(null);
    const lastSequenceNumberRef = useRef(0);
    const connectedRef = useRef(false);

    const markEventReceived = useCallback(() => {
        lastEventTimeRef.current = Date.now();
    }, []);

    const dismissConnectionToast = useCallback(async () => {
        if (!connectionToastIdRef.current) return;
        toast.dismiss('mobile-connection-error');
        connectionToastIdRef.current = null;
    }, []);

    // Full refresh of the server-backed state after reconnect / refocus. The
    // per-job/per-active caches are already updated incrementally via
    // setQueryData on live events; this covers anything that raced a gap.
    const refreshServerState = useCallback(() => {
        queryClient.invalidateQueries({ queryKey: ['jobs', 'active'] });
        queryClient.invalidateQueries({ queryKey: ['gallery'] });
        queryClient.invalidateQueries({ queryKey: ['statistics'] });
    }, [queryClient]);

    // Replay events missed during a disconnect. lastSequenceNumberRef is the
    // highest sequence number already applied, so the server only replays
    // what the client actually missed — safe to call on every reconnect.
    const replayMissedEvents = useCallback(async () => {
        if (lastSequenceNumberRef.current <= 0) return;
        try {
            const missedEvents = await ws.requestReplay(lastSequenceNumberRef.current);
            if (missedEvents.length > 0) {
                ws.dispatchReplayEvents(missedEvents);
            }
        } catch (error) {
            console.warn('[useJobsRealtime] Replay request failed:', error);
        }
        // After replay, invalidate to ensure consistency regardless.
        queryClient.invalidateQueries({ queryKey: ['jobs', 'active'] });
    }, [queryClient]);

    useEffect(() => {
        // Initial setup — subscribe exactly once. websocket.js re-subscribes
        // topics automatically after Socket.IO reconnects, so calling
        // subscribe() on every visibility change only leaks refcounts.
        lastEventTimeRef.current = Date.now();
        ws.connect().catch((error) => {
            console.warn('[useJobsRealtime] Initial connect failed:', error?.message || error);
        });
        void ws.subscribe('job');

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
            queryClient.invalidateQueries({ queryKey: ['jobs', 'queue'] });
        }));

        // 2. Job Progress/Updated -> Update in React Query
        const handleUpdate = (event) => {
            const job = event.data?.job || event;
            markEventReceived();
            if (event.sequence_number) lastSequenceNumberRef.current = event.sequence_number;

            // Partial LLM stream payloads ({id, status, stream_chunk, text,
            // metadata_}) carry no task_type or progress and would corrupt the
            // cached job (dropping task_type/provider_id, regressing status
            // out-of-order). Their text content is consumed via the streaming
            // store instead. Full job payloads always have task_type.
            if (!job.task_type && job.progress == null && job.overall_progress == null) return;

            // Update the single source of truth
            queryClient.setQueryData(['jobs', job.id], (old) => old ? { ...old, ...job } : job);

            queryClient.setQueryData(['jobs', 'active'], (old = []) => {
                return old.map(j => j.id === job.id ? { ...j, ...job } : j);
            });
        };

        unsubs.push(ws.on(ws.EventTypes.JOB_PROGRESS, handleUpdate));
        unsubs.push(ws.on(ws.EventTypes.JOB_UPDATED, handleUpdate));
        unsubs.push(ws.on(ws.EventTypes.JOB_POST_PROCESSING, handleUpdate));

        // 3. Job Terminated -> Remove from active, update detail, invalidate gallery, show toast
        const handleTermination = (event, type) => {
            const job = event.data?.job || event;
            markEventReceived();
            if (event.sequence_number) lastSequenceNumberRef.current = event.sequence_number;

            const isImageJob = job.task_type === 'image';

            queryClient.setQueryData(['jobs', 'active'], (old = []) => {
                const remaining = old.filter(j => j.id !== job.id);
                if (isImageJob && old.length > 0 && remaining.length === 0) {
                    toast.success('All jobs completed! Queue is empty.', { icon: '🎉' });
                }
                return remaining;
            });

            queryClient.setQueryData(['jobs', job.id], (old) =>
                old ? { ...old, ...job } : job
            );
            // Queue membership changed — refresh the queue panel. Gallery refresh
            // respects the user's autoRefreshOnJobComplete setting (it's a
            // bandwidth/preference choice, not a correctness one).
            queryClient.invalidateQueries({ queryKey: ['jobs', 'queue'] });
            if (useSettingsStore.getState().settings.gallery.autoRefreshOnJobComplete) {
                queryClient.invalidateQueries({ queryKey: ['gallery'] });
            }

            if (type === 'completed' && isImageJob) {
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
            } else if (type === 'failed' && isImageJob) {
                toast.error(
                    <div>
                        <strong>Job failed</strong>
                        <br />
                        <span className="text-sm opacity-80">{job.error || 'Unknown error'}</span>
                    </div>
                );
            } else if (type === 'cancelled' && isImageJob) {
                toast('Job cancelled', { icon: '🛑' });
            }
        };

        unsubs.push(ws.on(ws.EventTypes.JOB_COMPLETED, (e) => handleTermination(e, 'completed')));
        unsubs.push(ws.on(ws.EventTypes.JOB_FAILED, (e) => handleTermination(e, 'failed')));
        unsubs.push(ws.on(ws.EventTypes.JOB_CANCELLED, (e) => handleTermination(e, 'cancelled')));

        // Connection events
        unsubs.push(ws.on('connection', (data) => {
            if (data.connected) {
                const wasConnected = connectedRef.current;
                connectedRef.current = true;
                dismissConnectionToast();
                refreshServerState();
                // Real (re)connection: catch up on events missed during the gap.
                if (wasConnected || lastSequenceNumberRef.current > 0) {
                    void replayMissedEvents();
                }
            } else {
                connectedRef.current = false;
                if (document.visibilityState === 'visible') {
                    if (!connectionToastIdRef.current) {
                        connectionToastIdRef.current = toast.error(
                            'Disconnected from server. Trying to reconnect...',
                            { id: 'mobile-connection-error', duration: Infinity }
                        );
                    }
                }
            }
        }));

        // Watchdog: if the socket claims to be connected but events stopped
        // arriving (silently dropped), refetch the active queue so desktop
        // stays fresh even with refetchOnWindowFocus disabled.
        const watchdog = setInterval(() => {
            if (ws.getConnectionStatus() && Date.now() - lastEventTimeRef.current > 15000) {
                queryClient.invalidateQueries({ queryKey: ['jobs', 'active'] });
                lastEventTimeRef.current = Date.now();
            }
        }, 20000);

        // Document visibility and network listeners
        const onVisibilityChange = () => {
            if (document.visibilityState === 'visible') {
                dismissConnectionToast();

                if (!ws.getConnectionStatus()) {
                    ws.connect().catch((error) => {
                        console.warn('[useJobsRealtime] Reconnect failed:', error?.message || error);
                    });
                }

                refreshServerState();
            }
        };

        const onOnline = () => {
            dismissConnectionToast();
            // Only reconnect if actually disconnected — don't destroy a working socket
            if (!ws.getConnectionStatus()) {
                ws.connect().catch((error) => {
                    console.warn('[useJobsRealtime] Reconnect failed:', error?.message || error);
                });
            }
            refreshServerState();
        };

        document.addEventListener('visibilitychange', onVisibilityChange);
        window.addEventListener('online', onOnline);

        return () => {
            unsubs.forEach(unsub => unsub?.());
            clearInterval(watchdog);
            ws.unsubscribe('job');
            // Do NOT call ws.disconnect() — the socket is a module-level singleton
            // that should persist for the lifetime of the page. Destroying it here
            // causes events to be lost during the reconnection window.
            dismissConnectionToast();
            document.removeEventListener('visibilitychange', onVisibilityChange);
            window.removeEventListener('online', onOnline);
        };
    }, [queryClient, replayMissedEvents, dismissConnectionToast, markEventReceived, refreshServerState]);
}

export default useJobsRealtime;
