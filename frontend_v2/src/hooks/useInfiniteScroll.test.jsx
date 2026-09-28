import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, act, cleanup, waitFor } from '@testing-library/react';
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

describe('the observer root', () => {
    // The regression this pins: the observer was created with `root: null`, which
    // means the viewport. The gallery's list sits ~1400px down inside Layout's
    // `lg:overflow-y-auto` pane, so the chrome above it — banner, header,
    // toolbar, date rail, filter panel — sat outside the root rect, `rootMargin`
    // expanded the viewport instead of the pane, and the sentinel only counted as
    // "near" once it had been scrolled a whole viewport past the fold. The list
    // had to grow by a full screen before the next page was requested, which
    // looks exactly like infinite scroll not working.
    function stubIntersectionObserver(collect) {
        const RealIO = global.IntersectionObserver;
        class FakeIO {
            constructor(_cb, opts) { collect(opts.root); }
            observe() {}
            disconnect() {}
        }
        global.IntersectionObserver = FakeIO;
        return () => { global.IntersectionObserver = RealIO; };
    }

    it('observes the sentinel scrollable ancestor rather than the viewport', async () => {
        const roots = [];
        const restore = stubIntersectionObserver((r) => roots.push(r));
        const scroller = document.createElement('div');
        scroller.style.overflowY = 'auto';
        document.body.appendChild(scroller);

        function Probe() {
            const sentinelRef = useInfiniteScroll({
                hasMore: true, onLoadMore: () => {}, loading: false,
            });
            return <div ref={sentinelRef} data-testid="sentinel" />;
        }
        // The hook resolves its root from the sentinel's own ancestry, so the
        // sentinel has to be mounted inside the scroller.
        const into = document.createElement('div');
        scroller.appendChild(into);
        into.appendChild(document.createElement('div')); // placeholder so React has a parent
        const { rerender } = render(<Probe />, { container: into });
        rerender(<Probe />);

        await waitFor(() => expect(roots.length).toBeGreaterThan(0));
        expect(roots[0]).toBe(scroller);

        cleanup();
        scroller.remove();
        restore();
    });

    it('falls back to the viewport when nothing above the sentinel scrolls', async () => {
        const roots = [];
        const restore = stubIntersectionObserver((r) => roots.push(r));

        function Probe() {
            const sentinelRef = useInfiniteScroll({
                hasMore: true, onLoadMore: () => {}, loading: false,
            });
            return <div ref={sentinelRef} data-testid="plain" />;
        }
        render(<Probe />);

        await waitFor(() => expect(roots.length).toBeGreaterThan(0));
        // A sentinel in normal document flow keeps the old behaviour: `null`
        // means "use the viewport" to IntersectionObserver.
        expect(roots[0]).toBeNull();

        cleanup();
        restore();
    });
});
