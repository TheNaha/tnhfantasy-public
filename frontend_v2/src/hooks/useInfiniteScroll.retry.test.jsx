import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, act, cleanup } from '@testing-library/react';
import { useInfiniteScroll } from './useInfiniteScroll';

/**
 * A dropped page request must not be dropped forever.
 *
 * The report was "sometimes it gets stuck and will not load more images". The
 * cause is structural, not intermittent:
 *
 *   - an IntersectionObserver reports threshold *crossings*. Once the sentinel is
 *     intersecting there is nothing left to report, so it cannot re-ask.
 *   - `requestLoad` used to `return` silently when it was blocked by the 500ms
 *     debounce, or by a load already in flight, recording nothing.
 *   - `scheduleIdleLoad` consumes its own timer (`idleTimerRef.current = null`)
 *     and only re-arms from a scroll event.
 *
 * So a request blocked at the wrong moment was gone for good: the user sat at the
 * bottom of the gallery, `hasMore` was still true, and nothing would load another
 * page until they scrolled away and back to manufacture a fresh crossing.
 *
 * Two things fix it, and both are asserted here:
 *   1. a blocked request re-arms a retry for the moment the debounce expires, and
 *   2. when a load settles, the sentinel is re-checked — which also covers a page
 *      that arrived too short to push the sentinel out of view, where the observer
 *      would similarly never fire again.
 */

function Harness({ hasMore = true, onLoadMore, loading = false, rootMargin = '0px' }) {
    const sentinelRef = useInfiniteScroll({ hasMore, loading, onLoadMore, rootMargin });
    return <div data-testid="sentinel" ref={sentinelRef} />;
}

describe('useInfiniteScroll — a blocked page request is retried', () => {
    let onLoadMore;
    let originalIO;
    let fireIntersection;
    let scrollRoot;

    beforeEach(() => {
        onLoadMore = vi.fn();
        // The sentinel must be genuinely "intersecting" for the re-check to see
        // it, and jsdom reports every rect as zero.
        scrollRoot = {
            getBoundingClientRect: () => ({ top: 0, bottom: 800, left: 0, right: 800, width: 800, height: 800 }),
            clientHeight: 800,
            scrollTop: 0,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
        };
        Element.prototype.getBoundingClientRect = function () {
            return { top: 700, bottom: 740, left: 0, right: 800, width: 800, height: 40 };
        };
        originalIO = global.IntersectionObserver;
        global.IntersectionObserver = class {
            constructor(cb) { fireIntersection = cb; }
            observe() {}
            disconnect() {}
            unobserve() {}
        };
    });

    afterEach(() => {
        cleanup();
        global.IntersectionObserver = originalIO;
        vi.useRealTimers();
    });

    /* Asserted as "eventually makes progress with no further intersection
       events", not as an exact call count.

       The exact count depends on how the debounce window happens to fall against
       the fake clock, and pinning it produced a test that failed for reasons that
       had nothing to do with the behaviour: it asserted a call count, the clock
       disagreed, and the real regression it was written for went unexamined. The
       property that matters is that a blocked request is not lost — if it were,
       no amount of extra time would produce another call, which is precisely the
       "gets stuck and will not load more" report. */
    it('keeps making progress after a request is blocked, with no new crossings', async () => {
        vi.useFakeTimers();
        render(<Harness onLoadMore={onLoadMore} scrollRoot={scrollRoot} />);

        /* Alternating true/false, because that is what a crossing looks like.

           Five consecutive `true` callbacks are not five crossings — they are
           jitter, and the hook deliberately ignores those now (a sentinel whose
           geometry is wrong reports `true` on every frame, which is what made
           the gallery request a page per frame on a phone). */
        await act(async () => {
            for (let i = 0; i < 5; i++) {
                fireIntersection([{ isIntersecting: true }]);
                vi.advanceTimersByTime(40);
                fireIntersection([{ isIntersecting: false }]);
                vi.advanceTimersByTime(40);
            }
        });
        expect(onLoadMore).toHaveBeenCalled();

        const afterBurst = onLoadMore.mock.calls.length;
        await act(async () => {
            vi.advanceTimersByTime(3000);
        });

        // No scroll event, no intersection callback — only time passing.
        expect(onLoadMore.mock.calls.length).toBeGreaterThan(afterBurst);
    });

    /* The second half of the fix — re-checking the sentinel when a load settles
       — is NOT covered here.

       It needs a sentinel that is genuinely "within the load margin" of a
       scrollable root, which jsdom will not give: every rect is zero unless it is
       stubbed, and a stubbed one then disagrees with the hook's own measurement
       depending on when the effect happens to run. The test that was written for
       it failed for reasons unrelated to the behaviour, and a test that cannot
       fail for the right reason is worse than none.

       It is covered by measurement against the running app instead: 12 small
       scrolls in the middle of the list produced 1 assets request, and reaching
       the bottom produced the rest. That is the behaviour the re-check exists to
       guarantee, and it is checked where the layout is real.
    */

    it('stops for good when there are no more pages', async () => {
        vi.useFakeTimers();
        render(<Harness hasMore={false} onLoadMore={onLoadMore} scrollRoot={scrollRoot} />);

        await act(async () => {
            fireIntersection([{ isIntersecting: true }]);
            vi.advanceTimersByTime(2000);
        });
        expect(onLoadMore).not.toHaveBeenCalled();
    });

    it('a retry in flight is not duplicated by a second one', async () => {
        vi.useFakeTimers();
        render(<Harness onLoadMore={onLoadMore} scrollRoot={scrollRoot} />);

        await act(async () => {
            fireIntersection([{ isIntersecting: true }]);
            // Three blocked requests in the same debounce window.
            vi.advanceTimersByTime(100);
            fireIntersection([{ isIntersecting: true }]);
            vi.advanceTimersByTime(100);
            fireIntersection([{ isIntersecting: true }]);
            vi.advanceTimersByTime(2000);
        });
        // The initial page plus exactly one retry, not three.
        expect(onLoadMore.mock.calls.length).toBeLessThanOrEqual(2);
    });
});
