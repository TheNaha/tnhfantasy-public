import { render } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { useEscapeKey } from './useEscapeKey';

function Probe({ active, onEscape }) {
    useEscapeKey(onEscape, active);
    return <div>probe</div>;
}

describe('useEscapeKey', () => {
    let handlers;
    let originalAdd;
    let originalRemove;

    beforeEach(() => {
        handlers = new Set();
        originalAdd = window.addEventListener;
        originalRemove = window.removeEventListener;
        window.addEventListener = (type, fn, opts) => {
            if (type === 'keydown') handlers.add(fn);
            return originalAdd.call(window, type, fn, opts);
        };
        // Must be stubbed too, or the component's real cleanup never updates
        // the tracking set and the "unmounted" assertions test nothing.
        window.removeEventListener = (type, fn, opts) => {
            if (type === 'keydown') handlers.delete(fn);
            return originalRemove.call(window, type, fn, opts);
        };
    });

    afterEach(() => {
        window.addEventListener = originalAdd;
        window.removeEventListener = originalRemove;
        handlers.clear();
    });

    it('registers a listener only while active', () => {
        const { rerender } = render(<Probe active onEscape={() => {}} />);
        expect(handlers.size).toBe(1);

        rerender(<Probe active={false} onEscape={() => {}} />);
        expect(handlers.size).toBe(0);
    });

    it('calls the handler for Escape only', () => {
        const onEscape = vi.fn();
        render(<Probe active onEscape={onEscape} />);
        const [handler] = handlers;

        handler(new KeyboardEvent('keydown', { key: 'Enter' }));
        expect(onEscape).not.toHaveBeenCalled();

        handler(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(onEscape).toHaveBeenCalledTimes(1);
    });

    it('respects defaultPrevented so a nested handler can opt out', () => {
        const onEscape = vi.fn();
        render(<Probe active onEscape={onEscape} />);
        const [handler] = handlers;

        const prevented = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
        Object.defineProperty(prevented, 'defaultPrevented', { value: true });
        handler(prevented);
        expect(onEscape).not.toHaveBeenCalled();
    });

    it('removes the listener on unmount', () => {
        const onEscape = vi.fn();
        const { unmount } = render(<Probe active onEscape={onEscape} />);
        expect(handlers.size).toBe(1);

        unmount();
        // The tracking set is emptied by the component's own cleanup, which is
        // the behaviour under test. Holding a reference to the old handler and
        // calling it would prove nothing — the component no longer calls it.
        expect(handlers.size).toBe(0);

        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(onEscape).not.toHaveBeenCalled();
    });
});
