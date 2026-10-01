import { useEffect, useRef, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import * as ws from '../api/websocket';
import { jobMetadata } from '../utils/jobStatus';
import toast from 'react-hot-toast';

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
        toast.dismiss('mobile-connection-error');
        if (connectionToastIdRef.current) toast.dismiss(connectionToastIdRef.current);
        connectionToastIdRef.current = null;
    }, []);

    // Invalidate only what some component is actually showing. These run on
    // every tab focus and every reconnect from every route, including the ones
    // with no job UI at all, and an unobserved cache refetch buys nothing: the
    // query is stale either way, so the next mount of its consumer refetches
    // it (these keys have staleTime 0).
    // `options` is passed through so a caller can narrow what is refetched — see
    // the `refetchPage` use on the gallery, where invalidating every loaded page
    // of an infinite query is a multi-request answer to a single question.
    const invalidateIfMounted = useCallback((queryKey, options = {}) => {
        const isMounted = queryClient.getQueryCache()
            .findAll({ queryKey })
            .some((query) => query.getObserversCount() > 0);
        if (isMounted) queryClient.invalidateQueries({ queryKey, ...options });
    }, [queryClient]);

    // Full refresh of the server-backed state after reconnect / refocus. The
    // per-job/per-active caches are already updated incrementally via
    // setQueryData on live events; this covers anything that raced a gap.
    const refreshServerState = useCallback(() => {
        invalidateIfMounted(['jobs', 'active']);
        invalidateIfMounted(['jobs', 'failed']);
        // Newest page only — see the note on the job.completed handler for why a
        // bare invalidation of an infinite query is the wrong shape here.
        invalidateIfMounted(['gallery'], { refetchPage: (page, allPages) => page === allPages[0] });
        invalidateIfMounted(['statistics']);
    }, [invalidateIfMounted]);

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
        invalidateIfMounted(['jobs', 'active']);
        invalidateIfMounted(['jobs', 'failed']);
    }, [invalidateIfMounted]);

    useEffect(() => {
        // Initial setup — subscribe exactly once. websocket.js re-subscribes
        // topics automatically after Socket.IO reconnects, so calling
        // subscribe() on every visibility change only leaks refcounts.
        lastEventTimeRef.current = Date.now();
        ws.connect().catch((error) => {
            console.warn('[useJobsRealtime] Initial connect failed:', error?.message || error);
        });
        void ws.subscribe('job').catch((error) => {
            console.warn('[useJobsRealtime] Initial subscription failed:', error?.message || error);
        });

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

            // A job just failed/cancelled: the failed-job diagnostics view is
            // driven by ['jobs','failed'] and must not show a stale list.
            if (type === 'failed' || type === 'cancelled') {
                queryClient.invalidateQueries({ queryKey: ['jobs', 'failed'] });
            }

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
            queryClient.invalidateQueries({ queryKey: ['jobs', 'queue'] });

            if (type === 'completed' && isImageJob) {
                // The asset list is what the user is looking at when a job
                // finishes, and nothing was refreshing it: the job caches were
                // updated, the queue was invalidated, a toast fired — and the
                // grid stayed exactly as it was. The new image only appeared on
                // a tab refocus or a websocket reconnect, because
                // `refreshServerState` is the only other thing that touches
                // `['gallery']`.
                //
                // That is also why the gallery *feels* un-live even though the
                // job card genuinely is live: you watch the card say completed
                // and the grid does not change. It is a missing invalidation,
                // not polling.
                //
                /* Refetch ONLY the newest page.

                   `useGallery` is a `useInfiniteQuery`, so a bare
                   `invalidateQueries({ queryKey: ['gallery'] })` refetches
                   *every page already loaded, sequentially*. With five pages
                   loaded that is five requests for one finished job, and the list
                   height changes as each one lands — which moves the sentinel,
                   which is what made a job update appear to drive the infinite
                   scroll.

                   The new image is on page 0 (the cursor runs newest-first), so
                   refetching only that page keeps the original fix — the grid
                   shows the new image — without the tail churn. Guarded by
                   `invalidateIfMounted` so a route with no gallery mounted buys
                   no refetch at all. */
                invalidateIfMounted(['gallery'], { refetchPage: (_page, allPages) => _page === allPages[0] });
                // Collection and world counts change with every new asset.
                invalidateIfMounted(['collections']);
                invalidateIfMounted(['statistics']);

                toast.success(
                    <div>
                        <strong>Image generated!</strong>
                        <br />
                        <span className="text-sm opacity-80">
                            {jobMetadata(job).prompt?.substring(0, 50) || 'Job completed'}
                            {jobMetadata(job).prompt?.length > 50 ? '...' : ''}
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
            // Nothing to refresh on a route with no active-jobs view mounted
            // (`/settings`, `/characters`, `/chat`).
            if (!queryClient.getQueryCache().findAll({ queryKey: ['jobs', 'active'] })
                .some((query) => query.getObserversCount() > 0)) {
                return;
            }
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
    }, [queryClient, invalidateIfMounted, replayMissedEvents, dismissConnectionToast, markEventReceived, refreshServerState]);
}

export default useJobsRealtime;
