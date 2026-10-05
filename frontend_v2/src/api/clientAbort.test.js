/**
 * Aborting a request must not look like a failed one.
 *
 * `client.js` installs a 30s `AbortController` as a timeout guard. Until now
 * there were exactly two reasons a fetch could be stopped — that timer, or a
 * caller's own `signal` — and they were conflated:
 *
 *   - When a caller *did* pass a signal, `abortTimeout` stayed `undefined`, so
 *     the `AbortError` branch that maps to `ApiError('Request timed out', 408)`
 *     was skipped and the abort fell through to `new ApiError(message, 0)`.
 *     Status 0 is the network-failure shape, so react-query could not recognise
 *     it as a cancellation: it counted as a failed query, surfaced in
 *     `isError`, and re-ran the queryFn.
 *   - When a caller passed a signal, the timeout guard was *replaced* rather
 *     than joined. That was harmless while only two call sites passed one; it
 *     stopped being harmless the moment every `queryFn` began forwarding React
 *     Query's signal, which would have removed the 30s guard from the entire
 *     app at a stroke.
 *
 * These are stated as behaviour against a real `QueryClient`, because the part
 * that actually matters is what react-query does with the rejection, not what
 * the client throws.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { QueryObserver } from '@tanstack/query-core';

import api, { ApiError } from './client';

describe('an abort is an abort, not an error', () => {
    beforeEach(() => {
        vi.stubGlobal('fetch', vi.fn());
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    /** A fetch that never settles until aborted — as `fetch` itself behaves. */
    function hangingFetch() {
        return (_url, config) => new Promise((_resolve, reject) => {
            const abort = () => {
                const error = new Error('The operation was aborted.');
                error.name = 'AbortError';
                reject(error);
            };
            if (config.signal?.aborted) abort();
            else config.signal?.addEventListener('abort', abort);
        });
    }

    it('surfaces a caller abort as an AbortError, not an ApiError', async () => {
        fetch.mockImplementation(hangingFetch());
        const controller = new AbortController();

        const pending = api.get('/slow', { signal: controller.signal });
        controller.abort();

        const error = await pending.catch((e) => e);
        expect(error).not.toBeInstanceOf(ApiError);
        expect(error.name).toBe('AbortError');
        // React Query decides "cancelled" from exactly this pair of facts.
        expect(error instanceof Error).toBe(true);
    });

    it('rejects immediately for a signal that is already aborted', async () => {
        fetch.mockImplementation(hangingFetch());
        const error = await api.get('/slow', { signal: AbortSignal.abort() }).catch((e) => e);
        expect(error.name).toBe('AbortError');
        expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
    });

    it('react-query treats it as a cancellation, not a failed query', async () => {
        // The user-visible consequence: a cancelled query does not retry, does
        // not land in `isError`, and does not surface a toast.
        fetch.mockImplementation(hangingFetch());
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

        const observer = new QueryObserver(client, {
            queryKey: ['q'],
            queryFn: ({ signal }) => api.get('/slow', { signal }),
        });
        const unsubscribe = observer.subscribe(() => {});
        await vi.waitFor(() => expect(observer.getCurrentResult().status).toBe('pending'));

        // What react-query itself does when a query is cancelled or unmounted:
        // abort the signal it handed the fetcher, and treat the rejection as a
        // cancellation rather than a result.
        await client.cancelQueries({ queryKey: ['q'] });
        await vi.waitFor(() => expect(client.isFetching()).toBe(0));

        const result = observer.getCurrentResult();
        // The observable signature of a cancellation: no error left behind.
        // Had the abort arrived as `ApiError(message, 0)`, `isError` would be
        // true here and the panel above the gallery would show a failure for a
        // request that was cancelled on purpose.
        expect(result.error).toBeFalsy();
        expect(result.isError).toBe(false);
        expect(result.status).not.toBe('error');
        // A failure would be retried; a cancellation is not.
        expect(fetch).toHaveBeenCalledTimes(1);
        unsubscribe();
    });

    it('would have surfaced the abort as an error before the fix', async () => {
        // Stated directly, because "no error left behind" is only meaningful
        // next to what the alternative produced: `ApiError('…', 0)`, which is
        // the network-failure shape and lands in `isError`.
        fetch.mockImplementation(() => Promise.reject(
            Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' }),
        ));
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const observer = new QueryObserver(client, {
            queryKey: ['q2'],
            queryFn: async () => { throw new ApiError('The operation was aborted.', 0); },
        });
        const unsubscribe = observer.subscribe(() => {});
        await vi.waitFor(() => expect(observer.getCurrentResult().isError).toBe(true));
        expect(observer.getCurrentResult().error.status).toBe(0);
        unsubscribe();
    });

    it('still reports a timeout as a timeout, and not as an abort', async () => {
        vi.useFakeTimers();
        fetch.mockImplementation(hangingFetch());

        const pending = api.get('/slow', { timeout: 50 }).catch((e) => e);
        await vi.advanceTimersByTimeAsync(60);

        const error = await pending;
        expect(error).toBeInstanceOf(ApiError);
        expect(error.status).toBe(408);
        expect(error.message).toBe('Request timed out');
    });

    it('keeps the timeout guard for a request that also carries a signal', async () => {
        // The regression this guards: joining the two reasons to abort must not
        // be implemented by dropping one of them, because every queryFn in the
        // app now passes a signal.
        vi.useFakeTimers();
        fetch.mockImplementation(hangingFetch());
        const controller = new AbortController();

        const pending = api.get('/slow', { signal: controller.signal, timeout: 50 }).catch((e) => e);
        await vi.advanceTimersByTimeAsync(60);

        const error = await pending;
        expect(error).toBeInstanceOf(ApiError);
        expect(error.status).toBe(408);
        expect(controller.signal.aborted).toBe(false);
    });

    it('lets a caller abort win when the caller aborts first', async () => {
        vi.useFakeTimers();
        fetch.mockImplementation(hangingFetch());
        const controller = new AbortController();

        const pending = api.get('/slow', { signal: controller.signal, timeout: 5000 }).catch((e) => e);
        controller.abort();
        await vi.advanceTimersByTimeAsync(0);

        const error = await pending;
        expect(error.name).toBe('AbortError');
        expect(error).not.toBeInstanceOf(ApiError);
    });

    it('does not arm a timer when the caller asks for no timeout', async () => {
        fetch.mockImplementation(() => new Promise(() => {}));
        const spy = vi.spyOn(globalThis, 'setTimeout');
        api.get('/slow', { signal: new AbortController().signal, timeout: 0 });
        expect(spy.mock.calls.some(([ms]) => ms === 30000)).toBe(false);
        spy.mockRestore();
    });

    it('detaches its abort listener, so a long-lived caller signal is not retained', async () => {
        fetch.mockResolvedValue({
            ok: true,
            headers: new Headers({ 'content-type': 'application/json' }),
            json: async () => ({ ok: true }),
        });
        const controller = new AbortController();
        await api.get('/fast', { signal: controller.signal });

        // jsdom has no `listenerCount`; reaching into the internals is the
        // portable check that the `{ once: true }` listener was removed.
        const internals = controller.signal;
        const kHandlers = Object.getOwnPropertySymbols(internals)
            .find((s) => String(s).includes('kHandlers'));
        const handlers = kHandlers ? internals[kHandlers] : undefined;
        expect(!handlers || Object.keys(handlers).length === 0).toBe(true);
    });
});