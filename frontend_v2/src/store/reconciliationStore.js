import { create } from 'zustand';
import * as ws from '../api/websocket';

/**
 * Reconciliation Store
 * Centralized WebSocket-based reconciliation tracking.
 * Follows the same pattern as jobStore and downloadStore.
 */
const useReconciliationStore = create((set, get) => ({
    // Track active reconciliations by provider ID
    activeReconciliations: {}, // { providerId: { status, phase, stats, etc } }
    _wsInitialized: false,
    _unsubscribers: [],

    // Start tracking a reconciliation
    startReconciliation: (providerId) => {
        set((state) => ({
            activeReconciliations: {
                ...state.activeReconciliations,
                [providerId]: {
                    status: 'reconciling',
                    phase: 'validating',
                    startedAt: new Date().toISOString(),
                    stats: {
                        total_models_in_modal: 0,
                        downloads_queued: 0,
                        downloads_completed: 0,
                        downloads_failed: 0,
                        deletions_completed: 0
                    },
                    current_download: null,
                    active_downloads: [],
                    errors: [],
                    message: 'Starting reconciliation...'
                }
            }
        }));
    },

    // Update reconciliation status
    updateReconciliation: (providerId, data) => {
        set((state) => ({
            activeReconciliations: {
                ...state.activeReconciliations,
                [providerId]: {
                    ...state.activeReconciliations[providerId],
                    ...data,
                    // Merge active_downloads if provided
                    active_downloads: data.active_downloads ?? state.activeReconciliations[providerId]?.active_downloads ?? [],
                }
            }
        }));
    },

    // End tracking a reconciliation
    endReconciliation: (providerId) => {
        set((state) => {
            const { [providerId]: removed, ...remaining } = state.activeReconciliations;
            return { activeReconciliations: remaining };
        });
    },

    // Process WebSocket events
    _processEvent: (data) => {
        const eventData = data.data || data;
        const providerId = eventData.provider_id;
        if (!providerId) return;

        const { startReconciliation, updateReconciliation, endReconciliation } = get();

        if (eventData.status === 'started') {
            startReconciliation(providerId);
        } else if (eventData.status === 'completed' || eventData.status === 'failed') {
            updateReconciliation(providerId, {
                status: eventData.status,
                phase: eventData.phase || (eventData.status === 'completed' ? 'completed' : 'failed'),
                stats: eventData.stats,
                message: eventData.message,
                errors: eventData.errors
            });
            // Clear after delay so user can see final status
            setTimeout(() => endReconciliation(providerId), 5000);
        } else {
            // Progress update
            updateReconciliation(providerId, {
                status: eventData.status || 'reconciling',
                phase: eventData.phase,
                stats: eventData.stats,
                current_download: eventData.current_download,
                active_downloads: eventData.active_downloads,
                errors: eventData.errors,
                message: eventData.message
            });
        }
    },

    // Initialize WebSocket connection (call at app startup)
    connect: async () => {
        const { _wsInitialized } = get();
        if (_wsInitialized) return;

        try {
            await ws.connect();
            await ws.subscribe('reconciliation');

            // Subscribe to all reconciliation events
            const unsubStarted = ws.on(ws.EventTypes.RECONCILIATION_STARTED, get()._processEvent);
            const unsubProgress = ws.on(ws.EventTypes.RECONCILIATION_PROGRESS, get()._processEvent);
            const unsubCompleted = ws.on(ws.EventTypes.RECONCILIATION_COMPLETED, get()._processEvent);

            set({
                _wsInitialized: true,
                _unsubscribers: [unsubStarted, unsubProgress, unsubCompleted]
            });

            console.log('[ReconciliationStore] WebSocket connected');
        } catch (error) {
            console.error('[ReconciliationStore] WebSocket connection failed:', error);
        }
    },

    disconnect: () => {
        const { _unsubscribers } = get();
        _unsubscribers.forEach(unsub => unsub && unsub());
        ws.unsubscribe('reconciliation');
        set({ _wsInitialized: false, _unsubscribers: [] });
    },

    // Get active count
    getActiveCount: () => {
        return Object.keys(get().activeReconciliations).length;
    },

    // Get reconciliation for provider
    getReconciliation: (providerId) => {
        return get().activeReconciliations[providerId] || null;
    }
}));

export default useReconciliationStore;
