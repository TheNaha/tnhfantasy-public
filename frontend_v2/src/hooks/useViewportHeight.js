import { useEffect, useCallback } from 'react';

/**
 * Custom hook to handle dynamic viewport height on mobile browsers.
 * 
 * On iOS Safari and some Android browsers, 100vh doesn't account for
 * the address bar, causing content to be hidden behind it.
 * 
 * This hook sets a CSS custom property --vh that can be used instead:
 * - height: calc(100 * var(--vh, 1vh))
 * - max-height: calc(85 * var(--vh, 1vh))
 * 
 * @param {boolean} enabled - Whether to enable the hook (default: true)
 * @returns {number} Current vh value in pixels
 */
export function useViewportHeight(enabled = true) {
    const updateVH = useCallback(() => {
        // Calculate 1vh as 1% of window.innerHeight
        const vh = window.innerHeight * 0.01;
        document.documentElement.style.setProperty('--vh', `${vh}px`);
        return vh;
    }, []);

    useEffect(() => {
        if (!enabled) return;

        // Set initial value
        updateVH();

        // Update on resize and orientation change
        const handleResize = () => {
            // Debounce slightly to avoid excessive updates during animations
            requestAnimationFrame(updateVH);
        };

        window.addEventListener('resize', handleResize);
        window.addEventListener('orientationchange', handleResize);

        // Also update when the visual viewport changes (iOS keyboard, etc.)
        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', handleResize);
        }

        return () => {
            window.removeEventListener('resize', handleResize);
            window.removeEventListener('orientationchange', handleResize);
            if (window.visualViewport) {
                window.visualViewport.removeEventListener('resize', handleResize);
            }
        };
    }, [enabled, updateVH]);

    return updateVH;
}

export default useViewportHeight;
