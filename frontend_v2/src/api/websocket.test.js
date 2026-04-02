import { beforeEach, describe, expect, it, vi } from 'vitest';


class FakeSocket {
    constructor() {
        this.id = 'socket-1';
        this._listeners = new Map();
        this.emit = vi.fn();
        this.disconnect = vi.fn();
    }

    on(event, callback) {
        const callbacks = this._listeners.get(event) || [];
        callbacks.push(callback);
        this._listeners.set(event, callbacks);
        return this;
    }

    off(event, callback) {
        if (!this._listeners.has(event)) {
            return this;
        }
        const callbacks = this._listeners.get(event).filter((fn) => fn !== callback);
        this._listeners.set(event, callbacks);
        return this;
    }

    listeners(event) {
        return this._listeners.get(event) || [];
    }

    trigger(event, payload) {
        for (const callback of this.listeners(event)) {
            callback(payload);
        }
    }
}


let fakeSocket;

vi.mock('socket.io-client', () => ({
    io: vi.fn(() => {
        fakeSocket = new FakeSocket();
        return fakeSocket;
    }),
}));

vi.mock('./config', () => ({
    getApiUrl: () => 'http://localhost:8002',
}));


describe('websocket listener registration', () => {
    beforeEach(async () => {
        vi.resetModules();
        fakeSocket = null;
    });

    it('does not register the same callback twice on an active socket', async () => {
        const ws = await import('./websocket.js');
        const callback = vi.fn();

        const connectPromise = ws.connect();
        fakeSocket.trigger('connect');
        await connectPromise;

        ws.on(ws.EventTypes.JOB_PROGRESS, callback);
        ws.on(ws.EventTypes.JOB_PROGRESS, callback);

        expect(fakeSocket.listeners(ws.EventTypes.JOB_PROGRESS)).toHaveLength(1);
    });

    it('does not duplicate listeners when reconnecting', async () => {
        const ws = await import('./websocket.js');
        const callback = vi.fn();

        const connectPromise = ws.connect();
        fakeSocket.trigger('connect');
        await connectPromise;

        ws.on(ws.EventTypes.JOB_COMPLETED, callback);
        expect(fakeSocket.listeners(ws.EventTypes.JOB_COMPLETED)).toHaveLength(1);

        fakeSocket.trigger('connect');

        expect(fakeSocket.listeners(ws.EventTypes.JOB_COMPLETED)).toHaveLength(1);
    });

    it('rejects failed initial connection and supports retry', async () => {
        const ws = await import('./websocket.js');

        const failedConnect = ws.connect();
        fakeSocket.trigger('connect_error', { message: 'connection failed' });

        await expect(failedConnect).rejects.toThrow('connection failed');

        const retryConnect = ws.connect();
        fakeSocket.trigger('connect');

        await expect(retryConnect).resolves.toBeDefined();
    });

    it('defines a post-processing job event type constant', async () => {
        const ws = await import('./websocket.js');
        expect(ws.EventTypes.JOB_POST_PROCESSING).toBe('job.post_processing');
    });
});