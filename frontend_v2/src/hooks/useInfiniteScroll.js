import { useEffect, useRef, useCallback } from 'react';

/**
 * Custom hook for implementing infinite scroll using Intersection Observer.
 * Triggers the onLoadMore callback when the sentinel element comes into view.
 * 
 * @param {Object} options
 * @param {boolean} options.hasMore - Whether there are more items to load
 * @param {Function} options.onLoadMore - Callback to load more items
 * @param {boolean} options.loading - Whether currently loading
 * @param {string} options.rootMargin - Margin around root (default: '200px')
 * @returns {React.RefObject} - Ref to attach to sentinel element
 */
export function useInfiniteScroll({
    hasMore,
    onLoadMore,
    loading,
    rootMargin = '200px'  // Reduced from 400px to prevent premature loading
}) {
    const sentinelRef = useRef(null);
    const isLoadingRef = useRef(false);
    const lastCallTimeRef = useRef(0);
    const debounceMs = 500;  // Minimum time between calls

    // Reset loading lock when loading prop becomes false
    useEffect(() => {
        if (!loading) {
            // Small delay before allowing next load to prevent race conditions
            const timer = setTimeout(() => {
                isLoadingRef.current = false;
            }, 100);
            return () => clearTimeout(timer);
        }
    }, [loading]);

    // Stable callback reference
    const handleLoadMore = useCallback(() => {
        const now = Date.now();

        // Prevent duplicate calls with multiple guards
        if (isLoadingRef.current) {
            return;
        }
        if (loading) {
            return;
        }
        if (!hasMore) {
            return;
        }
        if (now - lastCallTimeRef.current < debounceMs) {
            return;
        }

        // Set synchronous lock immediately
        isLoadingRef.current = true;
        lastCallTimeRef.current = now;
        onLoadMore();
    }, [onLoadMore, loading, hasMore]);

    useEffect(() => {
        const currentSentinel = sentinelRef.current;
        if (!currentSentinel) return;

        // Don't even observe if no more items
        if (!hasMore) return;

        const observer = new IntersectionObserver(
            (entries) => {
                const [entry] = entries;
                if (entry.isIntersecting) {
                    handleLoadMore();
                }
            },
            {
                root: null,
                rootMargin,
                threshold: 0.1
            }
        );

        observer.observe(currentSentinel);

        return () => {
            observer.disconnect();
        };
    }, [handleLoadMore, rootMargin, hasMore]);

    return sentinelRef;
}
