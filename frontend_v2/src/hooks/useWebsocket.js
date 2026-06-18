import { useEffect, useCallback, useRef } from 'react';
import * as ws from '../api/websocket';
import { useJobStore } from '../store/jobStore';

const isMobile = () => typeof navigator !== 'undefined' && ('ontouchstart' in window || navigator.maxTouchPoints > 0);

export function useWebsocket() {
    const isConnected = useJobStore(state => state.isConnected);
    const connectionError = useJobStore(state => state.connectionError);
    const setConnectionStatus = useJobStore(state => state.setConnectionStatus);
    const processMessage = useJobStore(state => state.processMessage);
    const fetchJobs = useJobStore(state => state.fetchJobs);
    
    // Mutable refs for tracking lifecycle without causing re-renders
    const initializedRef = useRef(false);
    const unsubscribersRef = useRef([]);
    const connectPromiseRef = useRef(null);
    const lastEventTimeRef = useRef(Date.now());
    const consecutiveFailuresRef = useRef(0);
    const mobilePollingIntervalRef = useRef(null);
    const connectionToastIdRef = useRef(null);
    const lastPollingFetchStartedRef = useRef(0);

    const markEventReceived = useCallback(() => {
        lastEventTimeRef.current = Date.now();
        consecutiveFailuresRef.current = 0;
    }, []);

    const dismissConnectionToast = useCallback(async () => {
        if (!connectionToastIdRef.current) return;
        const { default: toast } = await import('react-hot-toast');
        toast.dismiss('mobile-connection-error');
        connectionToastIdRef.current = null;
    }, []);

    const stopMobilePolling = useCallback(() => {
        if (mobilePollingIntervalRef.current) {
            clearInterval(mobilePollingIntervalRef.current);
            mobilePollingIntervalRef.current = null;
            consecutiveFailuresRef.current = 0;
            console.log('[useWebsocket] Mobile polling stopped');
        }
    }, []);

    const startMobilePolling = useCallback(() => {
        if (mobilePollingIntervalRef.current) return;

        console.log('[useWebsocket] Starting mobile polling fallback...');
        consecutiveFailuresRef.current = 0;

        mobilePollingIntervalRef.current = setInterval(async () => {
            const hasActiveJobs = useJobStore.getState().jobs.length > 0;
            const wsEventsFlowing = Date.now() - lastEventTimeRef.current < 5000;

            if (!hasActiveJobs) {
                console.log('[useWebsocket] No active jobs, stopping mobile polling');
                stopMobilePolling();
                return;
            }

            if (wsEventsFlowing && useJobStore.getState().isConnected) {
                console.log('[useWebsocket] WebSocket events flowing, stopping mobile polling');
                stopMobilePolling();
                return;
            }

            console.log('[useWebsocket] Mobile polling: fetching jobs...');
            try {
                const fetchStartedAt = Date.now();
                lastPollingFetchStartedRef.current = fetchStartedAt;
                await useJobStore.getState().fetchJobs({ skipIfEventAfter: fetchStartedAt });
                consecutiveFailuresRef.current = 0;
            } catch (e) {
                console.error('[useWebsocket] Mobile polling fetch failed:', e);
                consecutiveFailuresRef.current += 1;

                if (consecutiveFailuresRef.current >= 3) {
                    const { default: toast } = await import('react-hot-toast');
                    connectionToastIdRef.current = toast.error('Connection issues - trying to reconnect...', {
                        id: 'mobile-connection-error',
                        duration: 4000,
                    });
                    consecutiveFailuresRef.current = 0;
                }
            }
        }, 2000);
    }, [stopMobilePolling]);

    const connect = useCallback(async () => {
        if (initializedRef.current) return;
        if (connectPromiseRef.current) return connectPromiseRef.current;

        const connectPromise = (async () => {
            try {
                await ws.connect();
                await ws.subscribe('job');

                const unsubConnection = ws.on('connection', (data) => {
                    setConnectionStatus(data.connected, data.error);
                    if (data.connected) {
                        console.log('[useWebsocket] WebSocket connected');
                    } else {
                        console.log('[useWebsocket] WebSocket disconnected:', data.reason || data.error);
                    }
                });

                const eventTypes = [
                    ws.EventTypes.JOB_CREATED,
                    ws.EventTypes.JOB_UPDATED,
                    ws.EventTypes.JOB_PROGRESS,
                    ws.EventTypes.JOB_POST_PROCESSING,
                    ws.EventTypes.JOB_COMPLETED,
                    ws.EventTypes.JOB_FAILED,
                    ws.EventTypes.JOB_CANCELLED,
                ];

                const eventUnsubscribers = eventTypes.map(eventType =>
                    ws.on(eventType, (data) => {
                        markEventReceived();
                        processMessage(data);
                    })
                );

                initializedRef.current = true;
                unsubscribersRef.current = [unsubConnection, ...eventUnsubscribers];
                setConnectionStatus(ws.getConnectionStatus(), null);
            } catch (error) {
                console.error('[useWebsocket] WebSocket connection failed:', error);
                setConnectionStatus(false, error.message);
            } finally {
                connectPromiseRef.current = null;
            }
        })();

        connectPromiseRef.current = connectPromise;
        return connectPromise;
    }, [processMessage, setConnectionStatus, markEventReceived]);

    const disconnect = useCallback(() => {
        unsubscribersRef.current.forEach(unsub => unsub && unsub());
        unsubscribersRef.current = [];
        ws.unsubscribe('job');
        ws.disconnect();
        setConnectionStatus(false, null);
        initializedRef.current = false;
        connectPromiseRef.current = null;
    }, [setConnectionStatus]);

    const reconnect = useCallback(async () => {
        console.log('[useWebsocket] Force reconnecting WebSocket...');
        ws.disconnect();
        setConnectionStatus(false, null);
        initializedRef.current = false;
        connectPromiseRef.current = null;
        
        await new Promise(resolve => setTimeout(resolve, 100));
        await connect();
    }, [connect, setConnectionStatus]);

    useEffect(() => {
        const onVisibilityChange = () => {
            if (document.visibilityState === 'visible') {
                dismissConnectionToast();
                console.log('[useWebsocket] Page became visible, checking WebSocket connection...');

                if (isMobile()) {
                    console.log('[useWebsocket] Mobile detected, forcing WebSocket reconnect...');
                    reconnect();
                    if (useJobStore.getState().jobs.length > 0) startMobilePolling();
                } else if (!useJobStore.getState().isConnected) {
                    connect();
                }

                const fetchStartedAt = Date.now();
                fetchJobs({ skipIfEventAfter: fetchStartedAt }).catch(console.error);
            } else {
                stopMobilePolling();
            }
        };

        const onOnline = () => {
            console.log('[useWebsocket] Network online, reconnecting WebSocket...');
            dismissConnectionToast();
            reconnect();
            const fetchStartedAt = Date.now();
            fetchJobs({ skipIfEventAfter: fetchStartedAt }).catch(console.error);
            if (isMobile() && useJobStore.getState().jobs.length > 0) startMobilePolling();
        };

        const onOffline = () => {
            console.log('[useWebsocket] Network offline, stopping mobile polling');
            stopMobilePolling();
        };

        document.addEventListener('visibilitychange', onVisibilityChange);
        window.addEventListener('online', onOnline);
        window.addEventListener('offline', onOffline);

        return () => {
            document.removeEventListener('visibilitychange', onVisibilityChange);
            window.removeEventListener('online', onOnline);
            window.removeEventListener('offline', onOffline);
            stopMobilePolling();
            dismissConnectionToast();
        };
    }, [connect, reconnect, fetchJobs, startMobilePolling, stopMobilePolling, dismissConnectionToast]);

    return {
        isConnected,
        connectionError,
        connect,
        disconnect,
        reconnect
    };
}
