import { useEffect } from 'react';

/**
 * Live registrations, newest last.
 *
 * Every `useEscapeKey` handler is a listener on the *same* target (`window`, in
 * the bubble phase), so `stopPropagation()` cannot disarm the siblings — that
 * only stops propagation to other targets, not other listeners on this one.
 * That made one Escape press close a dialog *and* the confirmation stacked on
 * top of it, so confirming a delete inside the Lorebook dialog also discarded
 * the half-finished form behind it.
 *
 * Registration order is mount order, so the most recently mounted live dialog is
 * the topmost one, and letting only that one act restores the expected
 * behaviour: Escape dismisses exactly the thing on top.
 */
let nextRegistrationId = 0;
const liveRegistrations = new Set();

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
/**
 * Is any close-on-Escape dialog currently open?
 *
 * The global keyboard shortcuts (`useKeyboardShortcuts`, and the Dashboard's own
 * listener) guard against modifier keys and against typing in a field, but not
 * against a dialog being open. So `d`/`g`/`m` navigated away from under a modal
 * and discarded its state, `?` opened the shortcuts help *over* the modal, and
 * on the Dashboard `Delete`/`Backspace` called `handleDelete` — deleting an
 * image while a confirmation dialog was open, bypassing the confirmation the
 * pointer path asks for.
 *
 * This is the same registry `useEscapeKey` already maintains, so the answer is
 * known rather than guessed from the DOM: a dialog can close itself on a button
 * without ever registering an Escape handler, and counting DOM overlays would
 * get that wrong.
 */
export function hasOpenEscapeDialog() {
    return liveRegistrations.size > 0;
}

export function useEscapeKey(onEscape, active = true) {
    useEffect(() => {
        if (!active || !onEscape) return undefined;

        const registration = { id: ++nextRegistrationId };
        liveRegistrations.add(registration);

        const onKey = (event) => {
            if (event.key !== 'Escape') return;
            // Let a nested handler opt out by calling preventDefault.
            if (event.defaultPrevented) return;

            let topmost = null;
            for (const candidate of liveRegistrations) {
                if (!topmost || candidate.id > topmost.id) topmost = candidate;
            }
            if (topmost !== registration) return;

            event.stopPropagation();
            onEscape();
        };
        window.addEventListener('keydown', onKey);
        return () => {
            liveRegistrations.delete(registration);
            window.removeEventListener('keydown', onKey);
        };
    }, [active, onEscape]);
}

export default useEscapeKey;
