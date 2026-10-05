/* eslint-disable react-refresh/only-export-components */
import { useState, useCallback, useRef, useEffect } from 'react';

/**
 * Custom hook for pull-to-refresh functionality on touch devices.
 * 
 * Usage:
 * ```jsx
 * const { containerRef, pullDistance, isRefreshing, isPulling } = usePullToRefresh({
 *   onRefresh: () => refetchData(),
 *   threshold: 80,
 * });
 * 
 * return (
 *   <div ref={containerRef}>
 *     <PullToRefreshIndicator pullDistance={pullDistance} isRefreshing={isRefreshing} isPulling={isPulling} />
 *     <YourContent />
 *   </div>
 * );
 * ```
 * 
 * @param {Object} options
 * @param {Function} options.onRefresh - Async function to call when refresh is triggered
 * @param {number} options.threshold - Pull distance in pixels to trigger refresh (default: 80)
 * @param {number} options.maxPull - Maximum pull distance in pixels (default: 150)
 * @returns {Object} Hook state and refs
 */
export function usePullToRefresh({
    onRefresh,
    threshold = 80,
    maxPull = 150,
    disabled = false
} = {}) {
    const [isPulling, setIsPulling] = useState(false);
    const [pullDistance, setPullDistance] = useState(0);
    const [isRefreshing, setIsRefreshing] = useState(false);
    
    const containerRef = useRef(null);
    const startY = useRef(0);
    const currentY = useRef(0);

    // The gesture's own state, mirrored into refs.
    //
    // The four touch listeners used to be `useCallback`s closing over
    // `isPulling` and `pullDistance`, which made them change identity on every
    // frame of the gesture — and the attach effect listed them as dependencies.
    // So every `touchmove` tore down and re-added all four listeners, including
    // the `{passive: false}` `touchmove` that carries the `preventDefault`,
    // while a finger was still down. Tearing down a listener the browser is
    // mid-dispatch of loses that event, and re-adding a `passive: false`
    // listener to cancel a scroll that has already started does not stop it, so
    // the page scrolled out from under the pull. Four binds and four unbinds
    // per frame is also the reason this was slow on a long pull.
    //
    // Mirrored synchronously inside the handlers rather than from an effect:
    // these are native listeners, so the state update they make is batched and
    // flushed around the end of the task, and a `touchmove` can be dispatched
    // before the commit that would have republished it.
    const isPullingRef = useRef(false);
    const pullDistanceRef = useRef(0);

    // Latest values for everything else the handlers read, so they can stay
    // stable for the life of the container. Same shape as `useDebounce`'s
    // `latest` ref.
    const latest = useRef(null);
    latest.current = { disabled, isRefreshing, threshold, maxPull, onRefresh };

    const handleTouchStart = useCallback((e) => {
        const { disabled: isDisabled, isRefreshing: busy } = latest.current;
        if (isDisabled || busy) return;

        const target = e.target;
        if (target && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(target.tagName?.toUpperCase())) return;

        // Only enable pull-to-refresh when scrolled to top
        // Prioritize window scroll as it's the most common scroll container for full-page views
                // Find the actual scroll container dynamically
        const getScrollTop = () => {
            // Check if we are inside a custom main scroll container
            const mainContainer = document.getElementById('main-scroll-container');
            if (mainContainer) {
                const style = window.getComputedStyle(mainContainer);
                if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
                    return mainContainer.scrollTop;
                }
            }

            // Fallback to window/document
            return window.scrollY || document.documentElement.scrollTop || containerRef.current?.scrollTop || 0;
        };

        const scrollTop = getScrollTop();

        // Strict top check with small buffer
        if (scrollTop > 0) return;

        startY.current = e.touches[0].clientY;
        currentY.current = startY.current;
        isPullingRef.current = true;
        pullDistanceRef.current = 0;
        setIsPulling(true);
    }, []);

    const handleTouchMove = useCallback((e) => {
        const { disabled: isDisabled, isRefreshing: busy, maxPull: cap } = latest.current;
        if (!isPullingRef.current || isDisabled || busy) return;

        currentY.current = e.touches[0].clientY;
        const diff = currentY.current - startY.current;

        // Only pull down, not up
        if (diff < 0) {
            pullDistanceRef.current = 0;
            setPullDistance(0);
            return;
        }

        // Apply resistance - pull slows down as you go further
        const resistance = 0.5;
        const resistedDiff = Math.min(diff * resistance, cap);
        pullDistanceRef.current = resistedDiff;
        setPullDistance(resistedDiff);

        // Prevent default scroll behavior when pulling
        if (resistedDiff > 10) {
            e.preventDefault();
        }
    }, []);

    const handleTouchEnd = useCallback(async () => {
        const { disabled: isDisabled, threshold: minimum, onRefresh: refresh } = latest.current;
        if (!isPullingRef.current || isDisabled) return;

        const reached = pullDistanceRef.current;
        isPullingRef.current = false;
        pullDistanceRef.current = 0;
        setIsPulling(false);

        if (reached >= minimum && refresh) {
            // Haptic feedback
            if (navigator.vibrate) {
                navigator.vibrate(50);
            }

            setIsRefreshing(true);
            pullDistanceRef.current = minimum;
            setPullDistance(minimum); // Keep indicator visible during refresh

            try {
                await refresh();
            } catch (error) {
                console.error('Pull-to-refresh error:', error);
            } finally {
                setIsRefreshing(false);
                pullDistanceRef.current = 0;
                setPullDistance(0);
            }
        } else {
            // Snap back
            setPullDistance(0);
        }
    }, []);

    // Attach event listeners. The three handlers are stable for the life of the
    // container, so this binds exactly once instead of four times per frame.
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        container.addEventListener('touchstart', handleTouchStart, { passive: true });
        container.addEventListener('touchmove', handleTouchMove, { passive: false });
        container.addEventListener('touchend', handleTouchEnd, { passive: true });
        container.addEventListener('touchcancel', handleTouchEnd, { passive: true });

        return () => {
            container.removeEventListener('touchstart', handleTouchStart);
            container.removeEventListener('touchmove', handleTouchMove);
            container.removeEventListener('touchend', handleTouchEnd);
            container.removeEventListener('touchcancel', handleTouchEnd);
        };
    }, [handleTouchStart, handleTouchMove, handleTouchEnd]);
    
    return {
        containerRef,
        pullDistance,
        isPulling,
        isRefreshing,
        progress: Math.min(pullDistance / threshold, 1),
    };
}

