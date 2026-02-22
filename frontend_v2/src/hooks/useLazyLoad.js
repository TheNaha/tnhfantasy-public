import { useState, useEffect, useRef } from 'react';

/**
 * Custom hook for lazy loading content when it enters the viewport.
 * Uses IntersectionObserver for efficient visibility detection.
 * 
 * @param {Object} options - IntersectionObserver options
 * @param {string} options.rootMargin - Margin around root (default: '100px' for preloading)
 * @param {number} options.threshold - Visibility threshold (default: 0.1)
 * @returns {[React.RefObject, boolean]} - [ref to attach to element, isVisible flag]
 * 
 * @example
 * const [ref, isVisible] = useLazyLoad();
 * return (
 *   <div ref={ref}>
 *     {isVisible && <ExpensiveComponent />}
 *   </div>
 * );
 */
export function useLazyLoad(options = {}) {
    const { rootMargin = '100px', threshold = 0.1 } = options;
    const [isVisible, setIsVisible] = useState(false);
    const ref = useRef(null);

    useEffect(() => {
        const element = ref.current;
        if (!element || isVisible) return;

        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry.isIntersecting) {
                    setIsVisible(true);
                    observer.disconnect();
                }
            },
            { rootMargin, threshold }
        );

        observer.observe(element);

        return () => observer.disconnect();
    }, [rootMargin, threshold, isVisible]);

    return [ref, isVisible];
}

export default useLazyLoad;
