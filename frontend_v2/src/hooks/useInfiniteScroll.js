import { useEffect, useRef, useCallback } from 'react';
import { resolveScrollRoot } from './useScrollRoot';

const SCROLL_IDLE_MS = 180;

export function useInfiniteScroll({
    hasMore,
    onLoadMore,
    loading,
    rootMargin = '200px',
    scrollRoot = null,
} = {}) {
    const sentinelRef = useRef(null);
    const isLoadingRef = useRef(false);
    const isUserScrollingRef = useRef(false);
    const pendingLoadRef = useRef(false);
    // Whether the sentinel was intersecting last time we were told.
    const wasIntersectingRef = useRef(false);
    const lastCallTimeRef = useRef(0);
    const idleTimerRef = useRef(null);
    const debounceMs = 500;
    const retryTimerRef = useRef(null);

    /**
     * Re-attempt a dropped load shortly.
     *
     * Separate from the idle timer on purpose: this is not "the gesture ended",
     * it is "we could not go yet". Sharing the idle path made the two interfere —
     * the idle timer clears `isUserScrollingRef` and consumes itself, so a
     * debounced request could wait on a timer that had already fired and been
     * discarded.
     */
    //
    // The callback is a parameter rather than captured from a ref. `requestLoad`
    // needs `scheduleRetry` and `scheduleRetry` needs to call `requestLoad`, and
    // a parameter breaks that cycle with no ref and no effect-ordering
    // question — a ref written during render is what `react-hooks/immutability`
    // rejects, and writing it in an effect only moves the problem.
    const scheduleRetry = useCallback((delay, run) => {
        if (retryTimerRef.current) return;
        retryTimerRef.current = setTimeout(() => {
            retryTimerRef.current = null;
            if (pendingLoadRef.current) run?.();
        }, Math.max(16, delay));
    }, []);

    useEffect(() => {
        if (!loading) {
            const timer = setTimeout(() => {
                isLoadingRef.current = false;
            }, 100);
            return () => clearTimeout(timer);
        }
    }, [loading]);

    /* The actual load, with no guards.

       Split out so that `requestLoad` (which decides *whether* to load) and the
       retry timer (which only needs to *do* it) can both reach it without a
       cycle. A self-reference, or a ref written during render, are the two ways
       to tie that knot and both are rejected — the first by
       `react-hooks/immutability`, the second because it is not safe. Passing the
       function into `scheduleRetry` keeps the dependency graph a straight line:
       `scheduleRetry` -> `load` -> `onLoadMore`.
    */
    const load = useCallback(() => {
        if (!hasMore) {
            pendingLoadRef.current = false;
            return;
        }
        pendingLoadRef.current = false;
        isLoadingRef.current = true;
        lastCallTimeRef.current = Date.now();
        onLoadMore();
    }, [hasMore, onLoadMore]);

    const requestLoad = useCallback(() => {
        if (!hasMore) {
            pendingLoadRef.current = false;
            return;
        }
        if (isLoadingRef.current || loading) {
            // A load is already in flight. The observer will not fire again on
            // its own — it reports threshold crossings, and the sentinel is
            // still intersecting — so record that another page is wanted and let
            // the settle re-check pick it up.
            pendingLoadRef.current = true;
            return;
        }
        const sinceLast = Date.now() - lastCallTimeRef.current;
        if (sinceLast < debounceMs) {
            /* Dropped on the debounce, and this is the "it gets stuck and will
               not load more" bug.

               This used to return silently. But the sentinel is still
               intersecting and an IntersectionObserver only reports threshold
               *crossings*, so once it is intersecting there is nothing left to
               fire. And `scheduleIdleLoad` consumes its own timer
               (`idleTimerRef.current = null`) and only re-arms on a scroll
               event — so a request dropped here was lost permanently. The user
               sits at the bottom of the gallery and no amount of waiting loads
               another page, until they scroll away and back to manufacture a
               crossing.

               So a dropped request re-arms itself for the moment the debounce
               expires. `pendingLoadRef` is left set too, so the idle path and
               this one agree that work is outstanding. */
            pendingLoadRef.current = true;
            scheduleRetry(debounceMs - sinceLast, load);
            return;
        }
        load();
    }, [debounceMs, hasMore, load, loading, scheduleRetry]);

    /* Re-check when a load settles.

       An IntersectionObserver reports threshold *crossings*. If the page that
       just loaded is shorter than the remaining space, the sentinel is still
       intersecting when the request finishes, so no new crossing occurs and
       nothing asks for the page after it — the gallery stops early even though
       `hasMore` is true. Re-checking on the `loading` edge covers that, and is
       also the safety net for any other dropped request.
    */
    useEffect(() => {
        if (loading) return;
        if (!hasMore) return;
        // Only after a page has actually been requested. Without this the check
        // fires on mount, which is both a wasted request — the observer is about
        // to ask anyway — and it made the timing of everything downstream depend
        // on whether the view had mounted yet.
        if (!lastCallTimeRef.current) return;
        const sentinel = sentinelRef.current;
        if (!sentinel) return;
        const root = resolveScrollRoot(sentinel, scrollRoot) ?? window;
        const rect = sentinel.getBoundingClientRect();
        const bounds = root === window
            ? { top: 0, bottom: window.innerHeight }
            : (() => { const r = root.getBoundingClientRect(); return { top: r.top, bottom: r.bottom }; })();
        /* Within the load margin, not merely on screen.

           The IntersectionObserver is configured with `rootMargin` (200px by
           default), so it fires when the sentinel is still 200px *below* the
           fold. This re-check originally asked only "is any part of the sentinel
           visible", which is a much weaker condition and fired sooner than the
           observer does — a slow scroll lingering near the bottom could pull a
           page before the observer would have. Same margin, same threshold, so
           the two paths agree on when "the end is near" means.
        */
        const margin = parseFloat(rootMargin) || 0;
        const visible = rect.top < bounds.bottom + margin && rect.bottom > bounds.top - margin;
        if (visible) {
            pendingLoadRef.current = true;
            // Consume the latch: this is a deliberate request, so the sentinel
            // must be allowed to cross again afterwards.
            wasIntersectingRef.current = false;
            scheduleRetry(0, load);
        }
    }, [load, loading, hasMore, rootMargin, scrollRoot, scheduleRetry]);

    const scheduleIdleLoad = useCallback(() => {
        if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
        idleTimerRef.current = setTimeout(() => {
            idleTimerRef.current = null;
            isUserScrollingRef.current = false;
            if (pendingLoadRef.current) requestLoad();
        }, SCROLL_IDLE_MS);
    }, [requestLoad]);

    const markUserActivity = useCallback(() => {
        isUserScrollingRef.current = true;
        // Re-arm the idle timer, do not clear it. There is no "wheel end" or
        // "scroll end" event, so the only way to detect that a gesture has
        // finished is to keep pushing the deadline out while events keep
        // arriving. This used to clear the timer here and rely on
        // touchend/touchcancel to re-arm it, which meant a mouse wheel -
        // which never fires either - latched isUserScrollingRef to true after
        // the first event and infinite scroll never fired again for the rest
        // of the session.
        scheduleIdleLoad();
    }, [scheduleIdleLoad]);

    const endUserActivity = useCallback(() => {
        scheduleIdleLoad();
    }, [scheduleIdleLoad]);

    useEffect(() => {
        const currentSentinel = sentinelRef.current;
        // The element that ACTUALLY SCROLLS, not the viewport.
        //
        // The gallery's list lives inside `Layout`'s
        // `flex-1 relative z-10 lg:overflow-y-auto` pane, ~1400px below the top
        // of the window (failed-jobs banner, header, toolbar, search, the date
        // rail, the filter panel). With `root: null` the observer measures against
        // the VIEWPORT, so all of that chrome is outside the root rect and
        // `rootMargin` expands the viewport rather than the pane — the sentinel
        // only counts as "near" once it has been scrolled well past the fold.
        // The list then has to grow a whole viewport before the next page is
        // asked for, which reads as infinite scroll not working. The model
        // selector's grid starts at the top of its pane, so the same code felt
        // instant there and broken here: nothing was broken, the trigger was
        // simply measured against the wrong box.
        //
        // Falls back to the viewport when the sentinel has no scrollable
        // ancestor, so a sentinel in normal document flow behaves as before.
        const root = resolveScrollRoot(currentSentinel, scrollRoot) ?? window;

        // Gesture listeners belong on the same root as the observer. They were
        // bound to `window` unconditionally, so on the gallery the wheel and
        // scroll events that drive the idle timer never fired at all: every load
        // had to go through the `pendingLoadRef` path instead, and the one
        // wheel gesture that should have been enough was not.
        const options = { passive: true };
        root.addEventListener('touchstart', markUserActivity, options);
        root.addEventListener('touchmove', markUserActivity, options);
        root.addEventListener('touchend', endUserActivity, options);
        root.addEventListener('touchcancel', endUserActivity, options);
        root.addEventListener('wheel', markUserActivity, options);
        root.addEventListener('scroll', markUserActivity, options);

        let observer = null;
        if (currentSentinel && hasMore) {
            observer = new IntersectionObserver(
                ([entry]) => {
                    /* Only act on a false -> true transition.

                       An IntersectionObserver reports threshold crossings, but a
                       crossing can be produced by anything that moves the
                       sentinel — including the list's own geometry being wrong,
                       which is the state the gallery is in below `lg`. When that
                       happens the sentinel jitters across the threshold on every
                       scroll frame and each one fires a callback, so treating
                       "intersecting" as the trigger means a page request per
                       frame instead of per crossing.

                       Measured on a 390px viewport: 20 ordinary scrolls through
                       the middle of the list produced 8 assets requests, all to
                       the paginated endpoint, at a point nowhere near the end.
                       Gating on the transition means jitter while it stays
                       visible cannot request anything. */
                    const was = wasIntersectingRef.current;
                    wasIntersectingRef.current = entry.isIntersecting;
                    if (!entry.isIntersecting) return;
                    if (was) return;
                    if (isUserScrollingRef.current) {
                        pendingLoadRef.current = true;
                        return;
                    }
                    requestLoad();
                },
                {
                    root: resolveScrollRoot(currentSentinel, scrollRoot),
                    rootMargin,
                    threshold: 0.1,
                },
            );
            observer.observe(currentSentinel);
        }

        return () => {
            root.removeEventListener('touchstart', markUserActivity);
            root.removeEventListener('touchmove', markUserActivity);
            root.removeEventListener('touchend', endUserActivity);
            root.removeEventListener('touchcancel', endUserActivity);
            root.removeEventListener('wheel', markUserActivity);
            root.removeEventListener('scroll', markUserActivity);
            observer?.disconnect();
            if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
            if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
        };
    }, [endUserActivity, hasMore, markUserActivity, requestLoad, rootMargin, scrollRoot]);

    return sentinelRef;
}
