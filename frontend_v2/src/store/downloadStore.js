/**
 * downloadStore.js - Real-time model download tracking store
 *
 * Subscribes to WebSocket "download.*" events emitted by the backend whenever
 * a model download starts, progresses, completes, or fails.
 *
 * STATE SHAPE:
 *   downloads     – Array of download objects (sorted newest-first).
 *   isConnected   – Whether the WebSocket connection is live.
 *   _wsInitialized – Internal flag; prevents duplicate subscriptions.
 *   _unsubscribers – Cleanup functions returned by `ws.on()`.
 *
 * LIFECYCLE:
 *   Call `connect()` once at app startup (done in App.jsx via providerStore or
 *   a dedicated model-manager hook).  The store will stay in sync via WebSocket
 *   events and a one-time initial HTTP fetch.
 */

import { create } from 'zustand';
import * as ws from '../api/websocket';
import { api } from '../api';

/**
 * Download Store
 * Centralized WebSocket-based download tracking.
 * Replaces legacy SSE logic.
 */
export const useDownloadStore = create((set, get) => ({
    downloads: [],
    isConnected: false,
    _wsInitialized: false,
    _unsubscribers: [],

    setDownloads: (downloads) => {
        // Sort by updated_at desc
        const sorted = [...downloads].sort((a, b) =>
            new Date(b.created_at || 0) - new Date(a.created_at || 0)
        );
        set({ downloads: sorted });
    },

    // Handle WebSocket message processing
    _processMessage: (data) => {
        // Check if data is wrapped in an event object or direct
        const payload = data.data?.download || data.download;

        if (!payload) return;

        set((state) => {
            const exists = state.downloads.some(d => d.id === payload.id);
            let newDownloads;

            if (exists) {
                // Update existing
                newDownloads = state.downloads.map(d =>
                    d.id === payload.id ? { ...d, ...payload } : d
                );
            } else {
                // Add new (prepend)
                newDownloads = [payload, ...state.downloads];
            }

            // Clean up: remove if status is final? 
            // Usually we keep them for a bit, or let user clear them.
            // But if it's 'deleted', we might want to remove.
            // For now, keep all sync'd.

            return { downloads: newDownloads };
        });
    },

    // Initialize WebSocket connection
    connect: async () => {
        const { _wsInitialized } = get();
        if (_wsInitialized) return;

        try {
            await ws.connect();
            await ws.subscribe('download');

            const unsubConnection = ws.on('connection', (data) => {
                set({ isConnected: data.connected });
                if (data.connected) {
                    // Fetch fresh list on connect
                    get().fetchDownloads();
                }
            });

            const eventTypes = [
                ws.EventTypes.DOWNLOAD_STARTED,
                ws.EventTypes.DOWNLOAD_PROGRESS,
                ws.EventTypes.DOWNLOAD_COMPLETED,
                ws.EventTypes.DOWNLOAD_FAILED,
            ];

            const unsubscribers = eventTypes.map(type =>
                ws.on(type, (data) => get()._processMessage(data))
            );

            set({
                _wsInitialized: true,
                _unsubscribers: [unsubConnection, ...unsubscribers],
                isConnected: ws.getConnectionStatus()
            });

            // Initial fetch
            get().fetchDownloads();

        } catch (error) {
            console.error('[DownloadStore] WebSocket connection failed:', error);
        }
    },

    disconnect: () => {
        const { _unsubscribers } = get();
        _unsubscribers.forEach(u => u && u());
        ws.unsubscribe('download');
        set({ isConnected: false, _wsInitialized: false, _unsubscribers: [] });
    },

    fetchDownloads: async () => {
        try {
            const response = await api.get('/api/downloads');
            get().setDownloads(response.data.downloads || []);
        } catch (error) {
            console.error("Failed to fetch downloads", error);
        }
    },

    // Clear a completed/failed download
    clearDownload: async (id) => {
        try {
            // Optimistic update
            set((state) => ({
                downloads: state.downloads.filter(d => d.id !== id)
            }));
            // We assume backend handles the actual cleanup via API if needed, 
            // strictly speaking this might just comprise removing from view.
            // But if there is an API endpoint:
            await api.delete(`/api/downloads/${id}`);
            return true;
        } catch (e) {
            // Re-fetch on error to restore state
            get().fetchDownloads();
            console.error("Failed to clear download", e);
            return false;
        }
    },

    // Clear all completed downloads
    clearCompleted: async () => {
        const { downloads } = get();
        const completed = downloads.filter(d => d.status === 'completed' || d.status === 'failed' || d.status === 'success');

        // Optimistic clear
        set(state => ({
            downloads: state.downloads.filter(d => d.status !== 'completed' && d.status !== 'failed' && d.status !== 'success')
        }));

        for (const d of completed) {
            // Silently fail individual clears to avoid spamming errors, or better: have a bulk clear endpoint
            try {
                await api.delete(`/api/downloads/${d.id}`);
            } catch (e) { /* ignore */ }
        }
    },

    // Get active download count
    getActiveCount: () => {
        return get().downloads.filter(d => d.status === 'downloading' || d.status === 'pending').length;
    },

    // Get completed count
    getCompletedCount: () => {
        return get().downloads.filter(d => d.status === 'completed' || d.status === 'success').length;
    }
}));

export default useDownloadStore;
