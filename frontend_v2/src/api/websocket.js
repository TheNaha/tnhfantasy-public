/**
 * WebSocket Client for Real-time Communication
 * 
 * Provides a Socket.IO client singleton with:
 * - Auto-connect/reconnect handling
 * - Room-based topic subscriptions
 * - Event listener management
 * - Connection status tracking
 * 
 * This replaces SSE for bidirectional real-time communication.
 */

import { io } from 'socket.io-client';

// Get API URL - use empty string to connect relative to current origin
// This ensures Socket.IO goes through the Vite proxy (/socket.io -> backend:8002)
// Works for: localhost, local network IP, and Tailscale access
const API_URL = '';

// WebSocket connection instance
let socket = null;

// Connection state
let isConnected = false;
let connectionPromise = null;

// Event listeners by event name
const listeners = new Map();

// Subscribed topics
const subscribedTopics = new Set();

/**
 * Initialize WebSocket connection
 * @returns {Promise} Resolves when connected
 */
export function connect() {
    if (connectionPromise) {
        return connectionPromise;
    }

    connectionPromise = new Promise((resolve, reject) => {
        if (socket && isConnected) {
            resolve(socket);
            return;
        }

        // Create Socket.IO connection
        socket = io(API_URL, {
            path: '/socket.io/',
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionAttempts: Infinity,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            timeout: 20000,
        });

        socket.on('connect', () => {
            console.log('[WebSocket] Connected:', socket.id);
            isConnected = true;

            // Re-subscribe to topics after reconnection
            if (subscribedTopics.size > 0) {
                socket.emit('subscribe', { topics: Array.from(subscribedTopics) });
            }

            // Re-register all pending listeners with the new socket connection
            // This is critical for mobile reconnection where the socket instance is reused
            // but event handlers may have been cleared
            listeners.forEach((callbacks, event) => {
                callbacks.forEach(callback => {
                    // Check if listener is already registered to avoid duplicates
                    if (!socket.listeners(event).includes(callback)) {
                        socket.on(event, callback);
                    }
                });
            });

            // Notify connection listeners
            emitLocal('connection', { connected: true, id: socket.id });
            resolve(socket);
        });

        socket.on('disconnect', (reason) => {
            console.log('[WebSocket] Disconnected:', reason);
            isConnected = false;
            emitLocal('connection', { connected: false, reason });
        });

        socket.on('connect_error', (error) => {
            console.warn('[WebSocket] Connection error:', error.message);
            emitLocal('connection', { connected: false, error: error.message });
        });

        socket.on('connected', (data) => {
            console.log('[WebSocket] Server welcome:', data.message);
        });

        socket.on('subscribed', (data) => {
            console.log('[WebSocket] Subscribed to:', data.topics);
        });

        socket.on('unsubscribed', (data) => {
            console.log('[WebSocket] Unsubscribed from:', data.topics);
        });

        socket.on('error', (data) => {
            console.error('[WebSocket] Server error:', data.message);
            emitLocal('error', data);
        });

        // Handle pong for keepalive
        socket.on('pong', (data) => {
            // Connection is alive
        });
    });

    return connectionPromise;
}

/**
 * Disconnect from WebSocket server
 */
export function disconnect() {
    if (socket) {
        socket.disconnect();
        socket = null;
    }
    isConnected = false;
    connectionPromise = null;
    subscribedTopics.clear();
}

/**
 * Get connection status
 * @returns {boolean}
 */
export function getConnectionStatus() {
    return isConnected;
}

/**
 * Subscribe to a topic (join a room)
 * @param {string|string[]} topics - Topic(s) to subscribe to
 */
export async function subscribe(topics) {
    const topicArray = Array.isArray(topics) ? topics : [topics];

    // Track subscriptions locally
    topicArray.forEach(t => subscribedTopics.add(t));

    // Ensure connected
    await connect();

    if (socket) {
        socket.emit('subscribe', { topics: topicArray });
    }
}

/**
 * Unsubscribe from a topic (leave a room)
 * @param {string|string[]} topics - Topic(s) to unsubscribe from
 */
export function unsubscribe(topics) {
    const topicArray = Array.isArray(topics) ? topics : [topics];

    // Remove from local tracking
    topicArray.forEach(t => subscribedTopics.delete(t));

    if (socket) {
        socket.emit('unsubscribe', { topics: topicArray });
    }
}

/**
 * Add event listener for WebSocket events
 * @param {string} event - Event name (e.g., 'job.progress', 'job.completed')
 * @param {function} callback - Callback function
 * @returns {function} Unsubscribe function
 */
export function on(event, callback) {
    if (!listeners.has(event)) {
        listeners.set(event, new Set());
    }
    listeners.get(event).add(callback);

    // Also register with Socket.IO if connected
    if (socket) {
        socket.on(event, callback);
    }

    // Return unsubscribe function
    return () => off(event, callback);
}

