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
import { useEffect, useMemo, useState, useCallback } from 'react';
import { getApiUrl, DEFAULT_API_URL } from './config';

function getSocketBaseUrl() {
    if (import.meta.env.DEV) {
        return '';
    }
    const apiUrl = getApiUrl();
    if (apiUrl && apiUrl !== DEFAULT_API_URL) {
        return apiUrl;
    }
    return '';
}

// WebSocket connection instance
let socket = null;

// Connection state
let isConnected = false;
let connectionPromise = null;

// Event listeners by event name
const listeners = new Map();

// Subscribed topics with reference counts so one consumer cannot unsubscribe another.
const subscribedTopics = new Map();


function registerSocketListener(event, callback) {
    if (!socket) {
        return;
    }

    if (!socket.listeners(event).includes(callback)) {
        socket.on(event, callback);
    }
}

/**
 * Initialize WebSocket connection
 * @returns {Promise} Resolves when connected
 */
export function connect() {
    if (connectionPromise) {
        return connectionPromise;
    }

    // If socket exists but isn't connected, it's reconnecting — wait for it
    if (socket && !isConnected) {
        connectionPromise = new Promise((resolve, reject) => {
            let settled = false;
            const settle = (fn, value) => {
                if (!settled) { settled = true; fn(value); }
            };
            const onConnect = () => settle(resolve, socket);
            const onError = (err) => settle(reject, err instanceof Error ? err : new Error(err?.message || 'reconnect error'));
            socket.once('connect', onConnect);
            socket.once('connect_error', onError);
        });
        return connectionPromise;
    }

    if (socket && isConnected) {
        return Promise.resolve(socket);
    }

    connectionPromise = new Promise((resolve, reject) => {
        if (socket && isConnected) {
            resolve(socket);
            return;
        }

        let settled = false;
        const resolveConnection = (value) => {
            if (settled) {
                return;
            }
            settled = true;
            resolve(value);
        };
        const rejectConnection = (error) => {
            if (settled) {
                return;
            }
            settled = true;
            reject(error);
        };

        // Create Socket.IO connection
        socket = io(getSocketBaseUrl(), {
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
            const activeTopics = Array.from(subscribedTopics.entries())
                .filter(([, count]) => count > 0)
                .map(([topic]) => topic);
            if (activeTopics.length > 0) {
                socket.emit('subscribe', { topics: activeTopics });
            }

            // Re-register all pending listeners with the new socket connection
            // This is critical for mobile reconnection where the socket instance is reused
            // but event handlers may have been cleared
            listeners.forEach((callbacks, event) => {
                callbacks.forEach(callback => {
                    registerSocketListener(event, callback);
                });
            });

            // Notify connection listeners
            emitLocal('connection', { connected: true, id: socket.id });
            resolveConnection(socket);
        });

        socket.on('disconnect', (reason) => {
            console.log('[WebSocket] Disconnected:', reason);
            isConnected = false;
            connectionPromise = null;
            emitLocal('connection', { connected: false, reason });
        });

        socket.on('connect_error', (error) => {
            console.warn('[WebSocket] Connection error:', error.message);
            emitLocal('connection', { connected: false, error: error.message });

            // Reject the initial connection promise if it hasn't resolved yet.
            // Do NOT destroy the socket — let Socket.IO's built-in reconnection handle retries.
            if (!settled) {
                connectionPromise = null;
                rejectConnection(error instanceof Error ? error : new Error(error?.message || 'WebSocket connection error'));
            }
        });

        socket.on('connected', ({ message }) => {
            console.log('[WebSocket] Server welcome:', message);
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
        socket.on('pong', () => {
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
    const topicsToSubscribe = [];

    topicArray.forEach((topic) => {
        const currentCount = subscribedTopics.get(topic) || 0;
        subscribedTopics.set(topic, currentCount + 1);
        if (currentCount === 0) {
            topicsToSubscribe.push(topic);
        }
    });

    // Ensure connected
    await connect();

    if (socket && topicsToSubscribe.length > 0) {
        socket.emit('subscribe', { topics: topicsToSubscribe });
    }
}

/**
 * Unsubscribe from a topic (leave a room)
 * @param {string|string[]} topics - Topic(s) to unsubscribe from
 */
export function unsubscribe(topics) {
    const topicArray = Array.isArray(topics) ? topics : [topics];
    const topicsToUnsubscribe = [];

    topicArray.forEach((topic) => {
        const currentCount = subscribedTopics.get(topic) || 0;
        if (currentCount <= 1) {
            subscribedTopics.delete(topic);
            topicsToUnsubscribe.push(topic);
        } else {
            subscribedTopics.set(topic, currentCount - 1);
        }
    });

    if (socket && topicsToUnsubscribe.length > 0) {
        socket.emit('unsubscribe', { topics: topicsToUnsubscribe });
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
        registerSocketListener(event, callback);
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
 * Request replay of missed events from the server's replay buffer.
 * @param {number} lastSequenceNumber - The last sequence number the client received
 * @returns {Promise} Resolves with the replay events array
 */
export function requestReplay(lastSequenceNumber) {
    return connect().then(() => new Promise((resolve, reject) => {
        if (!socket) {
            reject(new Error('Not connected'));
            return;
        }

        let timeoutId = null;

        const cleanup = () => {
            if (timeoutId) clearTimeout(timeoutId);
            socket.off('replay_events', handler);
            socket.off('error', errorHandler);
        };

        const handler = (data) => {
            cleanup();
            resolve(data?.events || []);
        };

        const errorHandler = (data) => {
            cleanup();
            reject(new Error(data?.message || 'Replay request failed'));
        };

        socket.on('replay_events', handler);
        socket.on('error', errorHandler);
        socket.emit('request_replay', { last_sequence_number: lastSequenceNumber });

        timeoutId = setTimeout(() => {
            cleanup();
            reject(new Error('Replay request timeout'));
        }, 10000);
    }));
}

/**
 * Dispatch replayed events to registered listeners.
 * Re-emits each event locally so that handlers registered via on() receive them.
 * @param {Array} events - Array of replayed event objects
 */
export function dispatchReplayEvents(events) {
    if (!events || events.length === 0) return;
    events.forEach(event => {
        if (event?.type) {
            emitLocal(event.type, event);
        }
    });
}

/**
 * Request job cancellation via WebSocket
 * @param {string} jobId - Job ID to cancel
 * @returns {Promise} Resolves with acknowledgment
 */
export function cancelJob(jobId) {
    return connect().then(() => new Promise((resolve, reject) => {
        if (!socket) {
            reject(new Error('Not connected'));
            return;
        }

        let timeoutId = null;

        const cleanup = () => {
            if (timeoutId) {
                clearTimeout(timeoutId);
            }
            socket.off('cancel_job_ack', handler);
        };

        // Listen for acknowledgment
        const handler = (data) => {
            if (data.job_id === jobId) {
                cleanup();
                resolve(data);
            }
        };

        socket.on('cancel_job_ack', handler);
        socket.emit('cancel_job', { job_id: jobId });

        // Timeout after 10 seconds
        timeoutId = setTimeout(() => {
            cleanup();
            reject(new Error('Cancel request timeout'));
        }, 10000);
    }));
}

// ============================================================================
// Event Type Constants
// ============================================================================

export const EventTypes = {
    // Job events
    JOB_CREATED: 'job.created',
    JOB_UPDATED: 'job.updated',
    JOB_PROGRESS: 'job.progress',
    JOB_POST_PROCESSING: 'job.post_processing',
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

/**
 * React hook for WebSocket connection and events
 * @param {string|string[]} topics - Topics to subscribe to
 * @returns {object} { isConnected, subscribe: fn, on: fn }
 */
export function useWebSocket(topics = []) {
    const [connected, setConnected] = useState(isConnected);
    const topicArray = useMemo(() => (Array.isArray(topics) ? topics : [topics]), [topics]);

    useEffect(() => {
        // Connect on mount
        connect().catch((error) => {
            console.warn('[WebSocket] Initial connect failed:', error?.message || error);
        });

        // Subscribe to topics
        if (topicArray.length > 0) {
            subscribe(topicArray).catch((error) => {
                console.warn('[WebSocket] Initial subscribe failed:', error?.message || error);
            });
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
    }, [topicArray]);

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
    requestReplay,
    dispatchReplayEvents,
    getConnectionStatus,
    EventTypes,
    useWebSocket,
};
