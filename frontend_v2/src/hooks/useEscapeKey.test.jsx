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

    it('only the topmost live dialog reacts to one Escape press', () => {
        // Every handler is a listener on the same target, so stopPropagation
        // cannot disarm the siblings. Without the topmost-wins rule, opening a
        // ConfirmationModal on top of the LorebookModal and pressing Escape
        // closed both — discarding the half-finished form behind the confirm.
        const onOuter = vi.fn();
        const onInner = vi.fn();
        const { rerender, unmount } = render(
            <>
                <Probe onEscape={onOuter} />
                <Probe onEscape={onInner} />
            </>
        );
        expect(handlers.size).toBe(2);

        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(onInner).toHaveBeenCalledTimes(1);
        expect(onOuter).not.toHaveBeenCalled();

        // The inner dialog closes; the outer one is now topmost and takes over.
        rerender(<Probe onEscape={onOuter} />);
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(onOuter).toHaveBeenCalledTimes(1);
        expect(onInner).toHaveBeenCalledTimes(1);

        unmount();
    });

    it('an inactive dialog does not become topmost', () => {
        const onOuter = vi.fn();
        const onInner = vi.fn();
        render(
            <>
                <Probe onEscape={onOuter} />
                <Probe active={false} onEscape={onInner} />
            </>
        );
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(onOuter).toHaveBeenCalledTimes(1);
        expect(onInner).not.toHaveBeenCalled();
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