/**
 * Visual indicator component for pull-to-refresh
 */
export function PullToRefreshIndicator({ pullDistance, isRefreshing, isPulling, threshold = 80 }) {
    if (pullDistance <= 0 && !isRefreshing) return null;
    
    const progress = Math.min(pullDistance / threshold, 1);
    const rotation = progress * 180;
    const scale = 0.5 + (progress * 0.5);
    
    return (
        <div
            className="fixed top-0 left-0 right-0 z-[60] flex justify-center items-center overflow-hidden"
            style={{
                height: `${pullDistance}px`,
                opacity: Math.max(0.5, progress),
            }}
        >
            <div 
                className={`w-8 h-8 flex items-center justify-center rounded-full bg-gray-800 border border-gray-700 ${isRefreshing ? 'animate-spin' : ''}`}
                style={{ 
                    transform: isRefreshing ? 'none' : `rotate(${rotation}deg) scale(${scale})`,
                    transition: isPulling ? 'none' : 'transform 0.2s ease-out'
                }}
            >
                {isRefreshing ? (
                    <svg className="w-4 h-4 text-blue-400" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                ) : (
                    <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                        <path strokeLinecap="round" strokeLinejoin="round" d="m19 14-7 7m0 0-7-7m7 7V3" />
                    </svg>
                )}
            </div>
        </div>
    );
}

export default usePullToRefresh;