/**
 * Remove event listener
 * @param {string} event - Event name
 * @param {function} callback - Callback function to remove
 */
export function off(event, callback) {
    const eventListeners = listeners.get(event);
    if (eventListeners) {
        eventListeners.delete(callback);
        if (eventListeners.size === 0) {
            listeners.delete(event);
        }
    }

    if (socket) {
        socket.off(event, callback);
    }
}

/**
 * Emit local event to all registered listeners
 * @param {string} event - Event name
 * @param {any} data - Event data
 */
function emitLocal(event, data) {
    const eventListeners = listeners.get(event);
    if (eventListeners) {
        eventListeners.forEach(callback => {
            try {
                callback(data);
            } catch (e) {
                console.error(`[WebSocket] Listener error for ${event}:`, e);
            }
        });
    }
}

/**
 * Send a message to the server (emit)
 * @param {string} event - Event name
 * @param {any} data - Data to send
 */
export async function emit(event, data) {
    await connect();

    if (socket) {
        socket.emit(event, data);
    }
}

/**
 * Request job cancellation via WebSocket
 * @param {string} jobId - Job ID to cancel
 * @returns {Promise} Resolves with acknowledgment
 */
export function cancelJob(jobId) {
    return new Promise(async (resolve, reject) => {
        await connect();

        if (!socket) {
            reject(new Error('Not connected'));
            return;
        }

        // Listen for acknowledgment
        const handler = (data) => {
            if (data.job_id === jobId) {
                socket.off('cancel_job_ack', handler);
                resolve(data);
            }
        };

        socket.on('cancel_job_ack', handler);
        socket.emit('cancel_job', { job_id: jobId });

        // Timeout after 10 seconds
        setTimeout(() => {
            socket.off('cancel_job_ack', handler);
            reject(new Error('Cancel request timeout'));
        }, 10000);
    });
}

// ============================================================================
// Event Type Constants
// ============================================================================

export const EventTypes = {
    // Job events
    JOB_CREATED: 'job.created',
    JOB_UPDATED: 'job.updated',
    JOB_PROGRESS: 'job.progress',
    JOB_COMPLETED: 'job.completed',
    JOB_FAILED: 'job.failed',
    JOB_CANCELLED: 'job.cancelled',

    // Download events
    DOWNLOAD_STARTED: 'download.started',
    DOWNLOAD_PROGRESS: 'download.progress',
    DOWNLOAD_COMPLETED: 'download.completed',
    DOWNLOAD_FAILED: 'download.failed',

    // Provider events
    PROVIDER_STATUS: 'provider.status',
    PROVIDER_CONTAINER_STATUS: 'provider.container_status',
    PROVIDER_STATS_UPDATE: 'provider.stats_update',

    // Model status events (replaces sync-status polling)
    MODEL_STATUS_UPDATE: 'model.status_update',

    // Reconciliation events
    RECONCILIATION_STARTED: 'reconciliation.started',
    RECONCILIATION_PROGRESS: 'reconciliation.progress',
    RECONCILIATION_COMPLETED: 'reconciliation.completed',

    // Model sync events
    MODEL_SYNC_STARTED: 'model.sync_started',
    MODEL_SYNC_PROGRESS: 'model.sync_progress',
    MODEL_SYNC_COMPLETED: 'model.sync_completed',
    MODEL_SYNC_FAILED: 'model.sync_failed',
};

// ============================================================================
// React Hook for WebSocket
// ============================================================================

import { useEffect, useState, useCallback } from 'react';

/**
 * React hook for WebSocket connection and events
 * @param {string|string[]} topics - Topics to subscribe to
 * @returns {object} { isConnected, subscribe: fn, on: fn }
 */
export function useWebSocket(topics = []) {
    const [connected, setConnected] = useState(isConnected);

    useEffect(() => {
        // Connect on mount
        connect();

        // Subscribe to topics
        const topicArray = Array.isArray(topics) ? topics : [topics];
        if (topicArray.length > 0) {
            subscribe(topicArray);
        }

        // Track connection status
        const unsubConnection = on('connection', (data) => {
            setConnected(data.connected);
        });

        return () => {
            // Unsubscribe from topics on unmount
            if (topicArray.length > 0) {
                unsubscribe(topicArray);
            }
            unsubConnection();
        };
    }, [JSON.stringify(topics)]);

    // Stable callback for subscribing to events
    const subscribeToEvent = useCallback((event, callback) => {
        return on(event, callback);
    }, []);

    return {
        isConnected: connected,
        subscribe: subscribeToEvent,
        emit,
        cancelJob,
    };
}

// ============================================================================
// Default Export
// ============================================================================

export default {
    connect,
    disconnect,
    subscribe,
    unsubscribe,
    on,
    off,
    emit,
    cancelJob,
    getConnectionStatus,
    EventTypes,
    useWebSocket,
};
