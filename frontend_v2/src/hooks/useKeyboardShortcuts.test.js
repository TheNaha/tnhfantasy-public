import { renderHook } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useKeyboardShortcuts } from './useKeyboardShortcuts';

// Mock react-router-dom
const mockNavigate = vi.fn();
let mockLocation = { pathname: '/' };

vi.mock('react-router-dom', () => ({
    useNavigate: () => mockNavigate,
    useLocation: () => mockLocation,
}));

describe('useKeyboardShortcuts', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockLocation = { pathname: '/' };
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    const triggerKeyDown = (key, options = {}) => {
        const eventInit = {
            key,
            bubbles: true,
            cancelable: true,
            ctrlKey: options.ctrlKey || false,
            metaKey: options.metaKey || false,
            altKey: options.altKey || false,
            shiftKey: options.shiftKey || false,
        };

        const event = new KeyboardEvent('keydown', eventInit);

        // If target is specified, dispatch from that element, otherwise window
        if (options.target) {
            // We need to define the target property if we are not dispatching via dispatchEvent
            // But usually element.dispatchEvent(event) sets the target correctly.
            options.target.dispatchEvent(event);
        } else {
            window.dispatchEvent(event);
        }
    };

    it('navigates to /generate when "g" is pressed', () => {
        renderHook(() => useKeyboardShortcuts());
        triggerKeyDown('g');
        expect(mockNavigate).toHaveBeenCalledWith('/generate');
    });

    it('navigates to / when "d" is pressed', () => {
        mockLocation = { pathname: '/generate' };
        renderHook(() => useKeyboardShortcuts());
        triggerKeyDown('d');
        expect(mockNavigate).toHaveBeenCalledWith('/');
    });

    it('navigates to /models when "m" is pressed', () => {
        renderHook(() => useKeyboardShortcuts());
        triggerKeyDown('m');
        expect(mockNavigate).toHaveBeenCalledWith('/models');
    });

    it('navigates to /advanced when "a" is pressed', () => {
        renderHook(() => useKeyboardShortcuts());
        triggerKeyDown('a');
        expect(mockNavigate).toHaveBeenCalledWith('/advanced');
    });

    it('calls onShowHelp when "?" is pressed', () => {
        const onShowHelp = vi.fn();
        renderHook(() => useKeyboardShortcuts({ onShowHelp }));
        triggerKeyDown('?');
        expect(onShowHelp).toHaveBeenCalled();
    });

    it('calls onEscape when "Escape" is pressed', () => {
        const onEscape = vi.fn();
        renderHook(() => useKeyboardShortcuts({ onEscape }));
        triggerKeyDown('Escape');
        expect(onEscape).toHaveBeenCalled();
    });

    it('does not navigate if modifier keys are pressed', () => {
        renderHook(() => useKeyboardShortcuts());

        triggerKeyDown('g', { ctrlKey: true });
        expect(mockNavigate).not.toHaveBeenCalled();

        triggerKeyDown('g', { metaKey: true });
        expect(mockNavigate).not.toHaveBeenCalled();

        triggerKeyDown('g', { altKey: true });
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('does not navigate if typing in an input', () => {
        renderHook(() => useKeyboardShortcuts());
        const input = document.createElement('input');
        document.body.appendChild(input);

        triggerKeyDown('g', { target: input });
        expect(mockNavigate).not.toHaveBeenCalled();

        document.body.removeChild(input);
    });

    it('does not navigate if typing in a textarea', () => {
        renderHook(() => useKeyboardShortcuts());
        const textarea = document.createElement('textarea');
        document.body.appendChild(textarea);

        triggerKeyDown('g', { target: textarea });
        expect(mockNavigate).not.toHaveBeenCalled();

        document.body.removeChild(textarea);
    });

    it('does not navigate if typing in a contentEditable element', () => {
        renderHook(() => useKeyboardShortcuts());
        const div = document.createElement('div');
        // JSDOM might not support isContentEditable property by default, so we mock it
        Object.defineProperty(div, 'isContentEditable', { value: true, writable: true });
        document.body.appendChild(div);

        triggerKeyDown('g', { target: div });
        expect(mockNavigate).not.toHaveBeenCalled();

        document.body.removeChild(div);
    });

    it('still calls onEscape when pressing Escape inside an input', () => {
        const onEscape = vi.fn();
        renderHook(() => useKeyboardShortcuts({ onEscape }));
        const input = document.createElement('input');
        document.body.appendChild(input);

        triggerKeyDown('Escape', { target: input });
        expect(onEscape).toHaveBeenCalled();

        document.body.removeChild(input);
    });

    it('does not navigate if already on the target page', () => {
        mockLocation = { pathname: '/generate' };
        renderHook(() => useKeyboardShortcuts());
        triggerKeyDown('g');
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('cleans up event listener on unmount', () => {
        const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener');
        const { unmount } = renderHook(() => useKeyboardShortcuts());
        unmount();
        expect(removeEventListenerSpy).toHaveBeenCalledWith('keydown', expect.any(Function));
    });
});
