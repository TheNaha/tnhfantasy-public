import { useEffect } from 'react';

/**
 * Close-on-Escape for dialogs.
 *
 * Most of the app's overlays handled the backdrop click and the close button
 * but not the keyboard, so Escape — the single most-expected way to dismiss a
 * dialog — did nothing. Auditing the overlays found 18 of 47 files mentioning
 * Escape at all.
 *
 * Kept as a standalone hook rather than folded into the shared <Modal> so an
 * existing dialog can adopt it without adopting <Modal>'s title/footer
 * structure. Adopting a whole component's markup to gain one behaviour is a
 * bad trade; calling a hook is not.
 */
export function useEscapeKey(onEscape, active = true) {
    useEffect(() => {
        if (!active || !onEscape) return undefined;
        const onKey = (event) => {
            if (event.key !== 'Escape') return;
            // Let a nested handler opt out by calling preventDefault.
            if (event.defaultPrevented) return;
            event.stopPropagation();
            onEscape();
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [active, onEscape]);
}

export default useEscapeKey;
