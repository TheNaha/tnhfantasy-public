import { useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useEscapeKey } from './useEscapeKey';

const NAVIGATION_TARGETS = {
    g: '/generate',
    // Dashboard is /gallery. '/' is the FantasyHub landing page, so this used to
    // navigate somewhere other than what this hook's own docstring and the
    // shortcuts modal promise.
    d: '/gallery',
    m: '/models',
    a: '/advanced',
};

/**
 * Live registrations, newest last.
 *
 * Layout and the Dashboard both register these shortcuts and the Dashboard
 * renders *inside* Layout, so every global key press used to be handled once
 * per live registration: `d`/`g`/`m`/`a` called `navigate()` twice, and one
 * Escape reached every `onEscape` — a dialog closed *and* the gallery closed
 * the lightbox behind it.
 *
 * Navigation is arbitrated by letting only the newest live registration act,
 * which is indistinguishable from the old behaviour because every registration
 * navigates to the same absolute path. Escape is arbitrated by useEscapeKey,
 * which already carries the topmost-wins rule for dialogs.
 */
let nextRegistrationId = 0;
const liveRegistrations = new Set();
let windowListener = null;

/** Newest first. */
function registrationsNewestFirst() {
    return [...liveRegistrations].sort((a, b) => b.id - a.id);
}

function isTypingTarget(target) {
    return !!target && (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        !!target.isContentEditable
    );
}

function handleGlobalKeyDown(event) {
    // Ignore if modifier keys are held (allow Ctrl+C, Ctrl+V, etc.)
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    // Ignore if the user is typing in an input/textarea. Escape is exempt: it
    // has to keep working there, which is why it is handled elsewhere.
    if (isTypingTarget(event.target)) return;

    const key = event.key.toLowerCase();
    const route = NAVIGATION_TARGETS[key];
    if (route) {
        const [newest] = registrationsNewestFirst();
        if (newest && newest.pathname !== route) newest.navigate(route);
        return;
    }

    if (key === '?') {
        // Not a dismiss, so every registration agrees on the outcome: let the
        // newest one that actually provides the action run it, rather than
        // whichever page happens to be nested last.
        const provider = registrationsNewestFirst().find((reg) => reg.onShowHelp);
        provider?.onShowHelp?.();
    }
}

/**
 * Custom hook to handle global keyboard shortcuts
 *
 * Shortcuts:
 * - D: Navigate to Dashboard
 * - G: Navigate to Generate page
 * - M: Navigate to Models page
 * - A: Navigate to Advanced page
 * - ?: Show keyboard shortcuts help
 * - Escape: Close modals (via callback)
 */
export const useKeyboardShortcuts = ({ onEscape, onShowHelp } = {}) => {
    const navigate = useNavigate();
    const location = useLocation();

    useEscapeKey(onEscape, !!onEscape);

    useEffect(() => {
        const registration = {
            id: ++nextRegistrationId,
            pathname: location.pathname,
            navigate,
            onShowHelp,
        };
        liveRegistrations.add(registration);

        if (windowListener === null) {
            windowListener = handleGlobalKeyDown;
            window.addEventListener('keydown', windowListener);
        }

        return () => {
            liveRegistrations.delete(registration);
            if (liveRegistrations.size === 0 && windowListener !== null) {
                window.removeEventListener('keydown', windowListener);
                windowListener = null;
            }
        };
    }, [navigate, location.pathname, onShowHelp]);
}

export default useKeyboardShortcuts;
