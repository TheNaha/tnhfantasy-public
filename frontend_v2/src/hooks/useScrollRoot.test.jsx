/**
 * The gallery's list lives inside `Layout`'s scrollable pane, not the window.
 *
 * Three separate features measured against the wrong box because of it, and all
 * three looked correct in a test that never rendered a real layout:
 *
 *   - infinite scroll's `IntersectionObserver` used the viewport as its root
 *   - the gallery virtualizer was `useWindowVirtualizer`, so its scroll offset
 *     stayed 0 and it rendered only the first viewportful, forever
 *   - the scroll-margin helper added `window.scrollY` (always 0) to a
 *     viewport-relative `rect.top`
 *
 * The virtualizer one is the dangerous direction: bound to `window` it always
 * had a height, so it always rendered *something*. That is why it survived
 * review and a green suite while being broken for every desktop user.
 */
import { render, screen } from '@testing-library/react';
import { useRef } from 'react';
import { describe, expect, it } from 'vitest';

import { resolveScrollRoot, useListVirtualizer } from './useScrollRoot';

function Probe({ count = 5, estimateSize = () => 100 }) {
    const ref = useRef(null);
    const virtualizer = useListVirtualizer(ref, {
        count,
        estimateSize,
        getItemKey: (index) => `row-${index}`,
    });
    return (
        <div ref={ref}>
            <div data-testid="total">{virtualizer.getTotalSize()}</div>
            {virtualizer.getVirtualItems().map((item) => (
                <div key={item.key} data-testid="row">row {item.index}</div>
            ))}
        </div>
    );
}

describe('resolveScrollRoot', () => {
    it('prefers an explicit root over anything it finds', () => {
        const explicit = document.createElement('div');
        const child = document.createElement('div');
        expect(resolveScrollRoot(child, explicit)).toBe(explicit);
    });

    it('walks up to the nearest scrollable ancestor', () => {
        const pane = document.createElement('div');
        pane.style.overflowY = 'auto';
        const middle = document.createElement('div');
        const leaf = document.createElement('div');
        pane.appendChild(middle);
        middle.appendChild(leaf);
        document.body.appendChild(pane);

        expect(resolveScrollRoot(leaf)).toBe(pane);
        pane.remove();
    });

    it('skips ancestors that do not scroll', () => {
        const pane = document.createElement('div');
        pane.style.overflowY = 'auto';
        const hidden = document.createElement('div');
        hidden.style.overflowY = 'hidden';
        const leaf = document.createElement('div');
        pane.appendChild(hidden);
        hidden.appendChild(leaf);
        document.body.appendChild(pane);

        // `hidden` is not a scrollport. Picking it would silently measure
        // against a box that can never move.
        expect(resolveScrollRoot(leaf)).toBe(pane);
        pane.remove();
    });

    it('returns null when there is no scrollable ancestor, so the caller can use the viewport', () => {
        const leaf = document.createElement('div');
        document.body.appendChild(leaf);
        expect(resolveScrollRoot(leaf)).toBeNull();
        leaf.remove();
    });

    it('does not throw when there is no element at all', () => {
        expect(resolveScrollRoot(null)).toBeNull();
        expect(resolveScrollRoot(undefined, undefined)).toBeNull();
    });
});

describe('useListVirtualizer', () => {
    it('renders rows when the scrollport cannot be measured', () => {
        // jsdom has no layout engine, so every element reports a zero height.
        // `useWindowVirtualizer` hid this by reading `window.innerHeight`; a
        // plain `useVirtualizer` pointed at `window` reads `offsetHeight`,
        // which is `undefined` there, and the visible range becomes NaN — an
        // empty list with no error. The hook supplies the window-aware
        // measurement so a zero-height scrollport falls back to the viewport
        // instead of rendering nothing.
        render(<Probe />);
        expect(screen.getAllByTestId('row').length).toBeGreaterThan(0);
    });

    it('tracks count changes, which a memoized options object would freeze', () => {
        const { rerender } = render(<Probe count={2} />);
        expect(screen.getByTestId('total').textContent).toBe('200');

        rerender(<Probe count={7} />);
        expect(screen.getByTestId('total').textContent).toBe('700');
    });
});
