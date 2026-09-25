import { useEffect, useRef, useCallback } from 'react';

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
        if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    }, []);

    const endUserActivity = useCallback(() => {
        scheduleIdleLoad();
    }, [scheduleIdleLoad]);

    useEffect(() => {
        const root = scrollRoot || window;
        const options = { passive: true };
        root.addEventListener('touchstart', markUserActivity, options);
        root.addEventListener('touchmove', markUserActivity, options);
        root.addEventListener('touchend', endUserActivity, options);
        root.addEventListener('touchcancel', endUserActivity, options);
        root.addEventListener('wheel', markUserActivity, options);
        root.addEventListener('scroll', markUserActivity, options);

        return () => {
            root.removeEventListener('touchstart', markUserActivity);
            root.removeEventListener('touchmove', markUserActivity);
            root.removeEventListener('touchend', endUserActivity);
            root.removeEventListener('touchcancel', endUserActivity);
            root.removeEventListener('wheel', markUserActivity);
            root.removeEventListener('scroll', markUserActivity);
            if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
        };
    }, [endUserActivity, markUserActivity, scrollRoot]);

    useEffect(() => {
        const currentSentinel = sentinelRef.current;
        if (!currentSentinel || !hasMore) return undefined;

        const observer = new IntersectionObserver(
            ([entry]) => {
                if (!entry.isIntersecting) return;
                if (isUserScrollingRef.current) {
                    pendingLoadRef.current = true;
                    return;
                }
                requestLoad();
            },
            {
                root: scrollRoot,
                rootMargin,
                threshold: 0.1,
            },
        );

        observer.observe(currentSentinel);
        return () => observer.disconnect();
    }, [hasMore, requestLoad, rootMargin, scrollRoot]);

    return sentinelRef;
}
