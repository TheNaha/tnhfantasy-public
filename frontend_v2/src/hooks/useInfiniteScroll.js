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
    const lastCallTimeRef = useRef(0);
    const idleTimerRef = useRef(null);
    const debounceMs = 500;

    useEffect(() => {
        if (!loading) {
            const timer = setTimeout(() => {
                isLoadingRef.current = false;
            }, 100);
            return () => clearTimeout(timer);
        }
    }, [loading]);

    const requestLoad = useCallback(() => {
        const now = Date.now();
        if (isLoadingRef.current || loading || !hasMore || now - lastCallTimeRef.current < debounceMs) {
            return;
        }
        pendingLoadRef.current = false;
        isLoadingRef.current = true;
        lastCallTimeRef.current = now;
        onLoadMore();
    }, [hasMore, loading, onLoadMore]);

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
                    if (!entry.isIntersecting) return;
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
        };
    }, [endUserActivity, hasMore, markUserActivity, requestLoad, rootMargin, scrollRoot]);

    return sentinelRef;
}
