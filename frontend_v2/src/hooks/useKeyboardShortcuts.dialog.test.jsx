import { render, renderHook } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { useKeyboardShortcuts } from './useKeyboardShortcuts';
import { useEscapeKey } from './useEscapeKey';

/**
 * A single-letter shortcut must not fire while a dialog is open.
 *
 * `useKeyboardShortcuts` guarded modifier keys and "is the user typing", but not
 * "is a dialog open". So `g` navigated away from under an open modal and
 * discarded whatever had been typed into it, and `?` opened the shortcuts help
 * *over* the modal. The Dashboard's own listener had the same gap, where
 * `Delete` reached `handleDelete` with a confirmation dialog already up — the
 * exact action the pointer path asks the user to confirm.
 *
 * The guard reads the registry `useEscapeKey` already maintains, so the answer is
 * asked for rather than inferred from the DOM: a dialog can close itself on a
 * button without ever registering an Escape handler, and counting DOM overlays
 * would get that wrong.
 *
 * Uses the same mock-router harness as `useKeyboardShortcuts.test.js`.
 */

const mockNavigate = vi.fn();
let mockLocation = { pathname: '/' };

vi.mock('react-router-dom', () => ({
    useNavigate: () => mockNavigate,
    useLocation: () => mockLocation,
}));

const press = (key) =>
    window.dispatchEvent(
        new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
    );

/** A dialog that registers itself for Escape, like every `ModalOverlay` does. */
function useTestDialog(active) {
    useEscapeKey(() => {}, active);
}

describe('global shortcuts vs open dialogs', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockLocation = { pathname: '/' };
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('navigates on "g" when no dialog is open', () => {
        renderHook(() => useKeyboardShortcuts());
        press('g');
        expect(mockNavigate).toHaveBeenCalledWith('/generate');
    });

    it('does NOT navigate on "g" while a dialog is open', () => {
        renderHook(() => {
            useTestDialog(true);
            useKeyboardShortcuts();
        });
        press('g');
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('does NOT navigate on any nav shortcut while a dialog is open', () => {
        renderHook(() => {
            useTestDialog(true);
            useKeyboardShortcuts();
        });
        for (const key of ['g', 'd', 'm', 'a']) press(key);
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('still navigates once the dialog is gone', () => {
        const { rerender } = renderHook(
            ({ open }) => {
                useTestDialog(open);
                useKeyboardShortcuts();
            },
            { initialProps: { open: true } }
        );

        press('g');
        expect(mockNavigate).not.toHaveBeenCalled();

        rerender({ open: false });
        press('g');
        expect(mockNavigate).toHaveBeenCalledWith('/generate');
    });

    it('an inert dialog (Escape inactive) does not disarm shortcuts', () => {
        // A dialog mounted but closed must not count as "open", or the app
        // would silently stop responding to shortcuts after visiting one page.
        renderHook(() => {
            useTestDialog(false);
            useKeyboardShortcuts();
        });
        press('g');
        expect(mockNavigate).toHaveBeenCalledWith('/generate');
    });
});

describe('hasOpenEscapeDialog', () => {
    beforeEach(() => vi.clearAllMocks());
    afterEach(() => vi.unmount?.());

    it('reports false when nothing is registered', async () => {
        const { hasOpenEscapeDialog } = await import('./useEscapeKey');
        expect(hasOpenEscapeDialog()).toBe(false);
    });

    it('reports true while a dialog is registered, and false after', async () => {
        const { hasOpenEscapeDialog } = await import('./useEscapeKey');
        const view = render(<div />);
        function Dialog() {
            useTestDialog(true);
            return null;
        }
        const { unmount } = renderHook(() => {
            useTestDialog(true);
        });
        expect(hasOpenEscapeDialog()).toBe(true);
        unmount();
        expect(hasOpenEscapeDialog()).toBe(false);
        view.unmount();
    });
});
