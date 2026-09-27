import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, act, cleanup } from '@testing-library/react';
import { useInfiniteScroll } from './useInfiniteScroll';

/**
 * The hook defers pagination until a scroll gesture ENDS — 180ms of inactivity.
 * It used to do the opposite: `wheel` and `scroll` set the "user is scrolling"
 * flag and CLEARED the idle timer, and only `touchend`/`touchcancel` re-armed
 * it. A mouse wheel fires neither of those, so the first wheel event latched the
 * flag for the rest of the session and the observer only ever set a pending
 * flag: infinite scroll was permanently dead on desktop.
 *
 * Real timers, because the behaviour under test is the timer. Rendered through
 * a real component, because the hook returns a ref the caller must attach to
 * the sentinel — with no attached node the observer effect bails out early and
 * the test would pass for the wrong reason.
 */

function Harness({ hasMore, onLoadMore, scrollRoot }) {
    const sentinelRef = useInfiniteScroll({ hasMore, loading: false, onLoadMore, rootMargin: '0px', scrollRoot });
    return <div data-testid="sentinel" ref={sentinelRef} />;
}

describe('useInfiniteScroll', () => {
    let onLoadMore;
    let originalIO;
    let callbacks;

    beforeEach(() => {
        onLoadMore = vi.fn();
        callbacks = [];
        originalIO = global.IntersectionObserver;
        // jsdom has no IntersectionObserver. Capture the callback so the test
        // decides when the sentinel is "visible".
        global.IntersectionObserver = class {
            constructor(cb) { callbacks.push(cb); }
            observe() {}
            disconnect() {}
            unobserve() {}
        };
    });

    afterEach(() => {
        cleanup();
        global.IntersectionObserver = originalIO;
    });

    const fire = (isIntersecting) =>
        act(() => { callbacks.forEach((cb) => cb([{ isIntersecting }])); });

    const waitPastIdle = () =>
        act(() => new Promise((resolve) => { setTimeout(resolve, 260); }));

    it('loads once the sentinel intersects and no gesture is in flight', async () => {
        render(<Harness hasMore onLoadMore={onLoadMore} />);
        await fire(true);
        expect(onLoadMore).toHaveBeenCalledTimes(1);
    });

    it('defers a mid-gesture intersection, then loads when a WHEEL gesture goes quiet', async () => {
        render(<Harness hasMore onLoadMore={onLoadMore} />);

        // A wheel event. This is the gesture with no "end" event — the case
        // that used to latch forever.
        await act(async () => { window.dispatchEvent(new Event('wheel')); });
        await fire(true);
        expect(onLoadMore).not.toHaveBeenCalled();

        // Gesture goes quiet for 180ms. Before the fix nothing re-armed the
        // timer, so this is exactly where it hung forever.
        await waitPastIdle();
        expect(onLoadMore).toHaveBeenCalledTimes(1);
    });

    it('defers for scroll events too, not just wheel', async () => {
        render(<Harness hasMore onLoadMore={onLoadMore} />);

        await act(async () => { window.dispatchEvent(new Event('scroll')); });
        await fire(true);
        expect(onLoadMore).not.toHaveBeenCalled();

        await waitPastIdle();
        expect(onLoadMore).toHaveBeenCalledTimes(1);
    });

    it('keeps deferring while activity continues, then loads once it stops', async () => {
        render(<Harness hasMore onLoadMore={onLoadMore} />);

        // A sustained gesture: repeated events, none of them an "end".
        for (let i = 0; i < 3; i++) {
            await act(async () => {
                window.dispatchEvent(new Event('wheel'));
                await new Promise((resolve) => { setTimeout(resolve, 100); });
            });
        }
        await fire(true);
        expect(onLoadMore).not.toHaveBeenCalled();

        await waitPastIdle();
        expect(onLoadMore).toHaveBeenCalledTimes(1);
    });

    it('still loads on touchend without waiting for the timer path twice', async () => {
        render(<Harness hasMore onLoadMore={onLoadMore} />);

        await act(async () => { window.dispatchEvent(new Event('touchstart')); });
        await fire(true);
        expect(onLoadMore).not.toHaveBeenCalled();

        await act(async () => { window.dispatchEvent(new Event('touchend')); });
        await waitPastIdle();
        expect(onLoadMore).toHaveBeenCalledTimes(1);
    });

    it('does not load when the sentinel is not intersecting', async () => {
        render(<Harness hasMore onLoadMore={onLoadMore} />);
        await fire(false);
        await waitPastIdle();
        expect(onLoadMore).not.toHaveBeenCalled();
    });

    it('does not load when there is nothing more to load', async () => {
        render(<Harness hasMore={false} onLoadMore={onLoadMore} />);
        await fire(true);
        await waitPastIdle();
        expect(onLoadMore).not.toHaveBeenCalled();
    });
});
